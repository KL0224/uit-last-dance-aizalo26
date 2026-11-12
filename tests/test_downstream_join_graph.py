"""Read JSON contracts and exercise validated paths and fanout on DuckDB fixtures."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace

import duckdb
from relationship_fixtures import reviewed_edge

from datamate.ingestion.contracts import (
    ColumnMetadata,
    JoinEdge,
    TableMetadata,
)
from datamate.context.contracts import (
    ContractBuilder,
    RuleCatalog,
)
from datamate.ingestion.join_graph import JoinGraphNavigator, JoinPredicateCompiler
from datamate.ingestion.metadata_adapter import BusinessContextSchemaReader
from datamate.ingestion.schema_catalog import SchemaCatalogBuilder


class DownstreamJoinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = duckdb.connect(":memory:")
        self.addCleanup(self.connection.close)
        definitions = {
            "customers": (("customer_id",), [("c1",), ("c2",)]),
            "orders": (
                ("order_id", "customer_id", "total"),
                [("o1", "c1", "100"), ("o2", "c1", "200")],
            ),
            "lines": (
                ("order_id", "line_no", "product_id"),
                [("o1", "1", "p1"), ("o1", "2", "p2"), ("o2", "1", "p1")],
            ),
            "products": (("product_id",), [("p1",), ("p2",)]),
            "payments": (
                ("order_id", "amount"),
                [("o1", "40"), ("o1", "60"), ("o2", "200")],
            ),
            "allocations": (
                ("order_id", "line_no", "lot_id"),
                [
                    ("o1", "1", "L1"),
                    ("o1", "1", "L2"),
                    ("o1", "2", "L1"),
                    ("o2", "1", "L1"),
                ],
            ),
        }
        tables = []
        for name, (columns, rows) in definitions.items():
            self.connection.execute(
                f'CREATE TABLE "{name}" ({", ".join(c + " VARCHAR" for c in columns)})'
            )
            self.connection.executemany(
                f'INSERT INTO "{name}" VALUES ({", ".join("?" for _ in columns)})', rows
            )
            tables.append(
                TableMetadata(
                    name,
                    tuple(ColumnMetadata(c, "VARCHAR") for c in columns),
                    grain=f"fixture {name} grain",
                    profile_is_complete=True,
                    profile_rows=tuple(dict(zip(columns, row)) for row in rows),
                )
            )
        declarations = []
        for left, right, pairs in (
            ("orders", "customers", (("customer_id", "customer_id"),)),
            ("lines", "orders", (("order_id", "order_id"),)),
            ("lines", "products", (("product_id", "product_id"),)),
            ("payments", "orders", (("order_id", "order_id"),)),
            (
                "allocations",
                "lines",
                (("order_id", "order_id"), ("line_no", "line_no")),
            ),
        ):
            declarations.append(
                reviewed_edge(
                    JoinEdge(
                        left,
                        pairs[0][0],
                        right,
                        pairs[0][1],
                        "many_to_one",
                        "candidate",
                        0.0,
                        (),
                        additional_key_pairs=pairs[1:],
                    )
                )
            )
        self.catalog = SchemaCatalogBuilder().build(tables, declarations)

    def test_contract_roundtrip_validated_path_and_compiled_query(self) -> None:
        payload = json.loads(
            json.dumps(
                ContractBuilder()
                .build("fixture", self.catalog, RuleCatalog(()))
                .to_dict()
            )
        )
        catalog = BusinessContextSchemaReader().read(payload)
        navigator = JoinGraphNavigator()
        path = navigator.find_path(catalog, "customers", "products")
        self.assertIsNotNone(path)
        self.assertEqual(len(path), 3)
        current = "customers"
        sql = 'SELECT COUNT(*) FROM "customers"'
        for edge in path:
            target = edge.right_table if edge.left_table == current else edge.left_table
            sql += (
                f' JOIN "{target}" ON {JoinPredicateCompiler().compile(edge, catalog)}'
            )
            current = target
        actual = self.connection.execute(sql).fetchone()[0]
        reference = self.connection.execute(
            "SELECT COUNT(*) FROM lines WHERE order_id IN (SELECT order_id FROM orders WHERE customer_id IN (SELECT customer_id FROM customers)) AND product_id IN (SELECT product_id FROM products)"
        ).fetchone()[0]
        self.assertEqual(actual, reference)
        self.assertEqual(actual, 3)
        result = navigator.describe_path(catalog, "customers", "products")
        self.assertEqual(result.status, "validated_path")
        self.assertTrue(result.warnings)

    def test_no_validated_path_is_explicit_and_unsafe_shortcut_is_ignored(self) -> None:
        shortcut = JoinEdge(
            "customers",
            "customer_id",
            "products",
            "product_id",
            "one_to_one",
            "uncertain",
            1.0,
            (),
        )
        catalog = replace(
            self.catalog, join_graph=self.catalog.join_graph + (shortcut,)
        )
        path = JoinGraphNavigator().find_path(catalog, "customers", "products")
        self.assertEqual(len(path), 3)
        for status in ("uncertain", "invalid", "candidate"):
            unsafe = replace(
                catalog,
                join_graph=tuple(replace(e, status=status) for e in catalog.join_graph),
            )
            result = JoinGraphNavigator().describe_path(unsafe, "customers", "products")
            self.assertEqual(result.status, "no_validated_path")
            self.assertEqual(result.path, ())
            with self.assertRaises(ValueError):
                JoinPredicateCompiler().compile(unsafe.join_graph[0], unsafe)

    def test_composite_and_child_branches_expose_measured_fanout(self) -> None:
        navigator = JoinGraphNavigator()
        for child in ("lines", "payments"):
            result = navigator.describe_path(self.catalog, "orders", child)
            self.assertTrue(result.warnings)
            edge = result.path[0]
            predicate = JoinPredicateCompiler().compile(edge, self.catalog)
            total = self.connection.execute(
                f'SELECT SUM(CAST(orders.total AS INTEGER)) FROM orders JOIN "{child}" ON {predicate}'
            ).fetchone()[0]
            self.assertEqual(total, 400)
        result = navigator.describe_path(self.catalog, "lines", "allocations")
        self.assertTrue(result.warnings)
        predicate = JoinPredicateCompiler().compile(result.path[0], self.catalog)
        self.assertIn('"lines"."line_no"', predicate)
        composite_count = self.connection.execute(
            f"SELECT COUNT(*) FROM lines JOIN allocations ON {predicate}"
        ).fetchone()[0]
        invoice_count = self.connection.execute(
            "SELECT COUNT(*) FROM lines JOIN allocations ON lines.order_id=allocations.order_id"
        ).fetchone()[0]
        self.assertEqual((composite_count, invoice_count), (4, 7))
        total = self.connection.execute(
            "SELECT SUM(CAST(orders.total AS INTEGER)) FROM orders JOIN lines USING(order_id) JOIN payments USING(order_id)"
        ).fetchone()[0]
        self.assertEqual(total, 600)

    def test_reader_rejects_forged_validated_status_without_attestation(self) -> None:
        payload = json.loads(
            json.dumps(
                ContractBuilder()
                .build("fixture", self.catalog, RuleCatalog(()))
                .to_dict()
            )
        )
        edge = next(
            e
            for e in payload["schema_catalog"]["join_graph"]
            if e["status"] == "validated"
        )
        edge.pop("relationship_evidence")
        with self.assertRaisesRegex(ValueError, "attestation"):
            BusinessContextSchemaReader().read(payload)


if __name__ == "__main__":
    unittest.main()
