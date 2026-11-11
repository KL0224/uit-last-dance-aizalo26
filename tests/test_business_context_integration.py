"""Prepared files -> persisted B01/B02 -> reviewed formula -> read-only SQL."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import duckdb

from datamate.ingestion.ingestion import prepare_business
from datamate.ingestion.join_graph import JoinGraphNavigator, JoinPredicateCompiler
from datamate.ingestion.metadata_adapter import BusinessContextSchemaReader
from datamate.context.rule_compiler import BusinessRuleCompiler
from datamate.context.rule_resolver import RuleResolver
from datamate.context.rule_templates import RuleTemplateBinder
from scripts.audit_prepared_bundles import audit
from scripts.demo_join_graph import read_rule_catalog, run_demo

REVENUE_CLAUSE = "Doanh thu một đơn | tổng **thành tiền các dòng hàng** (đã trừ giảm giá trên từng dòng). **Không** trừ giảm giá trên cả đơn (khuyến mãi theo tổng tiền đơn, voucher shop), **không** cộng thuế VAT, **không** gồm phí giao hàng. **Tiền hàng**, **tiền bán** của đơn bán cùng nghĩa với doanh thu"


class PreparedBusinessIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        business = cls.root / "fixture_business"
        business.mkdir()
        cls.source = business / "sales.sqlite"
        with sqlite3.connect(cls.source) as connection:
            connection.executescript("""
                CREATE TABLE customers(MaKhachHang TEXT PRIMARY KEY);
                CREATE TABLE products(MaHangHoa TEXT PRIMARY KEY);
                CREATE TABLE orders(MaHoaDon TEXT PRIMARY KEY, MaKhachHang TEXT REFERENCES customers(MaKhachHang), TinhTrang TEXT, NgayLap TEXT);
                CREATE TABLE lines(MaHoaDon TEXT REFERENCES orders(MaHoaDon), SoThuTu INTEGER, MaHangHoa TEXT REFERENCES products(MaHangHoa), TriGia DECIMAL(18,2), PRIMARY KEY(MaHoaDon,SoThuTu));
                CREATE TABLE returns(MaHoaDon TEXT REFERENCES orders(MaHoaDon), NgayTra TEXT);
                INSERT INTO customers VALUES ('c1'),('c2');
                INSERT INTO products VALUES ('p1'),('p2');
                INSERT INTO orders VALUES ('o1','c1','completed','2026-06-01'),('o2','c1','cancelled','2026-06-02'),('o3','c2','returned','2026-06-03'),('o4',NULL,'completed','2026-07-01'),('o5','c2','delivering','2026-06-30'),('o6','c1','completed','2026-06-05');
                INSERT INTO lines VALUES ('o1',1,'p1',100),('o1',2,'p2',180),('o2',1,'p1',999),('o3',1,'p1',999),('o4',1,'p1',999),('o5',1,'p2',50),('o6',1,'p1',999);
                INSERT INTO returns VALUES ('o6','2026-07-10');
            """)
        cls.source_hash = hashlib.sha256(cls.source.read_bytes()).hexdigest()
        rulebook = cls.root / "rulebook.md"
        rulebook.write_text(
            "# Rules\n| Luật | Mặc định |\n|---|---|\n| " + REVENUE_CLAUSE + " |\n",
            encoding="utf-8",
        )
        result = prepare_business(business, cls.root / "output", rulebook=rulebook)
        cls.prepared = result
        cls.bundle = result.bundle_dir
        cls.payload = json.loads((cls.bundle / "business_context.json").read_text())

    def test_consumer_reads_persisted_rules_without_promoting_them(self) -> None:
        before = (self.bundle / "business_context.json").read_bytes()
        result = run_demo(
            self.bundle,
            "customers",
            "products",
            count_rows=True,
            rule_topic="Doanh thu một đơn",
        )
        self.assertEqual(result["status"], "validated_path")
        self.assertEqual(result["joined_row_count"], 6)
        self.assertEqual(
            result["business_rule"]["status"], "missing_binding_or_evidence"
        )
        self.assertIsNone(result["business_rule"]["sql_fragment"])
        self.assertEqual((self.bundle / "business_context.json").read_bytes(), before)
        self.assertEqual(
            hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash
        )

    def test_selected_formula_and_validated_join_match_independent_reference(
        self,
    ) -> None:
        schema = BusinessContextSchemaReader().read(self.payload)
        catalog = read_rule_catalog(self.payload, schema)
        selected = RuleResolver().resolve(catalog, "fixture_business")
        source_rule = next(r for r in selected.rules if r.topic == "Doanh thu một đơn")
        compiler, binder = BusinessRuleCompiler(), RuleTemplateBinder()
        with duckdb.connect(
            str(self.bundle / "data.duckdb"), read_only=True
        ) as connection:
            names = dict(
                connection.execute(
                    "SELECT sheet,normalized_table FROM meta.source_mapping"
                ).fetchall()
            )
            lines, orders, returns = names["lines"], names["orders"], names["returns"]
            mapping = self.payload["business_metadata"]["schema_mapping"][lines][
                "columns"
            ]
            amount = next(
                c for c, info in mapping.items() if info["original_name"] == "TriGia"
            )
            path = JoinGraphNavigator().find_path(schema, lines, orders)
            self.assertEqual(len(path), 1)
            predicate = JoinPredicateCompiler().compile(path[0], schema)
            bindings = {"line_amount": lines + "." + amount}
            evidence = {
                "valid_revenue_orders": "fixture SQL excludes cancelled/returned and any return event, even after cutoff",
                "order_date_scope": "fixture SQL: NgayLap >= 2026-06-01 and < 2026-07-01",
                "sales_line_grain": "source PRIMARY KEY(MaHoaDon,SoThuTu); validated N:1 JOIN to orders",
                "line_amount_after_line_discount": "fixture TriGia is explicitly defined as line net amount",
                "line_amount_excludes_order_discount_vat_shipping": "fixture definition; no header discount/VAT/shipping added",
            }
            bound = binder.bind(source_rule, "revenue", bindings, schema, evidence)
            self.assertEqual(bound.status, "validated")
            fragment, parameters = compiler.compile_rule(bound, schema)
            sql = f'''SELECT {fragment} FROM "{lines}" JOIN "{orders}" ON {predicate}
                WHERE "{orders}".tinh_trang NOT IN ('cancelled','returned')
                AND "{orders}".ngay_lap >= ? AND "{orders}".ngay_lap < ?
                AND NOT EXISTS(SELECT 1 FROM "{returns}" r WHERE r.ma_hoa_don="{orders}".ma_hoa_don)'''
            actual = connection.execute(
                sql, [*parameters, "2026-06-01", "2026-07-01"]
            ).fetchone()[0]
            reference = connection.execute(
                f'''SELECT SUM(tri_gia) FROM "{lines}" WHERE ma_hoa_don IN ('o1','o5')'''
            ).fetchone()[0]
            self.assertEqual(actual, reference)
            self.assertEqual(actual, Decimal(330))
            missing = binder.bind(source_rule, "revenue", bindings, schema, {})
            self.assertEqual(missing.status, "invalid")
            for rule in (source_rule, missing):
                with self.assertRaises(ValueError):
                    compiler.compile_rule(rule, schema)
            unsafe = replace(
                schema,
                join_graph=tuple(
                    replace(e, status="uncertain") for e in schema.join_graph
                ),
            )
            self.assertIsNone(JoinGraphNavigator().find_path(unsafe, lines, orders))
            with self.assertRaises(ValueError):
                JoinPredicateCompiler().compile(unsafe.join_graph[0], unsafe)

    def test_reader_rejects_rules_from_another_business(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["rule_catalog"]["business_id"] = "other_business"
        with self.assertRaises(ValueError):
            read_rule_catalog(payload, BusinessContextSchemaReader().read(payload))

    def test_missing_rule_is_reported_without_inventing_sql(self) -> None:
        result = run_demo(
            self.bundle, "customers", "products", rule_topic="unknown topic"
        )
        self.assertEqual(result["business_rule"]["status"], "no_selected_rule")
        self.assertIsNone(result["business_rule"]["sql_fragment"])

    def test_regression_auditor_checks_sql_join_statistics_and_baseline_counts(
        self,
    ) -> None:
        cold = self.prepared.to_dict() | {"wall_seconds": 0.0, "peak_rss_mib": 0.0}
        warm = cold | {"cache_hit": True}
        benchmark = {
            "source_unchanged": True,
            "results": [
                {
                    "business_id": "fixture_business",
                    "cold": cold,
                    "warm": warm,
                }
            ],
        }
        report = self.root / "audit-input.json"
        report.write_text(json.dumps(benchmark))
        with redirect_stdout(io.StringIO()):
            verified = audit(report, report)
        self.assertEqual(verified["business_count"], 1)
        self.assertTrue(verified["results"][0]["baseline_counts_match"])
        context_path = self.bundle / "business_context.json"
        original = context_path.read_bytes()
        corrupted = json.loads(original)
        corrupted["schema_catalog"]["join_graph"][0]["statistics"][
            "matched_distinct"
        ] += 1
        try:
            context_path.write_text(json.dumps(corrupted))
            with redirect_stdout(io.StringIO()), self.assertRaises(AssertionError):
                audit(report)
        finally:
            context_path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
