"""File-based preparation acceptance tests (no competition source mutations)."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import duckdb
from openpyxl import Workbook

from datamate.b0.b01.ingestion import PreparationConfig, PreparationError, prepare_business
from datamate.b0.b01.ingestion.normalization import (
    ColumnParser,
    parse_date,
    parse_number,
    role_for,
)
from datamate.b0.b01.ingestion.readers import CSVReader, XLSXReader
from datamate.b0.b01.metadata_adapter import JSONMetadataProvider

RULES = """## 8. Cách ghi trong file
| Hai dòng của **cùng một đơn** giống nhau ở mọi ô | lỗi xuất file, tính một lần |
| Bảng không ghi theo đơn | mỗi dòng là một lần ghi |
| Ô để trống ở các dòng sau của cùng một nhóm dòng | giống ô đó ở dòng đầu nhóm |
"""


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.business = self.base / "biz_fixture"
        self.business.mkdir()
        self.rulebook = self.base / "rulebook.md"
        self.rulebook.write_text(RULES)
        self.output = self.base / "output"

    def csv(self, name, headers, rows, delimiter=",", encoding="utf-8-sig"):
        path = self.business / name
        with path.open("w", newline="", encoding=encoding) as f:
            writer = csv.writer(f, delimiter=delimiter)
            writer.writerow(headers)
            writer.writerows(rows)
        return path

    def prepare(self, **kw):
        return prepare_business(
            self.business, self.output, rulebook=self.rulebook, **kw
        )

    def context(self, result):
        return json.loads((result.bundle_dir / "business_context.json").read_text())

    def test_csv_bom_delimiter_exact_values_and_small_json(self):
        path = self.csv(
            "sales.csv",
            ["Mã đơn", "Tên hàng", "Số lượng", "Giá bán", "Ngày bán", "Trạng thái"],
            [
                ["0001", "Cà phê", "2", "55.000đ", "1 thg 6 2025", "huỷ"],
                ["0002", "Trà", "3", "25k", "2025-06-02", "trả hàng"],
                ["0003", "Bánh", "1", "1,500.0000", "03/06/2025", "đang giao"],
            ]
            + [
                [f"{n:04}", "Nước", "1", "10", "2028-01-01", "hoàn thành"]
                for n in range(4, 12)
            ],
            delimiter=";",
        )
        before = hashlib.sha256(path.read_bytes()).digest()
        result = self.prepare()
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)
        context = self.context(result)
        self.assertEqual(context["contract_version"], "1.1")
        self.assertEqual(context["normalized_data_handle"]["database"], "data.duckdb")
        table = context["schema_catalog"]["tables"][0]
        self.assertEqual(table["row_count"], 11)
        self.assertNotIn("__dm_row_id", [c["name"] for c in table["columns"]])
        profile = context["data_profiling"][table["name"]]
        self.assertEqual(len(profile["samples"]), 5)
        with duckdb.connect(
            str(result.bundle_dir / "data.duckdb"), read_only=True
        ) as c:
            rows = c.execute(
                f'SELECT ma_don, gia_ban, ngay_ban, trang_thai FROM "{table["name"]}" ORDER BY __dm_row_id'
            ).fetchall()
            self.assertEqual(
                rows[0], ("0001", Decimal("55000.0000"), date(2025, 6, 1), "cancelled")
            )
            self.assertEqual(rows[2][1], Decimal("1500.0000"))
            self.assertEqual(rows[-1][2], date(2028, 1, 1))
            self.assertEqual(sum(row[1] for row in rows), Decimal("81580.0000"))
        metadata = JSONMetadataProvider(
            result.bundle_dir / "foundation_metadata.json"
        ).load(self.business.name)
        self.assertIsNotNone(metadata.normalized_data_handle)
        self.assertTrue(
            any(
                k["status"] == "candidate" and k["columns"] == ["ma_don"]
                for k in context["schema_catalog"]["key_candidates"]
            )
        )

    def test_order_fill_and_dedup_never_events_or_measure_fill(self):
        self.csv(
            "sales.csv",
            ["Mã đơn", "Tên hàng", "Số lượng", "Giá bán", "Khách hàng", "Trạng thái"],
            [
                ["01", "A", "1", "10", "Chị Lan", "huỷ"],
                ["", "B", "", "", "", ""],
                ["01", "A", "1", "10", "Chị Lan", "huỷ"],
                ["02", "A", "1", "10", "", ""],
            ],
        )
        self.csv(
            "events.csv",
            ["Nội dung", "Số tiền"],
            [["Tiền điện", "50000"], ["Tiền điện", "50000"]],
        )
        result = self.prepare()
        context = self.context(result)
        byfamily = context["business_metadata"]["schema_mapping"]
        sale = next(t for t, m in byfamily.items() if m["family"] == "sales")
        event = next(t for t, m in byfamily.items() if m["family"] == "events")
        with duckdb.connect(
            str(result.bundle_dir / "data.duckdb"), read_only=True
        ) as c:
            self.assertEqual(
                c.execute(f'SELECT COUNT(*) FROM "{sale}"').fetchone()[0], 3
            )
            self.assertEqual(
                c.execute(f'SELECT COUNT(*) FROM "{event}"').fetchone()[0], 2
            )
            rows = c.execute(
                f'SELECT ma_don,so_luong,gia_ban,khach_hang,trang_thai FROM "{sale}" ORDER BY __dm_row_id'
            ).fetchall()
            self.assertEqual(rows[1], ("01", None, None, "Chị Lan", "cancelled"))
            self.assertEqual(rows[2][3:], (None, None))
            self.assertEqual(
                c.execute(
                    "SELECT COUNT(*) FROM meta.lineage WHERE deduplicated"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM meta.lineage").fetchone()[0], 6
            )

    def test_parse_errors_null_not_zero_raw_lineage_preserved(self):
        self.csv(
            "sales.csv",
            ["Mã đơn", "Giá bán", "Ngày"],
            [["0001", "???", "not-a-date"], ["0002", "", ""]],
        )
        result = self.prepare()
        table = self.context(result)["schema_catalog"]["tables"][0]["name"]
        with duckdb.connect(
            str(result.bundle_dir / "data.duckdb"), read_only=True
        ) as c:
            self.assertEqual(
                c.execute(f'SELECT gia_ban,ngay FROM "{table}"').fetchall(),
                [(None, None), (None, None)],
            )
            self.assertEqual(
                c.execute(
                    "SELECT COUNT(*) FROM meta.quality_issues WHERE code='parse_failure'"
                ).fetchone()[0],
                2,
            )
            raw = c.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='raw'"
            ).fetchone()[0]
            self.assertEqual(
                c.execute(
                    f'SELECT gia_ban FROM raw."{raw}" ORDER BY __dm_source_row LIMIT 1'
                ).fetchone()[0],
                "???",
            )

    def test_xlsx_months_group_headers_formula_and_other_tables(self):
        wb = Workbook()
        wb.remove(wb.active)
        for title, identifier in [("Thang01_2025", "001"), ("Thang02_2025", "002")]:
            ws = wb.create_sheet(title)
            ws.append(["Đơn", None, "Hàng", None])
            ws.append(["Mã đơn", "Ngày bán", "Tên hàng", "Số lượng", "Giá bán"])
            ws.append([identifier, 45658, "Cà phê", 2, "=2*100"])
            ws.append(["Mã đơn", "Ngày bán", "Tên hàng", "Số lượng", "Giá bán"])
        ws = wb.create_sheet("ChiPhi")
        ws.append(["Ngày", "Nội dung", "Số tiền"])
        ws.append(["1/2/2025", "Điện", 25000])
        wb.save(self.business / "Book.xlsx")
        result = self.prepare()
        context = self.context(result)
        self.assertEqual(len(context["schema_catalog"]["tables"]), 2)
        self.assertEqual(result.quality_summary["issues"]["formula_missing_cache"], 2)
        self.assertEqual(result.quality_summary["source_rows"], 3)
        tables = context["schema_catalog"]["tables"]
        table = next(t for t in tables if t["row_count"] == 2)
        with duckdb.connect(
            str(result.bundle_dir / "data.duckdb"), read_only=True
        ) as c:
            self.assertEqual(
                c.execute(f'SELECT ngay_ban FROM "{table["name"]}" LIMIT 1').fetchone()[
                    0
                ],
                date(2025, 1, 1),
            )

    def test_xlsx_ambiguous_header_requires_override(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Alpha", "Beta"])
        ws.append(["x", "y"])
        path = self.business / "ambiguous.xlsx"
        wb.save(path)
        with self.assertRaisesRegex(ValueError, "ambiguous XLSX header"):
            XLSXReader().discover(path, path.name, {})
        result = self.prepare(
            config=PreparationConfig(source_overrides={path.name: {"header_row": 1}})
        )
        self.assertEqual(result.status, "ready")

    def test_sqlite_readonly_and_composite_fk(self):
        path = self.business / "source.sqlite"
        with sqlite3.connect(path) as c:
            c.executescript(
                'CREATE TABLE parent (id TEXT, seq TEXT, PRIMARY KEY(id,seq)); CREATE TABLE child (id TEXT, seq TEXT, FOREIGN KEY(id,seq) REFERENCES parent(id,seq)); INSERT INTO parent VALUES ("01","1"),("01","2"),("02","1"); INSERT INTO child VALUES ("01","1"),("01","1"),("02","2");'
            )
        before = path.read_bytes()
        result = self.prepare()
        self.assertEqual(path.read_bytes(), before)
        edges = self.context(result)["schema_catalog"]["join_graph"]
        declared = next(e for e in edges if e["additional_key_pairs"])
        self.assertEqual(
            declared["status"], "invalid"
        )  # Individual columns overlap, full tuple does not.

    def test_cache_no_parse_and_document_source_invalidation(self):
        path = self.csv("sales.csv", ["Mã đơn", "Số lượng"], [["01", 1]])
        first = self.prepare()
        with patch.object(
            CSVReader, "rows", side_effect=AssertionError("should not parse cache")
        ):
            second = self.prepare()
        self.assertTrue(second.cache_hit)
        self.assertEqual(first.cache_key, second.cache_key)
        self.rulebook.write_text(RULES + "\nAdditional documented rule\n")
        third = self.prepare()
        self.assertNotEqual(third.cache_key, first.cache_key)
        with path.open("a") as f:
            f.write("02,2\n")
        fourth = self.prepare()
        self.assertNotEqual(fourth.cache_key, third.cache_key)

    def test_fail_closed_all_files_in_manifest(self):
        self.csv("good.csv", ["Mã đơn", "Số lượng"], [["01", 1]])
        (self.business / "bad.xls").write_bytes(b"unknown")
        with self.assertRaises(PreparationError):
            self.prepare()
        failed = list((self.output / self.business.name).glob("failed-*"))
        manifest = json.loads((failed[0] / "source_manifest.json").read_text())
        self.assertEqual(
            {f["path"] for f in manifest["files"]}, {"good.csv", "bad.xls"}
        )
        self.assertEqual(manifest["status"], "failed")
        self.assertFalse(
            any(
                p.name == manifest["cache_key"]
                for p in (self.output / self.business.name).iterdir()
            )
        )

    def test_same_table_multiple_regions(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Mã đơn", "Số lượng"])
        ws.append(["01", 1])
        ws.append([])
        ws.append(["Ngày", "Số tiền"])
        ws.append(["2025-01-01", 100])
        path = self.business / "regions.xlsx"
        wb.save(path)
        sources = XLSXReader().discover(path, path.name, {})
        self.assertEqual(len(sources), 2)
        result = self.prepare()
        self.assertEqual(result.quality_summary["source_rows"], 2)

    def test_cp1258_delimiter_override_and_competition_exclusions(self):
        self.csv(
            "source.csv",
            ["Ma don", "Gia ban"],
            [["0001", "25k"]],
            delimiter="|",
            encoding="cp1258",
        )
        (self.business / "questions.jsonl").write_text('{"id":"q"}')
        result = self.prepare(
            config=PreparationConfig(
                source_overrides={
                    "source.csv": {"encoding": "cp1258", "delimiter": "|"}
                }
            )
        )
        manifest = json.loads((result.bundle_dir / "source_manifest.json").read_text())
        self.assertEqual(
            next(f for f in manifest["files"] if f["path"] == "questions.jsonl")[
                "status"
            ],
            "excluded",
        )
        self.assertEqual(result.quality_summary["source_rows"], 1)

    def test_money_expiry_and_formula_are_not_forward_filled(self):
        wb = Workbook()
        ws = wb.active
        ws.append(
            ["Mã đơn", "Tên hàng", "Số lượng", "Khách trả", "Hạn sử dụng", "Giá bán"]
        )
        ws.append(["01", "A", 1, 100, "2025-01-01", "=1+1"])
        ws.append(["01", "A", 1, None, None, "=2+2"])
        wb.save(self.business / "sales.xlsx")
        result = self.prepare()
        table = self.context(result)["schema_catalog"]["tables"][0]["name"]
        with duckdb.connect(
            str(result.bundle_dir / "data.duckdb"), read_only=True
        ) as c:
            self.assertEqual(
                c.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0], 2
            )
            rows = c.execute(
                f'SELECT khach_tra, han_su_dung FROM "{table}" ORDER BY __dm_row_id'
            ).fetchall()
            self.assertEqual(rows[1], (None, None))

    def test_corrupted_cache_rebuilds_instead_of_reusing(self):
        self.csv("sales.csv", ["Mã đơn", "Số lượng"], [["01", 1]])
        first = self.prepare()
        (first.bundle_dir / "business_context.json").write_text("{}")
        second = self.prepare()
        self.assertFalse(second.cache_hit)
        self.assertEqual(self.context(second)["business_id"], self.business.name)
        self.assertTrue(self.prepare().cache_hit)

    def test_formula_cached_number_is_typed_and_raw_formula_retained(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Mã đơn", "Giá bán"])
        ws.append(["01", "=2*100"])
        path = self.business / "cached.xlsx"
        wb.save(path)
        with zipfile.ZipFile(path) as archive:
            members = {n: archive.read(n) for n in archive.namelist()}
        xml = ET.fromstring(members["xl/worksheets/sheet1.xml"])
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        xml.find(".//s:c[@r='B2']/s:v", ns).text = "200"
        members["xl/worksheets/sheet1.xml"] = ET.tostring(xml)
        with zipfile.ZipFile(path, "w") as archive:
            for name, value in members.items():
                archive.writestr(name, value)
        result = self.prepare()
        table = self.context(result)["schema_catalog"]["tables"][0]["name"]
        with duckdb.connect(
            str(result.bundle_dir / "data.duckdb"), read_only=True
        ) as c:
            self.assertEqual(
                c.execute(f'SELECT gia_ban FROM "{table}"').fetchone()[0], Decimal(200)
            )
            raw = c.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='raw'"
            ).fetchone()[0]
            self.assertEqual(
                c.execute(f'SELECT gia_ban FROM raw."{raw}"').fetchone()[0], "=2*100"
            )
        self.assertNotIn("formula_missing_cache", result.quality_summary["issues"])

    def test_group_order_date_is_filled_but_not_expiry(self):
        self.csv(
            "sales.csv",
            ["Mã đơn", "Tên hàng", "Số lượng", "Ngày đặt hàng", "Hạn sử dụng"],
            [["01", "A", 1, "2025-01-01", "2026-01-01"], ["", "B", 2, "", ""]],
        )
        result = self.prepare()
        table = self.context(result)["schema_catalog"]["tables"][0]["name"]
        with duckdb.connect(
            str(result.bundle_dir / "data.duckdb"), read_only=True
        ) as c:
            row = c.execute(
                f'SELECT ngay_dat_hang,han_su_dung FROM "{table}" ORDER BY __dm_row_id DESC LIMIT 1'
            ).fetchone()
            self.assertEqual(row, (date(2025, 1, 1), None))

    def test_bad_xlsx_records_every_file_and_never_publishes_ready(self):
        (self.business / "a_broken.xlsx").write_bytes(b"broken zip")
        self.csv("z_valid.csv", ["Mã đơn", "Số lượng"], [["01", 1]])
        with self.assertRaises(PreparationError):
            self.prepare()
        failed = next((self.output / self.business.name).glob("failed-*"))
        manifest = json.loads((failed / "source_manifest.json").read_text())
        self.assertEqual(
            {f["path"] for f in manifest["files"]}, {"a_broken.xlsx", "z_valid.csv"}
        )
        self.assertEqual(
            next(f for f in manifest["files"] if f["path"] == "a_broken.xlsx")[
                "status"
            ],
            "error",
        )

    def test_late_header_is_never_silently_discarded(self):
        wb = Workbook()
        ws = wb.active
        ws.cell(41, 1, "Mã đơn")
        ws.cell(41, 2, "Số lượng")
        ws.cell(42, 1, "01")
        ws.cell(42, 2, 2)
        wb.save(self.business / "late.xlsx")
        with self.assertRaises(PreparationError):
            self.prepare()
        result = self.prepare(
            config=PreparationConfig(source_overrides={"late.xlsx": {"header_row": 41}})
        )
        self.assertEqual(result.quality_summary["source_rows"], 1)

    def test_row_read_failure_retains_failed_bundle_and_closes_spools(self):
        path = self.csv("wide.csv", ["Mã đơn", "Số lượng"], [["01", 1]])
        with path.open("a") as stream:
            stream.write("02,2,extra\n")
        with self.assertRaises(PreparationError):
            self.prepare(
                config=PreparationConfig(
                    source_overrides={"wide.csv": {"delimiter": ","}}
                )
            )
        failed = next((self.output / self.business.name).glob("failed-*"))
        manifest = json.loads((failed / "source_manifest.json").read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertIn("wider than header", manifest["error"])
        self.assertFalse(
            (self.output / self.business.name / manifest["cache_key"]).exists()
        )

    def test_external_source_change_during_build_is_rejected(self):
        self.csv("sales.csv", ["Mã đơn", "Số lượng"], [["01", 1]])
        original = CSVReader.rows

        def changed(reader, source):
            yield from original(reader, source)
            with source.path.open("a") as stream:
                stream.write("02,2\n")

        with (
            patch.object(CSVReader, "rows", changed),
            self.assertRaisesRegex(PreparationError, "source changed"),
        ):
            self.prepare()
        self.assertTrue(list((self.output / self.business.name).glob("failed-*")))

    def test_explicit_footer_kept_in_raw_and_never_added_to_sales(self):
        self.csv(
            "sales.csv",
            ["Ngày", "Mã đơn", "Tên hàng", "Số lượng", "Thành tiền"],
            [
                ["2025-01-01", "01", "A", 1, 100],
                ["Tổng tháng", "", "", "", 100],
                ["Ghi chú: số liệu ghi tay", "", "", "", ""],
            ],
        )
        result = self.prepare()
        table = self.context(result)["schema_catalog"]["tables"][0]["name"]
        with duckdb.connect(
            str(result.bundle_dir / "data.duckdb"), read_only=True
        ) as c:
            self.assertEqual(
                c.execute(f'SELECT COUNT(*),SUM(thanh_tien) FROM "{table}"').fetchone(),
                (1, Decimal(100)),
            )
            raw = c.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='raw'"
            ).fetchone()[0]
            self.assertEqual(
                c.execute(f'SELECT COUNT(*) FROM raw."{raw}"').fetchone()[0], 3
            )
        self.assertEqual(result.quality_summary["excluded_non_data_rows"], 2)
        self.assertEqual(result.quality_summary["raw_rows"], 3)

    def test_output_parent_or_symlink_cannot_write_into_source(self):
        self.csv("sales.csv", ["Mã đơn", "Số lượng"], [["01", 1]])
        before = sorted(p.relative_to(self.business) for p in self.business.rglob("*"))
        with self.assertRaisesRegex(ValueError, "outside"):
            prepare_business(self.business, self.business.parent)
        self.output.mkdir()
        (self.output / self.business.name).symlink_to(
            self.business, target_is_directory=True
        )
        with self.assertRaisesRegex(ValueError, "outside"):
            self.prepare()
        self.assertEqual(
            sorted(p.relative_to(self.business) for p in self.business.rglob("*")),
            before,
        )


class ParsingTests(unittest.TestCase):
    def test_money_exact_precision_no_float_round(self):
        self.assertEqual(parse_number("55.000đ", "money"), Decimal(55000))
        self.assertEqual(parse_number("25k", "money"), Decimal(25000))
        self.assertEqual(parse_number("2tr760", "money"), Decimal(2760000))
        self.assertEqual(parse_number("398,8604tr", "money"), Decimal(398860400))
        self.assertEqual(parse_number("1,500.0000", "money").as_tuple().exponent, -4)
        self.assertEqual(
            parse_number("123456789012345678901234567890.12", "money"),
            Decimal("123456789012345678901234567890.12"),
        )
        self.assertEqual(parse_number("1 kg", "quantity"), Decimal(1))
        self.assertEqual(parse_number("2 xe 4m3", "quantity"), Decimal(2))
        with self.assertRaises(ValueError):
            parse_number("1,23,456", "money")

    def test_date_epoch_and_sheet_year(self):
        self.assertEqual(parse_date("1 thg 6 2025", "1900", None), date(2025, 6, 1))
        self.assertEqual(parse_date("1/6", "1900", 2025), date(2025, 6, 1))
        self.assertEqual(parse_date("45000", "1904", None), date(2027, 3, 16))
        with self.assertRaises(ValueError):
            parse_date("1/6", "1900", None)

    def test_identifier_leading_zeros_and_unknown_text(self):
        self.assertEqual(role_for("Người giao hàng"), "text")
        self.assertEqual(role_for("CachHoanTien"), "text")
        self.assertEqual(role_for("Giá bán theo đơn vị quy đổi"), "money")
        self.assertEqual(role_for("Kê đơn"), "boolean")
        self.assertEqual(role_for("Hạn thanh toán"), "date")
        self.assertEqual(
            ColumnParser("identifier").parse("000123", epoch="1900", year=None),
            ("000123", None),
        )
        parser = ColumnParser("unknown")
        parser.parse("000123", epoch="1900", year=None)
        self.assertEqual(parser.sql_type(), "VARCHAR")


if __name__ == "__main__":
    unittest.main()
