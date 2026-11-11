"""Audit full prepared train bundles against their published metadata and lineage."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb

from datamate.ingestion.ingestion.profiling import DuckDBProfileProvider
from datamate.ingestion.metadata_adapter import BusinessContextSchemaReader


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def audit(report_path: Path, baseline_report: Path | None = None) -> dict[str, Any]:
    benchmark = json.loads(report_path.read_text())
    baselines = {}
    if baseline_report is not None:
        for record in json.loads(baseline_report.read_text())["results"]:
            folder = Path(record["warm"]["bundle_dir"])
            baselines[record["business_id"]] = json.loads(
                (folder / "business_context.json").read_text()
            )
    audited = []
    files = Counter()
    issues = Counter()
    for record in sorted(benchmark["results"], key=lambda r: r["business_id"]):
        assert "error" not in record["cold"], record
        bundle = Path(record["warm"]["bundle_dir"])
        manifest = json.loads((bundle / "source_manifest.json").read_text())
        context = json.loads((bundle / "business_context.json").read_text())
        metadata = json.loads((bundle / "foundation_metadata.json").read_text())
        report = json.loads((bundle / "normalization_report.json").read_text())
        assert manifest["status"] == report["status"] == "ready"
        assert record["cold"]["cache_hit"] is False
        assert record["warm"]["cache_hit"] is True
        assert record["cold"]["cache_key"] == record["warm"]["cache_key"]
        data_files = [
            f
            for f in manifest["files"]
            if Path(f["path"]).suffix in {".csv", ".xlsx", ".sqlite"}
        ]
        assert all(f["status"] in {"read", "empty"} for f in data_files), data_files
        for f in data_files:
            files[Path(f["path"]).suffix] += 1
            assert all(t["status"] == "read" for t in f["tables"])
        assert context["contract_version"] == metadata["metadata_version"] == "1.1"
        assert context["normalized_data_handle"]["database"] == "data.duckdb"
        tables = context["schema_catalog"]["tables"]
        catalog = BusinessContextSchemaReader().read(context)
        edge_status = Counter(edge.status for edge in catalog.join_graph)
        key_status = Counter(key.status for key in catalog.key_candidates)
        baseline = baselines.get(record["business_id"])
        if baseline_report is not None:
            assert baseline is not None, "baseline does not cover this business"

            def table_signature(payload: dict[str, Any]) -> dict[str, tuple]:
                return {
                    t["name"]: (
                        t["row_count"],
                        [(c["name"], c["data_type"]) for c in t["columns"]],
                    )
                    for t in payload["schema_catalog"]["tables"]
                }

            assert table_signature(context) == table_signature(baseline), record[
                "business_id"
            ]
            assert context["data_profiling"] == baseline["data_profiling"], record[
                "business_id"
            ]
            assert context["rule_catalog"] == baseline["rule_catalog"], record[
                "business_id"
            ]
        with duckdb.connect(str(bundle / "data.duckdb"), read_only=True) as c:
            c.execute("SET threads=2")
            c.execute("SET memory_limit='512MB'")
            raw_names = [
                r[0]
                for r in c.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='raw'"
                ).fetchall()
            ]
            actual_raw_rows = sum(
                c.execute(f"SELECT COUNT(*) FROM raw.{quote(n)}").fetchone()[0]
                for n in raw_names
            )
            assert actual_raw_rows == report["raw_rows"]
            assert (
                sum(t["raw_rows"] for f in data_files for t in f["tables"])
                == actual_raw_rows
            )
            assert all(len(t["profile_rows"]) <= 5 for t in metadata["tables"])
            assert all("profile_rows" not in t for t in tables)
            actual_names = {
                r[0]
                for r in c.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
                ).fetchall()
            }
            assert actual_names == {t["name"] for t in tables}
            assert (
                report["raw_rows"]
                == report["source_rows"] + report["excluded_non_data_rows"]
            )
            lineage = c.execute(
                "SELECT COUNT(*), COUNT(*) FILTER(WHERE deduplicated) FROM meta.lineage"
            ).fetchone()
            assert lineage == (report["source_rows"], report["deduplicated_rows"])
            assert (
                report["source_rows"]
                == report["normalized_rows"] + report["deduplicated_rows"]
            )
            for table in tables:
                name = table["name"]
                assert (
                    c.execute(f"SELECT COUNT(*) FROM {quote(name)}").fetchone()[0]
                    == table["row_count"]
                )
                assert (
                    c.execute(
                        "SELECT COUNT(*) FROM meta.lineage WHERE table_name=? AND NOT deduplicated",
                        [name],
                    ).fetchone()[0]
                    == table["row_count"]
                )
                schema = c.execute(
                    "SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='main' AND table_name=?",
                    [name],
                ).fetchall()
                assert dict(schema) == {
                    "__dm_row_id": "BIGINT",
                    **{col["name"]: col["data_type"] for col in table["columns"]},
                }
                assert len(context["data_profiling"][name]["samples"]) <= 5
                for column in table["columns"]:
                    field = quote(column["name"])
                    nulls, distinct = c.execute(
                        f"SELECT COUNT(*) FILTER(WHERE {field} IS NULL), COUNT(DISTINCT {field}) FROM {quote(name)}"
                    ).fetchone()
                    profile = context["data_profiling"][name]["columns"][column["name"]]
                    assert (
                        nulls == profile["null_count"]
                        and distinct == profile["cardinality"]
                    )
                missing = c.execute(
                    f"SELECT COUNT(*) FROM meta.lineage l LEFT JOIN {quote(name)} t ON l.row_id=t.__dm_row_id WHERE l.table_name=? AND t.__dm_row_id IS NULL",
                    [name],
                ).fetchone()[0]
                assert missing == 0
            for key in context["schema_catalog"]["key_candidates"]:
                assert "__dm_row_id" not in key["columns"]
            provider = DuckDBProfileProvider(c, context["business_id"])
            by_name = {table.name: table for table in catalog.tables}
            for key in catalog.key_candidates:
                checked = provider.check_key(by_name[key.table], key.columns)
                assert checked.status == key.status, key
            for edge in catalog.join_graph:
                if any(
                    "conflicting cardinality declarations" in text
                    for text in edge.evidence
                ):
                    assert edge.status == "invalid", edge
                    continue  # Blocked before SQL validation; no statistics are promised.
                checked = provider.check_join(edge)
                assert checked.statistics == edge.statistics, edge
                assert checked.status == edge.status, edge
            db_issues = dict(
                c.execute(
                    "SELECT code,COUNT(*) FROM meta.quality_issues GROUP BY code"
                ).fetchall()
            )
            assert db_issues == report["issues"]
            issues.update(db_issues)
        audited.append(
            {
                "business_id": record["business_id"],
                "data_files": len(data_files),
                "tables": len(tables),
                "source_rows": report["source_rows"],
                "normalized_rows": report["normalized_rows"],
                "issues": report["issues"],
                "cold_seconds": record["cold"]["wall_seconds"],
                "warm_seconds": record["warm"]["wall_seconds"],
                "peak_rss_mib": record["cold"]["peak_rss_mib"],
                "key_count": len(catalog.key_candidates),
                "key_status": dict(key_status),
                "edge_count": len(catalog.join_graph),
                "edge_status": dict(edge_status),
                "fanout_count": sum(edge.fanout_warning for edge in catalog.join_graph),
                "search_limit_warnings": [
                    w
                    for w in catalog.warnings
                    if "search limited" in w or "search stopped" in w
                ],
                "baseline_counts_match": baseline is not None,
                "baseline_profiles_and_rules_match": baseline is not None,
                "baseline_key_count": len(baseline["schema_catalog"]["key_candidates"])
                if baseline
                else None,
                "baseline_edge_count": len(baseline["schema_catalog"]["join_graph"])
                if baseline
                else None,
            }
        )
        print(record["business_id"], "verified", flush=True)
    result = {
        "business_count": len(audited),
        "data_files": dict(files),
        "issue_counts": dict(issues),
        "source_unchanged": benchmark["source_unchanged"],
        "baseline_report": str(baseline_report) if baseline_report else None,
        "results": audited,
    }
    target = report_path.with_name(report_path.stem + "-audit.json")
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(target)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--baseline-report", type=Path)
    args = parser.parse_args()
    audit(args.report, args.baseline_report)
