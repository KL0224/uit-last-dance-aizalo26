"""Regression coverage for full-table discovery and reviewed JOIN preparation."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import duckdb
from relationship_fixtures import reviewed_edge

from datamate.b0.b01.contracts import (
    ColumnMetadata,
    JoinEdge,
    JoinStatistics,
    KeyCandidate,
    TableMetadata,
)
from datamate.b0.b01.ingestion import prepare_business
from datamate.b0.b01.ingestion.profiling import DuckDBProfileProvider
from datamate.b0.b01.schema_catalog import SchemaCatalogBuilder


class FullTableDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = duckdb.connect(":memory:")
        self.addCleanup(self.connection.close)

    def table(
        self, name: str, rows: list[tuple], names: tuple[str, ...]
    ) -> TableMetadata:
        definition = ", ".join(f'"{column}" VARCHAR' for column in names)
        self.connection.execute(f'CREATE TABLE "{name}" ({definition})')
        self.connection.executemany(
            f'INSERT INTO "{name}" VALUES ({", ".join("?" for _ in names)})', rows
        )
        columns = tuple(
            ColumnMetadata(
                column,
                "VARCHAR",
                null_ratio=sum(r[i] is None for r in rows) / len(rows),
                cardinality=len({r[i] for r in rows if r[i] is not None}),
            )
            for i, column in enumerate(names)
        )
        return TableMetadata(
            name,
            columns,
            row_count=len(rows),
            profile_rows=tuple(dict(zip(names, row)) for row in rows[:5]),
        )

    def test_disjoint_samples_do_not_hide_full_table_reference(self) -> None:
        parent = self.table(
            "customers", [(str(i),) for i in range(20)], ("ma_khach_hang",)
        )
        child = self.table(
            "orders",
            [(None,)] + [(str(i),) for i in range(10, 20)] * 2,
            ("ma_khach_hang",),
        )
        catalog = SchemaCatalogBuilder(DuckDBProfileProvider(self.connection)).build(
            [parent, child]
        )
        self.assertEqual(len(catalog.join_graph), 1)
        edge = catalog.join_graph[0]
        self.assertEqual(edge.status, "uncertain")
        self.assertEqual(edge.cardinality, "one_to_many")
        self.assertIn("right=10/10", " ".join(edge.evidence))

    def test_composite_discovery_uses_full_tuples_without_sample_overlap(self) -> None:
        names = ("ma_hoa_don", "so_thu_tu")
        parent = self.table(
            "lines", [(str(i), str(j)) for i in range(10) for j in range(2)], names
        )
        child = self.table(
            "allocations",
            [(str(i), str(j)) for i in range(5, 10) for j in range(2)] * 2,
            names,
        )
        catalog = SchemaCatalogBuilder(DuckDBProfileProvider(self.connection)).build(
            [parent, child]
        )
        composite = [edge for edge in catalog.join_graph if len(edge.key_pairs) == 2]
        self.assertEqual(len(composite), 1)
        self.assertEqual(composite[0].status, "uncertain")
        self.assertEqual(composite[0].cardinality, "one_to_many")

    def test_unrelated_names_low_coverage_and_accidental_unique_values(self) -> None:
        a = self.table(
            "a", [(str(i), str(i)) for i in range(20)], ("ma_hang", "amount")
        )
        b = self.table(
            "b", [(str(i), str(i)) for i in range(19, 39)], ("ma_hang", "amount")
        )
        c = self.table(
            "c", [(str(i), str(i)) for i in range(20)], ("ma_khach", "amount")
        )
        catalog = SchemaCatalogBuilder(DuckDBProfileProvider(self.connection)).build(
            [a, b, c]
        )
        self.assertEqual(catalog.join_graph, ())

    def test_source_column_mapping_is_used_without_unique_implying_semantics(
        self,
    ) -> None:
        a = self.table("a", [(str(i),) for i in range(10)], ("ma_khach",))
        b = self.table("b", [(str(i),) for i in range(10)], ("customer_reference",))
        b = replace(b, columns=(replace(b.columns[0], provenance="Mã khách"),))
        catalog = SchemaCatalogBuilder(DuckDBProfileProvider(self.connection)).build(
            [a, b]
        )
        self.assertEqual(len(catalog.join_graph), 1)
        self.assertEqual(catalog.join_graph[0].status, "uncertain")

    def test_same_name_high_coverage_still_does_not_prove_semantics(self) -> None:
        a = self.table("a", [(str(i),) for i in range(10)], ("id",))
        b = self.table("unrelated", [(str(i),) for i in range(10)], ("id",))
        catalog = SchemaCatalogBuilder(DuckDBProfileProvider(self.connection)).build(
            [a, b]
        )
        self.assertEqual(catalog.join_graph[0].status, "uncertain")

    def test_free_text_tampered_mapping_and_wrong_scope_cannot_validate(self) -> None:
        parent = self.table("parent", [("a",), ("b",)], ("id",))
        child = self.table("child", [("a",), ("a",), ("b",)], ("parent_id",))
        edge = JoinEdge(
            "child",
            "parent_id",
            "parent",
            "id",
            "many_to_one",
            "candidate",
            1.0,
            ("I promise this is valid",),
        )
        provider = DuckDBProfileProvider(self.connection, "fixture")
        self.assertEqual(provider.check_join(edge).status, "uncertain")
        trusted = reviewed_edge(edge)
        self.assertEqual(provider.check_join(trusted).status, "validated")
        self.assertNotEqual(
            provider.check_join(replace(trusted, cardinality="one_to_many")).status,
            "validated",
        )
        self.assertNotEqual(
            DuckDBProfileProvider(self.connection, "other").check_join(trusted).status,
            "validated",
        )
        cat = SchemaCatalogBuilder(provider).build(
            [parent, child], [trusted], business_id="other"
        )
        self.assertNotEqual(cat.join_graph[0].status, "validated")

    def test_conflicting_declarations_are_blocked(self) -> None:
        parent = self.table("parent", [("a",), ("b",)], ("id",))
        child = self.table("child", [("a",), ("a",), ("b",)], ("parent_id",))
        edge = reviewed_edge(
            JoinEdge(
                "child",
                "parent_id",
                "parent",
                "id",
                "many_to_one",
                "candidate",
                1.0,
                (),
            )
        )
        conflicting = reviewed_edge(replace(edge, cardinality="one_to_one"))
        catalog = SchemaCatalogBuilder(DuckDBProfileProvider(self.connection)).build(
            [parent, child], [edge, conflicting]
        )
        self.assertEqual([e.status for e in catalog.join_graph], ["invalid", "invalid"])

    def test_explicit_identifier_roles_allow_neutral_names_but_amount_roles_do_not(
        self,
    ) -> None:
        left = self.table(
            "left_table",
            [(str(i), str(i)) for i in range(10)],
            ("reference", "ma_amount"),
        )
        right = self.table(
            "right_table",
            [(str(i), str(i)) for i in range(10)],
            ("reference", "ma_amount"),
        )
        roles = {
            (table.name, name): role
            for table in (left, right)
            for name, role in (("reference", "identifier"), ("ma_amount", "money"))
        }
        provider = DuckDBProfileProvider(self.connection, column_roles=roles)
        catalog = SchemaCatalogBuilder(provider).build([left, right])
        self.assertEqual(len(catalog.join_graph), 1)
        self.assertEqual(catalog.join_graph[0].left_column, "reference")
        self.assertEqual(catalog.join_graph[0].status, "uncertain")

    def test_search_budget_is_explicit_and_deterministic(self) -> None:
        class CountingProfile(DuckDBProfileProvider):
            checks = 0

            def check_key(
                self, table: TableMetadata, columns: tuple[str, ...]
            ) -> KeyCandidate:
                return KeyCandidate(
                    table.name, columns, "primary", "candidate", 1.0, ("fixture",)
                )

            def check_join(self, edge: JoinEdge) -> JoinEdge:
                self.checks += 1
                return replace(
                    edge,
                    status="uncertain",
                    cardinality="one_to_one",
                    statistics=JoinStatistics(
                        2, 2, 0, 0, 2, 2, 2, 1.0, 1.0, "one_to_one"
                    ),
                )

        tables = [
            TableMetadata(
                f"t{i}",
                (ColumnMetadata("id", "VARCHAR", null_ratio=0, cardinality=2),),
                row_count=2,
            )
            for i in range(48)
        ]
        provider = CountingProfile(self.connection)
        catalog = SchemaCatalogBuilder(provider).build(tables)
        self.assertEqual(provider.checks, 1024)
        self.assertEqual(len(catalog.join_graph), 1024)
        self.assertIn("1024", " ".join(catalog.warnings))

    def test_business_scope_constants_do_not_create_all_to_all_join_candidates(
        self,
    ) -> None:
        left = self.table("orders", [("biz",), ("biz",)], ("shop_reference",))
        right = self.table("products", [("biz",), ("biz",)], ("shop_reference",))
        roles = {
            (table.name, "shop_reference"): "identifier" for table in (left, right)
        }
        catalog = SchemaCatalogBuilder(
            DuckDBProfileProvider(self.connection, column_roles=roles)
        ).build([left, right])
        self.assertEqual(catalog.join_graph, ())
        self.assertIn("constant", " ".join(catalog.warnings))


class ReviewedPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.business = self.base / "biz_fixture"
        self.business.mkdir()
        for file, rows in {
            "customers.csv": [["Mã khách"], ["001"], ["002"]],
            "orders.csv": [["Mã khách"], ["001"], ["001"], ["002"], [None]],
        }.items():
            with (self.business / file).open(
                "w", newline="", encoding="utf-8"
            ) as stream:
                csv.writer(stream).writerows(
                    [rows[0] + ["Ghi chú"]] + [row + ["fixture"] for row in rows[1:]]
                )
        self.quote = (
            "orders.Mã khách references customers.Mã khách; blank customer is optional."
        )
        self.document = self.base / "review.md"
        self.document.write_text(self.quote, encoding="utf-8")
        self.manifest = self.base / "relationships.json"
        self.payload = {
            "version": "1.0",
            "business_id": "biz_fixture",
            "relationships": [
                {
                    "id": "order_customer",
                    "left": {
                        "file": "orders.csv",
                        "table": None,
                        "columns": ["Mã khách"],
                    },
                    "right": {
                        "file": "customers.csv",
                        "table": None,
                        "columns": ["Mã khách"],
                    },
                    "cardinality": "many_to_one",
                    "review": {
                        "status": "approved",
                        "reviewed_by": "fixture schema reviewer",
                        "evidence": {
                            "path": "review.md",
                            "sha256": self.digest(),
                            "quote": self.quote,
                        },
                    },
                }
            ],
        }
        self.save()

    def digest(self) -> str:
        return hashlib.sha256(self.document.read_bytes()).hexdigest()

    def save(self) -> None:
        self.manifest.write_text(
            json.dumps(self.payload, ensure_ascii=False), encoding="utf-8"
        )

    def prepare(self):
        return prepare_business(
            self.business, self.base / "output", relationships=self.manifest
        )

    def edge(self, result):
        context = json.loads((result.bundle_dir / "business_context.json").read_text())
        return context["schema_catalog"]["join_graph"][0]

    def test_reviewed_source_mapping_cache_and_source_integrity(self) -> None:
        before = {p.name: p.read_bytes() for p in self.business.iterdir()}
        result = self.prepare()
        edge = self.edge(result)
        self.assertEqual(edge["status"], "validated")
        self.assertEqual(edge["statistics"]["left_null_rows"], 1)
        self.assertEqual(edge["relationship_evidence"]["source_sha256"], self.digest())
        self.assertEqual(edge["relationship_evidence"]["business_id"], "biz_fixture")
        self.assertTrue(self.prepare().cache_hit)
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.business.iterdir()}
        )
        review = self.payload["relationships"][0]["review"]
        review["status"] = "pending"
        self.save()
        pending = self.prepare()
        self.assertNotEqual(pending.cache_key, result.cache_key)
        self.assertEqual(self.edge(pending)["status"], "uncertain")
        self.assertEqual(
            self.edge(pending)["relationship_evidence"]["review_status"], "pending"
        )
        self.document.write_text(self.quote + "\nAdditional review.", encoding="utf-8")
        review["evidence"]["sha256"] = self.digest()
        self.save()
        self.assertNotEqual(self.prepare().cache_key, pending.cache_key)

    def test_bad_hash_quote_scope_and_missing_evidence_are_rejected(self) -> None:
        original = json.dumps(self.payload)
        for issue in ("hash", "quote", "scope", "missing"):
            with self.subTest(issue=issue):
                self.payload = json.loads(original)
                evidence = self.payload["relationships"][0]["review"]["evidence"]
                if issue == "hash":
                    evidence["sha256"] = "0" * 64
                elif issue == "quote":
                    evidence["quote"] = "not in the document"
                elif issue == "scope":
                    self.payload["business_id"] = "other_business"
                else:
                    del evidence["sha256"]
                self.save()
                with self.assertRaises(ValueError):
                    self.prepare()

    def test_orphan_and_cardinality_failure_remain_invalid(self) -> None:
        with (self.business / "orders.csv").open("a") as stream:
            stream.write("003,fixture\n")
        self.assertEqual(self.edge(self.prepare())["status"], "invalid")
        self.payload["relationships"][0]["cardinality"] = "one_to_one"
        self.save()
        self.assertEqual(self.edge(self.prepare())["status"], "invalid")

    def test_unknown_source_mapping_fails_explicitly(self) -> None:
        self.payload["relationships"][0]["left"]["columns"] = ["missing"]
        self.save()
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            self.prepare()

    def test_sqlite_foreign_key_is_trusted_without_review_manifest(self) -> None:
        import sqlite3

        with sqlite3.connect(self.business / "source.sqlite") as source:
            source.executescript(
                "CREATE TABLE parent(id TEXT PRIMARY KEY); CREATE TABLE child(ref TEXT REFERENCES parent(id)); INSERT INTO parent VALUES ('a'),('b'); INSERT INTO child VALUES ('a'),('a'),('b');"
            )
        result = prepare_business(self.business, self.base / "output")
        context = json.loads((result.bundle_dir / "business_context.json").read_text())
        source_edge = next(
            e
            for e in context["schema_catalog"]["join_graph"]
            if e.get("relationship_evidence")
        )
        self.assertEqual(source_edge["status"], "validated")
        self.assertEqual(
            source_edge["relationship_evidence"]["origin"], "sqlite_foreign_key"
        )


if __name__ == "__main__":
    unittest.main()
