"""Execute compound joins and numeric rules to verify SQL semantics."""

from __future__ import annotations

import sqlite3
import unittest
from dataclasses import replace

from datamate.contracts import (
    ColumnMetadata,
    ContractBuilder,
    JoinEdge,
    RuleCatalog,
    SchemaCatalog,
    TableMetadata,
)
from datamate.join_graph import JoinGraphNavigator, JoinPredicateCompiler
from datamate.rule_compiler import BusinessRuleCompiler
from datamate.schema_catalog import SchemaCatalogBuilder


class CompositeJoinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parent = TableMetadata(
            "lines",
            (ColumnMetadata("order_id"), ColumnMetadata("line_no")),
            profile_is_complete=True,
            profile_rows=(
                {"order_id": 1, "line_no": 1},
                {"order_id": 1, "line_no": 2},
                {"order_id": 2, "line_no": 1},
            ),
        )
        self.child = TableMetadata(
            "allocations",
            (ColumnMetadata("order_ref"), ColumnMetadata("line_ref")),
            profile_is_complete=True,
            profile_rows=(
                {"order_ref": 1, "line_ref": 1},
                {"order_ref": 1, "line_ref": 1},
                {"order_ref": 1, "line_ref": 2},
            ),
        )
        self.edge = JoinEdge(
            "allocations",
            "order_ref",
            "lines",
            "order_id",
            "many_to_one",
            "candidate",
            0.9,
            ("README: allocation references the order and its line",),
            additional_key_pairs=(("line_ref", "line_no"),),
        )

    def test_tuple_join_is_validated_and_executes_without_cross_product(self) -> None:
        catalog = SchemaCatalogBuilder().build([self.parent, self.child], [self.edge])
        edge = catalog.join_graph[0]
        self.assertEqual(edge.status, "validated")
        predicate = JoinPredicateCompiler().compile(edge, catalog)
        with sqlite3.connect(":memory:") as connection:
            connection.execute("CREATE TABLE lines (order_id INTEGER, line_no INTEGER)")
            connection.execute(
                "CREATE TABLE allocations (order_ref INTEGER, line_ref INTEGER)"
            )
            connection.executemany(
                "INSERT INTO lines VALUES (?, ?)", [(1, 1), (1, 2), (2, 1)]
            )
            connection.executemany(
                "INSERT INTO allocations VALUES (?, ?)", [(1, 1), (1, 1), (1, 2)]
            )
            actual = connection.execute(
                f"SELECT COUNT(*) FROM lines JOIN allocations ON {predicate}"
            ).fetchone()[0]
        self.assertEqual(actual, 3)
        payload = ContractBuilder().build("biz", catalog, RuleCatalog(())).to_dict()
        self.assertEqual(
            payload["schema_catalog"]["join_graph"][0]["additional_key_pairs"],
            (("line_ref", "line_no"),),
        )

    def test_individual_values_do_not_prove_tuple_referential_coverage(self) -> None:
        orphan = replace(self.child, profile_rows=({"order_ref": 2, "line_ref": 2},))
        edge = (
            SchemaCatalogBuilder()
            .build([self.parent, orphan], [self.edge])
            .join_graph[0]
        )
        self.assertEqual(edge.status, "invalid")

    def test_unknown_composite_column_is_rejected_by_contract(self) -> None:
        edge = replace(self.edge, additional_key_pairs=(("missing", "line_no"),))
        catalog = SchemaCatalog((self.parent, self.child), join_graph=(edge,))
        with self.assertRaises(ValueError):
            ContractBuilder().build("biz", catalog, RuleCatalog(()))

    def test_only_validated_paths_are_available(self) -> None:
        catalog = SchemaCatalogBuilder().build([self.parent, self.child], [self.edge])
        navigator = JoinGraphNavigator()
        path = navigator.find_path(catalog, "lines", "allocations")
        self.assertEqual(path, (catalog.join_graph[0],))
        unvalidated = replace(
            catalog, join_graph=(replace(catalog.join_graph[0], status="uncertain"),)
        )
        self.assertIsNone(navigator.find_path(unvalidated, "lines", "allocations"))
        with self.assertRaises(ValueError):
            JoinPredicateCompiler().compile(unvalidated.join_graph[0], unvalidated)

    def test_same_name_composite_identity_produces_uncertain_candidate(self) -> None:
        child = TableMetadata(
            "returns",
            self.parent.columns,
            profile_rows=({"order_id": 1, "line_no": 1}, {"order_id": 1, "line_no": 1}),
        )
        catalog = SchemaCatalogBuilder().build([self.parent, child])
        edges = [edge for edge in catalog.join_graph if len(edge.key_pairs) == 2]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].status, "uncertain")


class FormulaExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = SchemaCatalogBuilder().build(
            [
                TableMetadata(
                    "sales",
                    tuple(
                        ColumnMetadata(name, "INTEGER")
                        for name in ("order_id", "amount", "quantity", "unit_cost")
                    ),
                )
            ]
        )
        self.compiler = BusinessRuleCompiler()

    def test_gross_profit_formula_uses_fields_and_preserves_nulls(self) -> None:
        expression = {
            "op": "sum",
            "item": {
                "op": "sub",
                "left": {"op": "field", "field": "amount"},
                "right": {
                    "op": "mul",
                    "left": {"op": "field", "field": "quantity"},
                    "right": {"op": "field", "field": "unit_cost"},
                },
            },
        }
        sql, parameters = self.compiler.compile_expression(expression, self.schema)
        with sqlite3.connect(":memory:") as connection:
            connection.execute(
                "CREATE TABLE sales (order_id, amount, quantity, unit_cost)"
            )
            connection.executemany(
                "INSERT INTO sales VALUES (?, ?, ?, ?)",
                [(1, 100, 2, 30), (2, 180, 3, 40)],
            )
            self.assertEqual(
                connection.execute(f"SELECT {sql} FROM sales", parameters).fetchone()[
                    0
                ],
                100,
            )
            connection.execute("DELETE FROM sales")
            self.assertIsNone(
                connection.execute(f"SELECT {sql} FROM sales", parameters).fetchone()[0]
            )

    def test_distinct_orders_counts_entity_instead_of_lines(self) -> None:
        sql, parameters = self.compiler.compile_expression(
            {"op": "count_distinct", "field": "order_id"}, self.schema
        )
        with sqlite3.connect(":memory:") as connection:
            result = connection.execute(
                f"WITH sales(order_id) AS (VALUES (1),(1),(2),(NULL)) SELECT {sql} FROM sales",
                parameters,
            ).fetchone()[0]
        self.assertEqual(result, 2)

    def test_fractional_division_and_zero_denominator(self) -> None:
        for denominator, expected in ((2, 2.5), (0, None)):
            sql, params = self.compiler.compile_expression(
                {"op": "div", "left": 5, "right": denominator}, self.schema
            )
            with sqlite3.connect(":memory:") as connection:
                self.assertEqual(
                    connection.execute(f"SELECT {sql}", params).fetchone()[0], expected
                )

    def test_nested_aggregate_and_non_scalar_parameters_are_rejected(self) -> None:
        expressions = (
            {"op": "sum", "item": {"op": "count_distinct", "field": "order_id"}},
            {"op": "in", "field": "order_id", "values": [{"sql": "bad"}]},
            {"op": "literal", "value": float("nan")},
        )
        for expression in expressions:
            with (
                self.subTest(expression=expression),
                self.assertRaises((TypeError, ValueError)),
            ):
                self.compiler.compile_expression(expression, self.schema)


if __name__ == "__main__":
    unittest.main()
