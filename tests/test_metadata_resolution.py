"""Regression tests for evidence completeness, composite keys and rule scope."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from relationship_fixtures import reviewed_edge

from datamate.b0.b02.contracts import (
    BusinessRule,
    ColumnMetadata,
    JoinEdge,
    RuleCatalog,
    TableMetadata,
)
from datamate.b0.b02.rule_compiler import BusinessRuleCompiler
from datamate.b0.b02.rule_resolver import RuleResolver
from datamate.b0.b01.schema_catalog import SchemaCatalogBuilder


class KeyEvidenceTests(unittest.TestCase):
    def test_null_or_missing_key_cells_never_prove_uniqueness(self) -> None:
        for null_row in ({"id": None}, {}):
            with self.subTest(row=null_row):
                table = TableMetadata(
                    "orders",
                    (ColumnMetadata("id"),),
                    primary_key_candidates=("id",),
                    profile_rows=({"id": 1}, null_row),
                    profile_is_complete=True,
                )
                key = SchemaCatalogBuilder().build([table]).key_candidates[0]
                self.assertEqual(key.status, "uncertain")
                self.assertIsInstance(key.evidence, tuple)

    def test_inconsistent_complete_flag_does_not_prove_full_table_key(self) -> None:
        table = TableMetadata(
            "orders",
            (ColumnMetadata("id"),),
            row_count=100,
            profile_rows=({"id": 1}, {"id": 2}),
            profile_is_complete=True,
        )
        key = SchemaCatalogBuilder().build([table]).key_candidates[0]
        self.assertEqual(key.status, "uncertain")

    def test_minimal_composite_key_supplies_structural_grain(self) -> None:
        table = TableMetadata(
            "lines",
            (ColumnMetadata("order_id"), ColumnMetadata("line_no")),
            row_count=4,
            profile_is_complete=True,
            profile_rows=tuple(
                {"order_id": order, "line_no": line}
                for order in (1, 2)
                for line in (1, 2)
            ),
        )
        catalog = SchemaCatalogBuilder().build([table])
        self.assertEqual(
            [key.columns for key in catalog.key_candidates], [("order_id", "line_no")]
        )
        self.assertEqual(catalog.tables[0].grain, "row keyed by (order_id, line_no)")
        self.assertTrue(catalog.tables[0].grain_evidence)

    def test_sample_only_composite_and_duplicate_declared_key_remain_uncertain(
        self,
    ) -> None:
        table = TableMetadata(
            "lines",
            (ColumnMetadata("order"), ColumnMetadata("line")),
            composite_key_candidates=(("order", "line"),),
            profile_rows=({"order": 1, "line": 1}, {"order": 1, "line": 1}),
            profile_is_complete=True,
        )
        catalog = SchemaCatalogBuilder().build([table])
        self.assertEqual(catalog.key_candidates[0].status, "uncertain")
        self.assertIsNone(catalog.tables[0].grain)

    def test_documented_grain_is_preserved(self) -> None:
        table = TableMetadata(
            "lines", (), grain="one product line per order", provenance="README.md:3"
        )
        result = SchemaCatalogBuilder().build([table]).tables[0]
        self.assertEqual(result.grain, table.grain)
        self.assertIn("README.md:3", result.grain_evidence[0])

    def test_declared_fk_requires_complete_coverage_and_correct_cardinality(
        self,
    ) -> None:
        parent = TableMetadata(
            "orders",
            (ColumnMetadata("id"),),
            row_count=2,
            profile_is_complete=True,
            profile_rows=({"id": "a"}, {"id": "b"}),
        )
        child = TableMetadata(
            "payments",
            (ColumnMetadata("order_ref"),),
            row_count=3,
            profile_is_complete=True,
            profile_rows=({"order_ref": "a"}, {"order_ref": "a"}, {"order_ref": "b"}),
        )
        declared = reviewed_edge(
            JoinEdge(
                "payments",
                "order_ref",
                "orders",
                "id",
                "many_to_one",
                "candidate",
                0.9,
                ("README:4 FK mapping",),
            )
        )
        valid = SchemaCatalogBuilder().build([child, parent], [declared]).join_graph[0]
        self.assertEqual(valid.status, "validated")
        orphan = replace(
            child,
            profile_rows=(
                {"order_ref": "a"},
                {"order_ref": "a"},
                {"order_ref": "missing"},
            ),
        )
        self.assertEqual(
            SchemaCatalogBuilder()
            .build([orphan, parent], [declared])
            .join_graph[0]
            .status,
            "invalid",
        )
        mismatch = reviewed_edge(replace(declared, cardinality="one_to_one"))
        self.assertEqual(
            SchemaCatalogBuilder()
            .build([child, parent], [mismatch])
            .join_graph[0]
            .status,
            "invalid",
        )
        sample = replace(child, profile_is_complete=False)
        self.assertEqual(
            SchemaCatalogBuilder()
            .build([sample, parent], [declared])
            .join_graph[0]
            .status,
            "candidate",
        )
        sparse = replace(
            child, row_count=2, profile_rows=({"order_ref": "a"}, {"order_ref": "b"})
        )
        sparse_edge = (
            SchemaCatalogBuilder().build([sparse, parent], [declared]).join_graph[0]
        )
        self.assertEqual(sparse_edge.status, "validated")
        self.assertEqual(sparse_edge.cardinality, "many_to_one")


class RuleResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = RuleResolver()
        self.default = BusinessRule(
            "default",
            "default formula",
            "rulebook:1",
            "split_default",
            100,
            topic="revenue",
        )
        self.industry = BusinessRule(
            "industry",
            "industry formula",
            "rulebook:2",
            "industry",
            200,
            topic="revenue",
            industry="Nhà thuốc",
        )
        self.business = BusinessRule(
            "business", "business formula", "README:1", "business", 300, topic="revenue"
        )
        self.question = BusinessRule(
            "question",
            "question formula",
            "question:q1",
            "question_override",
            400,
            topic="revenue",
            question_id="q1",
        )

    def test_scope_filtering_happens_before_precedence(self) -> None:
        catalog = RuleCatalog(
            (self.default, self.industry, self.business, self.question),
            business_id="biz_1",
        )
        self.assertEqual(
            self.resolver.resolve(catalog, "biz_1", "Nhà thuốc", "q1").rules[0].rule_id,
            "question",
        )
        self.assertEqual(
            self.resolver.resolve(catalog, "biz_1", "Nhà thuốc", "q2").rules[0].rule_id,
            "business",
        )
        shared = RuleCatalog((self.default, self.industry), business_id="biz_1")
        self.assertEqual(
            self.resolver.resolve(shared, "biz_1", "NHÀ THUỐC").rules[0].rule_id,
            "industry",
        )
        self.assertEqual(
            self.resolver.resolve(shared, "biz_1", "Cà phê").rules[0].rule_id, "default"
        )
        self.assertEqual(
            self.resolver.resolve(shared, "biz_1").rules[0].rule_id, "default"
        )

    def test_conflicting_highest_priority_blocks_instead_of_fallback(self) -> None:
        other = replace(self.business, rule_id="other", text="incompatible formula")
        catalog = RuleCatalog((self.default, self.business, other), business_id="biz_1")
        result = self.resolver.resolve(catalog, "biz_1")
        self.assertEqual(result.rules, ())
        self.assertEqual(result.blocked_topics, ("revenue",))

    def test_invalid_highest_rule_is_not_silently_replaced(self) -> None:
        catalog = RuleCatalog(
            (self.default, replace(self.business, status="invalid")),
            business_id="biz_1",
        )
        self.assertEqual(
            self.resolver.resolve(catalog, "biz_1").blocked_topics, ("revenue",)
        )

    def test_catalog_isolation_and_unscoped_business_rules(self) -> None:
        with self.assertRaises(ValueError):
            self.resolver.resolve(
                RuleCatalog((self.business,), business_id="biz_2"), "biz_1"
            )
        self.assertEqual(
            self.resolver.resolve(RuleCatalog((self.business,)), "biz_1").rules, ()
        )

    def test_conflicting_rule_cannot_be_compiled(self) -> None:
        rule = replace(
            self.business,
            status="conflict",
            expression={"op": "eq", "field": "status", "value": "done"},
        )
        with self.assertRaises(ValueError):
            BusinessRuleCompiler().compile_rule(rule, SchemaCatalogBuilder().build([]))


class RuleIngestionRegressionTests(unittest.TestCase):
    def test_last_table_rule_before_blank_line_is_not_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rulebook.md"
            path.write_text(
                "## 6. Theo ngành\n### Nhà thuốc\n| Luật | Mặc định |\n|---|---|\n"
                "| Thuốc kê đơn | Theo danh mục thuốc |\n\n## 7. Khác\nRule khác\n",
                encoding="utf-8",
            )
            catalog = BusinessRuleCompiler().ingest_documents([path])
        self.assertEqual(len(catalog.rules), 2)
        self.assertEqual(catalog.rules[0].topic, "Thuốc kê đơn")
        self.assertEqual(catalog.rules[0].industry, "Nhà thuốc")
        self.assertEqual(catalog.rules[1].scope, "split_default")


if __name__ == "__main__":
    unittest.main()
