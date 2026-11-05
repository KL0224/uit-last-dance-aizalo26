"""Opt-in integration checks with read-only CSV/SQLite metadata fixtures.

Run with DATAMATE_TRAIN_DIR=data/train PYTHONPATH=src python3 -m unittest
discover -s tests -p test_train_smoke.py -v. The fixture readers are test-only;
production ingestion belongs to the team's Data Foundation.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path

from datamate.b0.b02.contracts import ColumnMetadata, ContractBuilder, TableMetadata
from datamate.b0.b02.rule_compiler import BusinessRuleCompiler
from datamate.b0.b02.rule_resolver import RuleResolver
from datamate.b0.b02.rule_templates import RuleTemplateBinder
from datamate.b0.b01.schema_catalog import SchemaCatalogBuilder


def _csv_metadata(path: Path) -> TableMetadata:
    """Build bounded fixture metadata without changing competition files."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = tuple(ColumnMetadata(name) for name in reader.fieldnames or ())
        sample: list[dict[str, str | None]] = []
        row_count = 0
        for row in reader:
            row_count += 1
            if len(sample) < 32:
                sample.append(
                    {key: value if value else None for key, value in row.items()}
                )
    return TableMetadata(
        path.stem,
        columns,
        row_count=row_count,
        provenance=str(path),
        profile_rows=tuple(sample),
        profile_is_complete=row_count == len(sample),
    )


def _sqlite_metadata(path: Path) -> list[TableMetadata]:
    """Inspect SQLite with an explicit read-only connection."""
    tables: list[TableMetadata] = []
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        names = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for (name,) in names:
            quoted = '"' + name.replace('"', '""') + '"'
            info = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
            columns = tuple(
                ColumnMetadata(item[1], item[2] or "unknown") for item in info
            )
            row_count = connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[
                0
            ]
            rows = connection.execute(f"SELECT * FROM {quoted} LIMIT 32").fetchall()
            sample = tuple(
                dict(zip((column.name for column in columns), row)) for row in rows
            )
            tables.append(
                TableMetadata(
                    name,
                    columns,
                    row_count=row_count,
                    provenance=f"{path}#{name}",
                    profile_rows=sample,
                    profile_is_complete=row_count == len(sample),
                )
            )
    finally:
        connection.close()
    return tables


@unittest.skipUnless(
    os.environ.get("DATAMATE_TRAIN_DIR"),
    "set DATAMATE_TRAIN_DIR for real-data smoke tests",
)
class TrainSmokeTests(unittest.TestCase):
    def test_reviewed_rulebook_formulas_execute_with_explicit_field_bindings(
        self,
    ) -> None:
        root = Path(os.environ["DATAMATE_TRAIN_DIR"])
        compiler = BusinessRuleCompiler()
        source_rules = compiler.ingest_documents([root / "rulebook.md"], "fixture")
        selected = RuleResolver().resolve(source_rules, "fixture")
        schema = SchemaCatalogBuilder().build(
            [
                TableMetadata(
                    "sales",
                    tuple(
                        ColumnMetadata(name, "INTEGER")
                        for name in ("amount", "qty", "cost", "qty_base")
                    ),
                )
            ]
        )
        binder = RuleTemplateBinder()
        cases = (
            ("revenue", "Doanh thu một đơn", {"line_amount": "amount"}, 280),
            (
                "gross_profit",
                "Lãi gộp",
                {"line_amount": "amount", "quantity": "qty", "unit_cost": "cost"},
                100,
            ),
            ("sold_qty_base", "Bán chạy", {"base_quantity": "qty_base"}, 5),
        )
        for template, topic, fields, expected in cases:
            with self.subTest(template=template):
                source = next(rule for rule in selected.rules if rule.topic == topic)
                missing = binder.bind(source, template, fields, schema, {})
                self.assertEqual(missing.status, "invalid")
                with self.assertRaises(ValueError):
                    compiler.compile_rule(missing, schema)
                evidence = {
                    key: "normalized fixture: valid filtered sales lines"
                    for key in binder.requirements(template)
                }
                bound = binder.bind(source, template, fields, schema, evidence)
                self.assertEqual(bound.source, source.source)
                sql, params = compiler.compile_rule(bound, schema)
                with sqlite3.connect(":memory:") as connection:
                    connection.execute(
                        "CREATE TABLE sales(amount, qty, cost, qty_base)"
                    )
                    connection.executemany(
                        "INSERT INTO sales VALUES (?,?,?,?)",
                        [(100, 2, 30, 2), (180, 3, 40, 3)],
                    )
                    self.assertEqual(
                        connection.execute(
                            f"SELECT {sql} FROM sales", params
                        ).fetchone()[0],
                        expected,
                    )
                changed = replace(
                    source, text=source.text + " Thay đổi công thức theo câu hỏi."
                )
                with self.assertRaises(ValueError):
                    binder.bind(changed, template, fields, schema, evidence)

    def test_three_businesses_produce_scoped_json_contracts(self) -> None:
        root = Path(os.environ["DATAMATE_TRAIN_DIR"])
        compiler = BusinessRuleCompiler()
        for business_id in ("biz_111", "biz_127", "biz_123"):
            with self.subTest(business=business_id):
                folder = root / "data" / business_id
                if business_id == "biz_123":
                    tables = _sqlite_metadata(folder / "pos.sqlite")
                else:
                    tables = [
                        _csv_metadata(path) for path in sorted(folder.glob("*.csv"))
                    ]
                self.assertTrue(tables)
                schema = SchemaCatalogBuilder().build(tables)
                rules = compiler.ingest_documents(
                    [root / "rulebook.md", folder / "README.md"], business_id, schema
                )
                self.assertFalse(rules.warnings)
                context = ContractBuilder().build(business_id, schema, rules)
                payload = json.loads(json.dumps(context.to_dict(), ensure_ascii=False))
                self.assertEqual(payload["business_id"], business_id)
                self.assertTrue(payload["schema_catalog"]["tables"])
                self.assertTrue(payload["rule_catalog"]["rules"])
                self.assertTrue(
                    all(edge.status != "confirmed" for edge in schema.join_graph)
                )
                resolved = RuleResolver().resolve(rules, business_id)
                self.assertFalse(
                    any(rule.scope == "industry" for rule in resolved.rules)
                )
                pharmacy = RuleResolver().resolve(
                    rules, business_id, industry="Nhà thuốc"
                )
                selected_industry = [
                    rule for rule in pharmacy.rules if rule.scope == "industry"
                ]
                self.assertEqual(len(selected_industry), 4)
                self.assertTrue(
                    all(rule.industry == "Nhà thuốc" for rule in selected_industry)
                )
                for table in payload["schema_catalog"]["tables"]:
                    self.assertNotIn("profile_rows", table)


if __name__ == "__main__":
    unittest.main()
