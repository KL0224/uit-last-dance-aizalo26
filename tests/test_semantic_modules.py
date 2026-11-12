"""Unit tests for DataMate B01/B02 and their shared contract."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from datamate.context.contracts import (
    BusinessRule,
    ColumnMetadata,
    ContractBuilder,
    JoinEdge,
    RuleCatalog,
    SchemaCatalog,
    TableMetadata,
)
from datamate.context.rule_compiler import BusinessRuleCompiler
from datamate.ingestion.schema_catalog import SchemaCatalogBuilder


class SchemaCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = SchemaCatalogBuilder()

    def test_primary_key_candidate_requires_non_null_unique_profile(self) -> None:
        good = TableMetadata(
            "orders",
            (ColumnMetadata("order_id"),),
            primary_key_candidates=("order_id",),
            profile_rows=({"order_id": 1}, {"order_id": 2}),
            profile_is_complete=True,
        )
        bad = TableMetadata(
            "bad",
            (ColumnMetadata("id"),),
            primary_key_candidates=("id",),
            profile_rows=({"id": 1}, {"id": 1}),
        )
        catalog = self.builder.build([good, bad])
        self.assertEqual(
            [item.status for item in catalog.key_candidates], ["candidate", "uncertain"]
        )

    def test_primary_key_can_be_inferred_from_complete_profile_statistics(self) -> None:
        table = TableMetadata(
            "orders",
            (
                ColumnMetadata("order_id", null_ratio=0, cardinality=10),
                ColumnMetadata("status", null_ratio=0, cardinality=3),
            ),
            row_count=10,
            profile_is_complete=True,
        )
        catalog = self.builder.build([table])
        self.assertEqual(
            [(item.columns, item.status) for item in catalog.key_candidates],
            [(("order_id",), "candidate")],
        )

    def test_column_name_match_without_profile_does_not_create_join(self) -> None:
        parent = TableMetadata("parent", (ColumnMetadata("id"),))
        child = TableMetadata("child", (ColumnMetadata("id"),))
        self.assertEqual(self.builder.build([parent, child]).join_graph, ())

    def test_relationship_candidates_include_cardinality_and_fanout_warning(
        self,
    ) -> None:
        parent = TableMetadata(
            "parent",
            (ColumnMetadata("order_id"),),
            profile_rows=({"order_id": 1}, {"order_id": 2}),
        )
        child = TableMetadata(
            "child",
            (ColumnMetadata("order_id"),),
            profile_rows=({"order_id": 1}, {"order_id": 1}, {"order_id": 2}),
        )
        edge = self.builder.build([parent, child]).join_graph[0]
        self.assertEqual(edge.status, "uncertain")
        self.assertEqual(edge.cardinality, "one_to_many")
        self.assertTrue(edge.fanout_warning)

    def test_many_to_many_relationship_warns_about_fanout(self) -> None:
        left = TableMetadata(
            "left_table",
            (ColumnMetadata("key"),),
            profile_rows=({"key": 1}, {"key": 1}, {"key": 2}),
        )
        right = TableMetadata(
            "right_table",
            (ColumnMetadata("key"),),
            profile_rows=({"key": 1}, {"key": 2}, {"key": 2}),
        )
        edge = self.builder.build([left, right]).join_graph[0]
        self.assertEqual(edge.cardinality, "many_to_many")
        self.assertTrue(edge.fanout_warning)

    def test_different_column_names_can_form_uncertain_candidate_from_values(
        self,
    ) -> None:
        orders = TableMetadata(
            "orders",
            (ColumnMetadata("order_id"),),
            profile_rows=({"order_id": "a"}, {"order_id": "b"}),
        )
        payments = TableMetadata(
            "payments",
            (ColumnMetadata("invoice_ref"),),
            profile_rows=(
                {"invoice_ref": "a"},
                {"invoice_ref": "a"},
                {"invoice_ref": "b"},
            ),
        )
        edge = self.builder.build([orders, payments]).join_graph[0]
        self.assertEqual(edge.status, "uncertain")
        self.assertEqual(edge.cardinality, "one_to_many")
        self.assertTrue(any("names differ" in item for item in edge.evidence))

    def test_declared_join_is_candidate_and_invalid_reference_is_warning(self) -> None:
        left = TableMetadata("a", (ColumnMetadata("order_id"),))
        right = TableMetadata("b", (ColumnMetadata("invoice_ref"),))
        declared = JoinEdge(
            "a",
            "order_id",
            "b",
            "invoice_ref",
            "one_to_many",
            "confirmed",
            0.99,
            ("source FK",),
        )
        catalog = self.builder.build([left, right], [declared])
        self.assertEqual(catalog.join_graph[0].status, "candidate")
        invalid = JoinEdge(
            "a", "missing", "b", "invoice_ref", "unknown", "candidate", 0.5, ()
        )
        self.assertEqual(
            len(self.builder.build([left, right], [invalid]).join_graph), 0
        )


class RuleCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = BusinessRuleCompiler()
        self.schema = SchemaCatalogBuilder().build(
            [
                TableMetadata(
                    "orders",
                    (
                        ColumnMetadata("status"),
                        ColumnMetadata("amount"),
                        ColumnMetadata("order_id"),
                    ),
                )
            ]
        )

    def test_markdown_ingestion_is_stable_and_preserves_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "README.md"
            source.write_text(
                "# Shop\n\n| Rule | Meaning |\n|---|---|\n| Status | `status` must be active |\n",
                encoding="utf-8",
            )
            one = self.compiler.ingest_documents([source], "biz_1", self.schema)
            two = self.compiler.ingest_documents([source], "biz_1", self.schema)
        self.assertEqual(one.rules, two.rules)
        self.assertEqual(one.rules[0].scope, "business")
        self.assertEqual(one.rules[0].required_fields, ("status",))
        self.assertIn("README.md:5", one.rules[0].source)

    def test_rule_precedence_and_industry_subheading_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rulebook.md"
            source.write_text(
                "# Rulebook\n\n## Default rules\nRule A.\n\n## Rules by industry\n### Pharmacy\nPrescription rule.\n",
                encoding="utf-8",
            )
            catalog = self.compiler.ingest_documents([source])
        self.assertEqual(catalog.rules[0].scope, "split_default")
        self.assertEqual(catalog.rules[1].scope, "industry")
        self.assertGreater(catalog.rules[1].precedence, catalog.rules[0].precedence)

    def test_structured_expression_is_parameterized(self) -> None:
        expression = {
            "op": "and",
            "items": [
                {"op": "eq", "field": "status", "value": "Hoàn thành"},
                {"op": "gte", "field": "amount", "value": 100},
            ],
        }
        catalog = self.compiler.add_structured_rule(
            "r1", "valid orders", "README.md:10", "business", expression, self.schema
        )
        self.assertEqual(catalog.rules[0].status, "validated")
        sql, params = self.compiler.compile_expression(expression, self.schema)
        self.assertEqual(sql, '("status" = ? AND "amount" >= ?)')
        self.assertEqual(params, ("Hoàn thành", 100))

    def test_missing_field_and_unsupported_operator_are_rejected(self) -> None:
        missing = self.compiler.add_structured_rule(
            "r1",
            "x",
            "source",
            "business",
            {"op": "eq", "field": "missing", "value": 1},
            self.schema,
        )
        self.assertEqual(missing.rules[0].status, "invalid")
        with self.assertRaises(ValueError):
            self.compiler.compile_expression(
                {"op": "raw_sql", "sql": "DROP TABLE x"}, self.schema
            )

    def test_ambiguous_unqualified_field_is_rejected(self) -> None:
        schema = SchemaCatalogBuilder().build(
            [
                TableMetadata("orders", (ColumnMetadata("id"),)),
                TableMetadata("products", (ColumnMetadata("id"),)),
            ]
        )
        expression = {"op": "eq", "field": "id", "value": 1}
        catalog = self.compiler.add_structured_rule(
            "amb", "ambiguous", "source", "business", expression, schema
        )
        self.assertEqual(catalog.rules[0].status, "invalid")
        qualified_sql, _ = self.compiler.compile_expression(
            {"op": "eq", "field": "orders.id", "value": 1}, schema
        )
        self.assertEqual(qualified_sql, '"orders"."id" = ?')

    def test_conflicting_topic_is_marked_for_review(self) -> None:
        first = self.compiler.add_structured_rule(
            "r1",
            "A",
            "a",
            "business",
            {"op": "eq", "field": "status", "value": "A"},
            self.schema,
            topic="valid_status",
        )
        second = self.compiler.add_structured_rule(
            "r2",
            "B",
            "b",
            "business",
            {"op": "eq", "field": "status", "value": "B"},
            self.schema,
            first,
            topic="valid_status",
        )
        self.assertEqual(
            [rule.status for rule in second.rules], ["conflict", "conflict"]
        )
        self.assertTrue(second.warnings)


class ContractTests(unittest.TestCase):
    def test_context_serializes_with_version_and_keeps_missing_metadata_null(
        self,
    ) -> None:
        schema = SchemaCatalogBuilder().build(
            [
                TableMetadata(
                    "orders", (ColumnMetadata("id"),), profile_rows=({"id": 1},)
                )
            ]
        )
        context = ContractBuilder().build("biz_1", schema, RuleCatalog(()))
        serialized = context.to_dict()
        self.assertEqual(serialized["contract_version"], "1.0")
        self.assertIsNone(serialized["data_profiling"])
        self.assertNotIn("profile_rows", serialized["schema_catalog"]["tables"][0])
        self.assertEqual(json.loads(json.dumps(serialized))["business_id"], "biz_1")

    def test_context_rejects_edges_to_missing_columns(self) -> None:
        schema = SchemaCatalogBuilder().build(
            [
                TableMetadata("a", (ColumnMetadata("id"),)),
                TableMetadata("b", (ColumnMetadata("ref"),)),
            ],
            [JoinEdge("a", "not_id", "b", "ref", "unknown", "candidate", 0.2, ())],
        )
        schema = SchemaCatalog(
            tables=schema.tables,
            join_graph=(
                JoinEdge("a", "not_id", "b", "ref", "unknown", "candidate", 0.2, ()),
            ),
        )
        with self.assertRaises(ValueError):
            ContractBuilder().build("biz", schema, RuleCatalog(()))

    def test_context_rejects_rule_catalog_from_another_business(self) -> None:
        schema = SchemaCatalogBuilder().build([])
        with self.assertRaises(ValueError):
            ContractBuilder().build(
                "biz_2", schema, RuleCatalog((), business_id="biz_1")
            )

    def test_rule_precedence_values_are_explicit_in_context(self) -> None:
        schema = SchemaCatalogBuilder().build([])
        rule = BusinessRule("r", "text", "source", "industry", 200)
        context = ContractBuilder().build("biz", schema, RuleCatalog((rule,)))
        self.assertEqual(
            context.to_dict()["rule_catalog"]["rules"][0]["precedence"], 200
        )

    def test_end_to_end_business_context_combines_b01_and_b02(self) -> None:
        schema = SchemaCatalogBuilder().build(
            [
                TableMetadata(
                    "orders",
                    (ColumnMetadata("order_id"), ColumnMetadata("status")),
                    row_count=2,
                    primary_key_candidates=("order_id",),
                    profile_rows=(
                        {"order_id": "o1", "status": "done"},
                        {"order_id": "o2", "status": "cancelled"},
                    ),
                    profile_is_complete=True,
                )
            ]
        )
        compiler = BusinessRuleCompiler()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "README.md"
            source.write_text(
                "# Shop\nRevenue uses completed orders.\n", encoding="utf-8"
            )
            rules = compiler.ingest_documents([source], "biz_1", schema)
        rules = compiler.add_structured_rule(
            "valid_status",
            "completed status",
            "README.md:2",
            "business",
            {"op": "eq", "field": "status", "value": "done"},
            schema,
            rules,
            topic="valid_order",
        )
        context = ContractBuilder().build(
            "biz_1", schema, rules, data_profiling={"orders": {"row_count": 2}}
        )
        payload = context.to_dict()
        self.assertEqual(
            payload["schema_catalog"]["key_candidates"][0]["status"], "candidate"
        )
        self.assertEqual(payload["rule_catalog"]["rules"][-1]["status"], "validated")
        self.assertEqual(payload["data_profiling"]["orders"]["row_count"], 2)


if __name__ == "__main__":
    unittest.main()
