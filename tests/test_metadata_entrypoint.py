"""Exercise the producer boundary, orchestrator and runnable JSON entry point."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path

from relationship_fixtures import reviewed_edge

from datamate.b0.b02.cli import main
from datamate.b0.b02.context_service import BusinessContextService
from datamate.b0.b02.contracts import ContractBuilder
from datamate.b0.b01.contracts import JoinEdge
from datamate.b0.b01.metadata_adapter import JSONMetadataProvider
from datamate.b0.b02.rule_compiler import BusinessRuleCompiler
from datamate.b0.b01.schema_catalog import SchemaCatalogBuilder


def _payload() -> dict:
    return {
        "metadata_version": "1.0",
        "business_id": "biz_1",
        "tables": [
            {
                "name": "orders",
                "columns": [{"name": "id", "data_type": "INTEGER"}],
                "row_count": 2,
                "profile_is_complete": True,
                "profile_rows": [{"id": 1}, {"id": 2}],
            },
            {
                "name": "payments",
                "columns": [{"name": "order_ref"}],
                "row_count": 3,
                "profile_is_complete": True,
                "profile_rows": [{"order_ref": 1}, {"order_ref": 1}, {"order_ref": 2}],
            },
        ],
        "relationships": [
            {
                "left_table": "payments",
                "left_column": "order_ref",
                "right_table": "orders",
                "right_column": "id",
                "cardinality": "many_to_one",
                "evidence": ["README:4 payment order reference"],
                "relationship_evidence": asdict(
                    reviewed_edge(
                        JoinEdge(
                            "payments",
                            "order_ref",
                            "orders",
                            "id",
                            "many_to_one",
                            "candidate",
                            0.0,
                            (),
                        ),
                        "biz_1",
                    ).relationship_evidence
                ),
            }
        ],
        "data_profiling": {"orders": {"row_count": 2}},
    }


class MetadataBoundaryTests(unittest.TestCase):
    def test_legacy_plain_evidence_still_parses_but_cannot_grant_validation(
        self,
    ) -> None:
        payload = _payload()
        payload["relationships"][0].pop("relationship_evidence")
        metadata = JSONMetadataProvider("unused.json").from_dict(payload, "biz_1")
        catalog = SchemaCatalogBuilder().build(
            list(metadata.tables), list(metadata.relationships), business_id="biz_1"
        )
        self.assertEqual(catalog.join_graph[0].status, "candidate")
        context = ContractBuilder().build(
            "biz_1", catalog, BusinessRuleCompiler().ingest_documents([], "biz_1")
        )
        self.assertEqual(context.contract_version, "1.0")

    def test_provider_rejects_invalid_version_scope_and_unknown_fields(self) -> None:
        provider = JSONMetadataProvider("unused.json")
        for change in (
            {"metadata_version": "2.0"},
            {"business_id": "biz_other"},
            {"unknown_key": 1},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                provider.from_dict(_payload() | change, "biz_1")

    def test_provider_rejects_bad_profile_types_counts_and_relationships(self) -> None:
        provider = JSONMetadataProvider("unused.json")
        for key, value in (
            ("profile_is_complete", "yes"),
            ("row_count", True),
            ("row_count", 100),
        ):
            payload = _payload()
            payload["tables"][0][key] = value
            with self.subTest(field=key), self.assertRaises((TypeError, ValueError)):
                provider.from_dict(payload, "biz_1")
        payload = _payload()
        payload["relationships"][0]["right_column"] = "missing"
        with self.assertRaises(ValueError):
            provider.from_dict(payload, "biz_1")

    def test_service_preserves_producer_metadata_and_document_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.json"
            path.write_text(json.dumps(_payload()), encoding="utf-8")
            service = BusinessContextService(
                JSONMetadataProvider(path),
                SchemaCatalogBuilder(),
                BusinessRuleCompiler(),
                ContractBuilder(),
            )
            context = service.prepare("biz_1", [Path(directory) / "missing.md"])
        self.assertEqual(context.schema_catalog.join_graph[0].status, "validated")
        self.assertEqual(context.data_profiling, {"orders": {"row_count": 2}})
        self.assertTrue(context.rule_catalog.warnings)
        self.assertIsNone(context.answerability_constraints)

    def test_cli_outputs_json_and_reports_errors_without_partial_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metadata = Path(directory) / "metadata.json"
            metadata.write_text(json.dumps(_payload()), encoding="utf-8")
            readme = Path(directory) / "README.md"
            readme.write_text(
                "# Shop\nPayment references order ID.\n", encoding="utf-8"
            )
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                code = main(
                    [
                        "--metadata",
                        str(metadata),
                        "--business-id",
                        "biz_1",
                        "--document",
                        str(readme),
                    ]
                )
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["business_id"], "biz_1")
            self.assertEqual(errors.getvalue(), "")
            self.assertNotIn("profile_rows", result["schema_catalog"]["tables"][0])
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                code = main(["--metadata", str(metadata), "--business-id", "biz_wrong"])
            self.assertEqual(code, 1)
            self.assertEqual(output.getvalue(), "")
            self.assertIn("business_id", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
