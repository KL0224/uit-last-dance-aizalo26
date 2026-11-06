"""Deterministic preparation of immutable datasets into atomic DuckDB bundles."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import time
import uuid
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any

import duckdb
import openpyxl

from datamate.b0.b01.contracts import JoinEdge
from datamate.b0.b01.schema_catalog import SchemaCatalogBuilder
from datamate.b0.b02.context_service import BusinessContextService
from datamate.b0.b02.contracts import ContractBuilder
from datamate.b0.b02.rule_compiler import BusinessRuleCompiler
from .models import (
    PARSER_VERSION,
    PreparationConfig,
    PreparationError,
    PreparedBusinessArtifacts,
    SourceTable,
)
from .normalization import (
    ColumnParser,
    descriptions,
    is_order_key,
    is_product,
    raw_text,
    role_for,
)
from .profiling import (
    DuckDBMetadataProvider,
    DuckDBProfileProvider,
    metadata_dict,
)
from .readers import READERS, column_names, fold, quote, sql_name


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(
            value, ensure_ascii=False, indent=2, allow_nan=False, default=raw_text
        )
        + "\n",
        encoding="utf-8",
    )


class _CSV:
    """Disk spool with a per-build NULL token, preserving empty strings and literal NULL."""

    def __init__(self, path: Path, cleanup: ExitStack) -> None:
        self.path = path
        self.null = "__DATAMATE_NULL_" + uuid.uuid4().hex
        self.stream = path.open("w", encoding="utf-8", newline="")
        cleanup.callback(self.stream.close)
        self.writer = csv.writer(self.stream)
        self.count = 0

    def row(self, values) -> None:
        self.writer.writerow([self.null if v is None else v for v in values])
        self.count += 1

    def load(self, connection, table: str, columns: dict[str, str]) -> None:
        self.stream.close()
        if self.count:
            connection.execute(
                f"CREATE TABLE {table} AS SELECT * FROM read_csv(?, columns=?, header=false, nullstr=?, auto_detect=false, parallel=false, max_line_size=16777216)",
                [str(self.path), columns, self.null],
            )
        else:
            definition = ", ".join(f"{quote(n)} {t}" for n, t in columns.items())
            connection.execute(f"CREATE TABLE {table} ({definition})")
        self.path.unlink()


def prepare_business(
    business_dir: str | Path,
    output_dir: str | Path,
    *,
    rulebook: str | Path | None = None,
    calendar: str | Path | None = None,
    config: PreparationConfig | None = None,
) -> PreparedBusinessArtifacts:
    """Prepare a business; a failed build raises and retains a diagnostic directory."""
    config = config or PreparationConfig()
    root = Path(business_dir).resolve(strict=True)
    output = Path(output_dir).resolve()
    bundle_parent = (output / root.name).resolve()
    if (
        not root.is_dir()
        or output == root
        or root in output.parents
        or bundle_parent == root
        or root in bundle_parent.parents
    ):
        raise ValueError("output must be outside the business input directory")
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if any(root not in p.resolve().parents for p in files):
        raise ValueError("source symlink escapes business directory")
    documents = [
        p
        for p in files
        if p.name.lower().startswith("readme") and p.suffix.lower() == ".md"
    ]
    if rulebook is not None:
        documents.append(Path(rulebook).resolve(strict=True))
    dependencies = list(
        dict.fromkeys(
            documents + ([Path(calendar).resolve(strict=True)] if calendar else [])
        )
    )
    hashes = {str(p): _hash(p) for p in dict.fromkeys(files + dependencies)}
    cache_inputs = {
        "sources": {str(p.relative_to(root)): hashes[str(p)] for p in files},
        "documents": {str(p): hashes[str(p)] for p in dependencies},
        "parser": PARSER_VERSION,
        "code_hash": hashlib.sha256(
            "".join(
                _hash(p) for p in sorted(Path(__file__).parent.parent.rglob("*.py"))
            ).encode()
        ).hexdigest(),
        "config": asdict(config),
        "duckdb": duckdb.__version__,
        "openpyxl": openpyxl.__version__,
    }
    key = hashlib.sha256(json.dumps(cache_inputs, sort_keys=True).encode()).hexdigest()
    parent = output / root.name
    target = parent / key
    required = (
        "data.duckdb",
        "source_manifest.json",
        "foundation_metadata.json",
        "business_context.json",
        "normalization_report.json",
    )
    if target.is_dir() and all((target / name).is_file() for name in required):
        manifest = json.loads((target / "source_manifest.json").read_text())
        if manifest.get("status") == "ready" and all(
            _hash(target / name) == digest
            for name, digest in manifest.get("artifact_hashes", {}).items()
        ):
            report = json.loads((target / "normalization_report.json").read_text())
            return PreparedBusinessArtifacts(
                root.name, key, target, "ready", True, report
            )
    parent.mkdir(parents=True, exist_ok=True)
    work = parent / (".build-" + uuid.uuid4().hex)
    work.mkdir()
    started = time.monotonic()
    manifest = {
        "business_id": root.name,
        "cache_key": key,
        "parser_version": PARSER_VERSION,
        "status": "building",
        "inputs": cache_inputs,
        "files": [],
    }
    report: dict[str, Any] = {
        "status": "building",
        "issues": {},
        "source_rows": 0,
        "raw_rows": 0,
        "excluded_non_data_rows": 0,
        "normalized_rows": 0,
        "deduplicated_rows": 0,
    }
    try:
        sources: list[SourceTable] = []
        failures = []
        for path in files:
            rel = path.relative_to(root).as_posix()
            entry: dict[str, Any] = {
                "path": rel,
                "sha256": hashes[str(path)],
                "status": "discovered",
                "tables": [],
            }
            manifest["files"].append(entry)
            extension = path.suffix.lower()
            if (
                path in dependencies
                or path.name in {"questions.jsonl", "answers.jsonl"}
                or extension
                in {
                    ".md",
                    ".txt",
                    ".json",
                    ".jsonl",
                    ".pdf",
                    ".png",
                    ".jpg",
                }
            ):
                entry.update(
                    status="excluded",
                    reason="documentation or non-business/competition artifact",
                )
                continue
            if extension not in READERS:
                entry.update(status="error", error="unsupported source format")
                failures.append(rel)
                continue
            try:
                tables = READERS[extension].discover(path, rel, config.source_overrides)
                sources.extend(tables)
                entry["tables"] = [
                    {
                        "source_id": t.source_id,
                        "sheet": t.sheet,
                        "header_row": t.header_row,
                        "end_row": t.end_row,
                        "headers": t.headers,
                        "encoding": t.encoding if extension == ".csv" else None,
                        "delimiter": t.delimiter if extension == ".csv" else None,
                        "excel_epoch": t.epoch if extension == ".xlsx" else None,
                        "sheet_year": t.year,
                        "logical_family": t.logical_family,
                        "status": "discovered",
                    }
                    for t in tables
                ]
                entry["status"] = "discovered" if tables else "empty"
                if extension == ".xlsx":
                    workbook = openpyxl.load_workbook(path, read_only=True)
                    try:
                        entry["sheets"] = [
                            {
                                "name": s,
                                "status": "discovered"
                                if any(t.sheet == s for t in tables)
                                else "empty",
                            }
                            for s in workbook.sheetnames
                        ]
                    finally:
                        workbook.close()
            except Exception as exc:  # noqa: BLE001 -- record heterogeneous reader failures for every source
                entry.update(status="error", error=f"{type(exc).__name__}: {exc}")
                failures.append(rel)
        if failures or not sources:
            raise PreparationError(
                f"discovery failed: {failures or 'no business tables'}"
            )
        mapping, relationships = _materialize(
            work, sources, documents, config, manifest, report
        )
        provider = DuckDBMetadataProvider(
            work / "data.duckdb", root.name, mapping, relationships, config
        )
        metadata = provider.load(root.name)
        _json(work / "foundation_metadata.json", metadata_dict(metadata))
        with duckdb.connect(str(work / "data.duckdb"), read_only=True) as connection:
            connection.execute("SET threads=?", [config.threads])
            connection.execute("SET memory_limit=?", [config.memory_limit])
            service = BusinessContextService(
                provider,
                SchemaCatalogBuilder(DuckDBProfileProvider(connection)),
                BusinessRuleCompiler(),
                ContractBuilder(),
            )
            context = service.prepare(root.name, documents)
        _json(work / "business_context.json", context.to_dict())
        if any(_hash(Path(p)) != digest for p, digest in hashes.items()):
            raise PreparationError(
                "source changed while building; bundle not published"
            )
        report.update(
            status="ready",
            elapsed_seconds=round(time.monotonic() - started, 4),
            table_count=len(mapping),
        )
        _json(work / "normalization_report.json", report)
        manifest.update(
            status="ready",
            artifact_hashes={
                name: _hash(work / name)
                for name in required
                if name != "source_manifest.json"
            },
        )
        _json(work / "source_manifest.json", manifest)
        shutil.rmtree(work / "spill", ignore_errors=True)
        if target.exists():
            # A concurrent successful builder may have published the same content key.
            existing = json.loads((target / "source_manifest.json").read_text())
            valid = existing.get("status") == "ready" and all(
                (target / n).is_file() and _hash(target / n) == d
                for n, d in existing.get("artifact_hashes", {}).items()
            )
            if valid:
                shutil.rmtree(work)
            else:
                os.rename(target, parent / ("corrupt-" + uuid.uuid4().hex))
                os.rename(work, target)
        else:
            os.rename(work, target)
        return PreparedBusinessArtifacts(root.name, key, target, "ready", False, report)
    except Exception as exc:
        for entry in manifest["files"]:
            if entry["status"] == "discovered":
                entry.update(
                    status="aborted", reason="build failed before source completed"
                )
        manifest.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        report.update(
            status="failed", elapsed_seconds=round(time.monotonic() - started, 4)
        )
        _json(work / "source_manifest.json", manifest)
        _json(work / "normalization_report.json", report)
        failed = parent / ("failed-" + key[:12] + "-" + uuid.uuid4().hex[:8])
        os.rename(work, failed)
        raise PreparationError(f"{exc}; diagnostics: {failed}") from exc


def _materialize(work, sources, documents, config, manifest, report):
    with ExitStack() as spool_cleanup:
        descriptions_by_name = descriptions(
            "\n".join(p.read_text(encoding="utf-8") for p in documents)
        )
        document_text = fold(
            "\n".join(p.read_text(encoding="utf-8") for p in documents)
        )
        # This opt-in is tied to the export convention explicitly documented in the rulebook.
        export_convention = all(
            clause in document_text
            for clause in (
                "hai dong cua cung mot don giong nhau o moi o",
                "bang khong ghi theo don",
                "o de trong o cac dong sau cua cung mot nhom dong",
            )
        )
        issues = _CSV(work / "issues.csv", spool_cleanup)
        lineage = _CSV(work / "lineage.csv", spool_cleanup)
        issue_counts = Counter()

        def issue(source, row, column, code, rule):
            issues.row((source.source_id, row, column, code, rule))
            issue_counts[code] += 1

        mapping = {}
        groups = defaultdict(list)
        for source in sources:
            override = config.source_overrides.get(
                f"{source.relative_path}#{source.sheet}",
                config.source_overrides.get(source.relative_path, {}),
            )
            family = override.get("logical_table", source.logical_family)
            signature = (family, source.headers)
            groups[signature].append(source)
        with duckdb.connect(str(work / "data.duckdb")) as connection:
            connection.execute("SET threads=?", [config.threads])
            connection.execute("SET memory_limit=?", [config.memory_limit])
            connection.execute("SET temp_directory=?", [str(work / "spill")])
            connection.execute("CREATE SCHEMA raw")
            connection.execute("CREATE SCHEMA meta")
            for (family, headers), partitions in sorted(groups.items()):
                digest = hashlib.sha256(
                    json.dumps([family, headers], ensure_ascii=False).encode()
                ).hexdigest()[:8]
                name = sql_name(family, "table") + "_" + digest
                columns = column_names(headers)
                descriptions_list = [descriptions_by_name.get(h, "") for h in headers]
                roles = [
                    role_for(h, d)
                    for h, d in zip(headers, descriptions_list, strict=True)
                ]
                for source in partitions:
                    overrides = config.source_overrides.get(
                        f"{source.relative_path}#{source.sheet}",
                        config.source_overrides.get(source.relative_path, {}),
                    ).get("roles", {})
                    roles = [
                        overrides.get(h, r) for h, r in zip(headers, roles, strict=True)
                    ]
                if any(
                    r
                    not in {
                        "identifier",
                        "text",
                        "status",
                        "date",
                        "money",
                        "quantity",
                        "boolean",
                        "unknown",
                    }
                    for r in roles
                ):
                    raise ValueError("unsupported role override")
                parsers = [ColumnParser(r) for r in roles]
                orders = [
                    i
                    for i, (h, d) in enumerate(
                        zip(headers, descriptions_list, strict=True)
                    )
                    if is_order_key(h, d)
                ]
                products = [
                    i
                    for i, (h, d) in enumerate(
                        zip(headers, descriptions_list, strict=True)
                    )
                    if is_product(h, d)
                ]
                order_lines = (
                    export_convention
                    and len(orders) == 1
                    and bool(products)
                    and "quantity" in roles
                )
                normalized = _CSV(work / "normalized.csv", spool_cleanup)
                seen = {}
                row_id = 0
                for source in partitions:
                    raw = _CSV(work / "source.csv", spool_cleanup)
                    reader = READERS[source.path.suffix.lower()]
                    for row in reader.rows(source):
                        raw.row(
                            (
                                row.number,
                                *(raw_text(v) for v in row.values),
                                json.dumps(
                                    row.formulas, ensure_ascii=False, default=raw_text
                                ),
                            )
                        )
                    raw_name = "raw." + quote(source.source_id)
                    raw.load(
                        connection,
                        raw_name,
                        {
                            "__dm_source_row": "BIGINT",
                            **dict.fromkeys(columns, "VARCHAR"),
                            "__dm_formula_cache": "VARCHAR",
                        },
                    )
                    cursor = connection.cursor()
                    cursor.execute(f"SELECT * FROM {raw_name} ORDER BY __dm_source_row")
                    group_order = None
                    order_fields = {}
                    while batch := cursor.fetchmany(config.batch_size):
                        for raw_row in batch:
                            number, *values, cache_json = raw_row
                            report["raw_rows"] += 1
                            marker = fold(values[0] or "")
                            footer_marker = marker in {
                                "tong",
                                "tong thang",
                                "tong cong",
                            } or marker.startswith("ghi chu ")
                            if (
                                roles[0] == "date"
                                and footer_marker
                                and not any(values[i] for i in set(orders + products))
                            ):
                                report["excluded_non_data_rows"] += 1
                                issue(
                                    source,
                                    number,
                                    columns[0],
                                    "non_data_footer",
                                    "explicit summary/note in date field; no order or product identity; retained in raw",
                                )
                                # A summary/note terminates the preceding order group.
                                group_order, order_fields = None, {}
                                continue
                            report["source_rows"] += 1
                            cache = json.loads(cache_json)
                            for index, value in cache.items():
                                values[int(index)] = raw_text(value)
                                if value is None:
                                    issue(
                                        source,
                                        number,
                                        columns[int(index)],
                                        "formula_missing_cache",
                                        "cached value only; no recalculation",
                                    )
                            if order_lines:
                                order_index = orders[0]
                                if (
                                    values[order_index] is not None
                                    and str(values[order_index]).strip()
                                ):
                                    current = values[order_index]
                                    if current != group_order:
                                        group_order, order_fields = current, {}
                                for i, value in enumerate(values):
                                    label = fold(headers[i])
                                    allowed = (
                                        i == order_index
                                        or roles[i] == "status"
                                        or (
                                            roles[i] == "date"
                                            and not (
                                                set(label.split()) & {"han", "expiry"}
                                            )
                                        )
                                        or (
                                            roles[i] in {"text", "identifier"}
                                            and any(
                                                w in label for w in ("khach", "ghi chu")
                                            )
                                        )
                                    )
                                    if (
                                        not allowed
                                        or group_order is None
                                        or str(i) in cache
                                    ):
                                        continue
                                    if value is None or not str(value).strip():
                                        if i in order_fields:
                                            values[i] = order_fields[i]
                                            issue(
                                                source,
                                                number,
                                                columns[i],
                                                "forward_fill",
                                                "documented order group; first nonempty order field",
                                            )
                                    else:
                                        order_fields.setdefault(i, value)
                            signature = (
                                tuple(values),
                                tuple(
                                    (index, raw_row[int(index) + 1])
                                    for index in sorted(cache)
                                ),
                            )
                            dedup = (
                                order_lines
                                and values[orders[0]] is not None
                                and signature in seen
                            )
                            if dedup:
                                normalized_id = seen[signature]
                                report["deduplicated_rows"] += 1
                                issue(
                                    source,
                                    number,
                                    None,
                                    "duplicate_export",
                                    "documented identical order line export",
                                )
                            else:
                                row_id += 1
                                normalized_id = row_id
                                parsed = []
                                for index, (parser, value) in enumerate(
                                    zip(parsers, values, strict=True)
                                ):
                                    result, code = parser.parse(
                                        value, epoch=source.epoch, year=source.year
                                    )
                                    if code:
                                        issue(
                                            source,
                                            number,
                                            columns[index],
                                            code,
                                            "role-aware parser; raw value retained",
                                        )
                                    parsed.append(result)
                                normalized.row((row_id, *parsed))
                                if order_lines:
                                    seen[signature] = row_id
                            lineage.row(
                                (name, normalized_id, source.source_id, number, dedup)
                            )
                    cursor.close()
                    for entry in manifest["files"]:
                        for table in entry["tables"]:
                            if table["source_id"] == source.source_id:
                                table.update(
                                    status="read",
                                    raw_rows=raw.count,
                                    normalized_table=name,
                                )
                        if entry["path"] == source.relative_path:
                            entry["status"] = "read"
                types = {
                    column: parser.sql_type()
                    for column, parser in zip(columns, parsers, strict=True)
                }
                # No Decimal is rounded: oversized precision stays text and is reported.
                for column, parser in zip(columns, parsers, strict=True):
                    if (
                        parser.role in {"money", "quantity"}
                        and parser.sql_type() == "VARCHAR"
                    ):
                        issue(
                            partitions[0],
                            0,
                            column,
                            "decimal_precision_preserved_as_text",
                            "value exceeds supported exact decimal precision",
                        )
                normalized.load(
                    connection, quote(name), {"__dm_row_id": "BIGINT", **types}
                )
                report["normalized_rows"] += row_id
                mapping[name] = {
                    "columns": {
                        c: {"original_name": h, "role": r, "sql_type": types[c]}
                        for c, h, r in zip(columns, headers, roles, strict=True)
                    },
                    "source_ids": [s.source_id for s in partitions],
                    "family": family,
                }
            issues.load(
                connection,
                "meta.quality_issues",
                {
                    "source_id": "VARCHAR",
                    "source_row": "BIGINT",
                    "column_name": "VARCHAR",
                    "code": "VARCHAR",
                    "rule": "VARCHAR",
                },
            )
            lineage.load(
                connection,
                "meta.lineage",
                {
                    "table_name": "VARCHAR",
                    "row_id": "BIGINT",
                    "source_id": "VARCHAR",
                    "source_row": "BIGINT",
                    "deduplicated": "BOOLEAN",
                },
            )
            connection.execute(
                "CREATE TABLE meta.source_mapping (source_id VARCHAR, path VARCHAR, sheet VARCHAR, header_row BIGINT, normalized_table VARCHAR)"
            )
            rows = [
                (s.source_id, s.relative_path, s.sheet, s.header_row, name)
                for name, m in mapping.items()
                for s in sources
                if s.source_id in m["source_ids"]
            ]
            connection.executemany(
                "INSERT INTO meta.source_mapping VALUES (?, ?, ?, ?, ?)", rows
            )
            connection.execute(
                "CREATE TABLE meta.column_mapping (table_name VARCHAR, column_name VARCHAR, original_name VARCHAR, role VARCHAR)"
            )
            connection.executemany(
                "INSERT INTO meta.column_mapping VALUES (?, ?, ?, ?)",
                [
                    (t, c, m["original_name"], m["role"])
                    for t, v in mapping.items()
                    for c, m in v["columns"].items()
                ],
            )
            connection.execute("CHECKPOINT")
        report["issues"] = dict(sorted(issue_counts.items()))
        return mapping, _relationships(sources, mapping)


def _relationships(sources, mapping):
    """Preserve declared SQLite composite foreign keys as complete ordered tuples."""
    source_tables = {
        (s.relative_path, s.sheet): (s, name)
        for s in sources
        for name, m in mapping.items()
        if s.source_id in m["source_ids"]
    }
    edges = []
    for source in sources:
        constraints = defaultdict(list)
        for fk in source.sqlite_foreign_keys:
            constraints[fk["id"]].append(fk)
        for parts in constraints.values():
            parts.sort(key=lambda p: p["seq"])
            target = source_tables.get((source.relative_path, parts[0]["table"]))
            if not target or any(not p["to"] for p in parts):
                continue
            left_name = source_tables[(source.relative_path, source.sheet)][1]
            right_name = target[1]
            left_cols = {
                v["original_name"]: k for k, v in mapping[left_name]["columns"].items()
            }
            right_cols = {
                v["original_name"]: k for k, v in mapping[right_name]["columns"].items()
            }
            pairs = [(left_cols[p["from"]], right_cols[p["to"]]) for p in parts]
            edges.append(
                JoinEdge(
                    left_name,
                    pairs[0][0],
                    right_name,
                    pairs[0][1],
                    "many_to_one",
                    "candidate",
                    0.8,
                    (
                        f"SQLite foreign_key_list: {source.relative_path}#{source.sheet}",
                    ),
                    additional_key_pairs=tuple(pairs[1:]),
                )
            )
    return tuple(edges)
