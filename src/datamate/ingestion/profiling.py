"""Full-table SQL profiling, independent of bounded JSON samples."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, replace
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from datamate.contracts import ColumnMetadata, JoinEdge, KeyCandidate, TableMetadata
from datamate.ingestion.models import PreparationConfig
from datamate.ingestion.readers import quote
from datamate.metadata_adapter import BaseMetadataProvider, FoundationMetadata


def json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        # Decimal metadata samples are strings to preserve exact values in JSON.
        return format(value, "f")
    return value


class BaseProfileProvider(ABC):
    @abstractmethod
    def check_key(self, table: TableMetadata, columns: tuple[str, ...]) -> KeyCandidate:
        raise NotImplementedError

    @abstractmethod
    def check_join(self, edge: JoinEdge) -> JoinEdge:
        raise NotImplementedError


class DuckDBProfileProvider(BaseProfileProvider):
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self.connection = connection

    def check_key(self, table: TableMetadata, columns: tuple[str, ...]) -> KeyCandidate:
        fields = ", ".join(quote(column) for column in columns)
        nulls = " OR ".join(f"{quote(column)} IS NULL" for column in columns)
        query = (
            f"SELECT COUNT(*), COUNT(*) FILTER (WHERE {nulls}) FROM {quote(table.name)}"
        )
        count, null_count = self.connection.execute(query).fetchone()
        distinct = self.connection.execute(
            f"SELECT COUNT(*) FROM (SELECT DISTINCT {fields} FROM {quote(table.name)})"
        ).fetchone()[0]
        unique = count > 0 and null_count == 0 and distinct == count
        return KeyCandidate(
            table.name,
            columns,
            "primary",
            "candidate" if unique else "invalid",
            1.0 if unique else 0.0,
            (
                f"exact SQL profile: rows={count}, null_keys={null_count}, distinct_keys={distinct}",
            ),
        )

    def check_join(self, edge: JoinEdge) -> JoinEdge:
        left = tuple(pair[0] for pair in edge.key_pairs)
        right = tuple(pair[1] for pair in edge.key_pairs)

        def relation(table: str, columns: tuple[str, ...]) -> tuple[str, int, int]:
            projection = ", ".join(
                f"{quote(column)} AS k{index}" for index, column in enumerate(columns)
            )
            condition = " AND ".join(
                f"{quote(column)} IS NOT NULL" for column in columns
            )
            sql = f"SELECT {projection} FROM {quote(table)} WHERE {condition}"
            count = self.connection.execute(f"SELECT COUNT(*) FROM ({sql})").fetchone()[
                0
            ]
            distinct = self.connection.execute(
                f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM ({sql}))"
            ).fetchone()[0]
            return sql, count, distinct

        lsql, lcount, ldistinct = relation(edge.left_table, left)
        rsql, rcount, rdistinct = relation(edge.right_table, right)
        keys = ", ".join(f"k{index}" for index in range(len(left)))
        overlap = self.connection.execute(
            f"SELECT COUNT(*) FROM (SELECT DISTINCT {keys} FROM ({lsql}) INTERSECT SELECT DISTINCT {keys} FROM ({rsql}))"
        ).fetchone()[0]
        from datamate.schema_catalog import _cardinality

        observed = _cardinality(lcount == ldistinct, rcount == rdistinct)
        evidence = edge.evidence + (
            f"exact SQL tuple coverage: left={overlap}/{ldistinct}, right={overlap}/{rdistinct}; observed={observed}",
        )
        if not ldistinct or not rdistinct:
            return replace(edge, status="uncertain", confidence=0.2, evidence=evidence)
        if not edge.evidence:
            return replace(
                edge,
                status="uncertain",
                confidence=0.75,
                evidence=evidence,
                cardinality=observed,
                fanout_warning=observed != "one_to_one",
            )
        valid_shapes = {
            "one_to_one": {"one_to_one"},
            "one_to_many": {"one_to_one", "one_to_many"},
            "many_to_one": {"one_to_one", "many_to_one"},
        }
        if edge.cardinality not in valid_shapes:
            return replace(
                edge, status="candidate", evidence=evidence, fanout_warning=True
            )
        shape_ok = observed in valid_shapes[edge.cardinality]
        coverage_ok = (
            overlap == ldistinct
            if edge.cardinality == "many_to_one"
            else overlap == rdistinct
            if edge.cardinality == "one_to_many"
            else overlap == ldistinct == rdistinct
        )
        status = "validated" if shape_ok and coverage_ok else "invalid"
        if edge.cardinality == "one_to_one" and shape_ok and not coverage_ok:
            status = "uncertain"
        return replace(
            edge,
            status=status,
            confidence=0.95 if status == "validated" else 0.0,
            evidence=evidence,
            fanout_warning=edge.cardinality != "one_to_one",
        )


class DuckDBMetadataProvider(BaseMetadataProvider):
    """Read a materialized normalized store; do not retain full rows in DTOs."""

    def __init__(
        self,
        database: Path,
        business_id: str,
        mapping: dict[str, Any],
        relationships: tuple[JoinEdge, ...] = (),
        config: PreparationConfig | None = None,
    ) -> None:
        self.database = database
        self.business_id = business_id
        self.mapping = mapping
        self.relationships = relationships
        self.config = config or PreparationConfig()

    def load(self, business_id: str) -> FoundationMetadata:
        if business_id != self.business_id:
            raise ValueError("database metadata business mismatch")
        tables: list[TableMetadata] = []
        profiles: dict[str, Any] = {}
        with duckdb.connect(str(self.database), read_only=True) as connection:
            connection.execute("SET memory_limit=?", [self.config.memory_limit])
            connection.execute("SET threads=?", [self.config.threads])
            connection.execute(
                "SET temp_directory=?", [str(self.database.parent / "spill")]
            )
            for table_name, mapping in sorted(self.mapping.items()):
                columns: list[ColumnMetadata] = []
                count = connection.execute(
                    f"SELECT COUNT(*) FROM {quote(table_name)}"
                ).fetchone()[0]
                column_profiles: dict[str, Any] = {}
                for column_name in mapping["columns"]:
                    dtype = connection.execute(
                        "SELECT data_type FROM information_schema.columns WHERE table_schema='main' AND table_name=? AND column_name=?",
                        [table_name, column_name],
                    ).fetchone()[0]
                    null_count, cardinality = connection.execute(
                        f"SELECT COUNT(*) FILTER (WHERE {quote(column_name)} IS NULL), COUNT(DISTINCT {quote(column_name)}) FROM {quote(table_name)}"
                    ).fetchone()
                    stats = {
                        "null_count": null_count,
                        "cardinality": cardinality,
                        "mode": "exact",
                    }
                    if dtype in {"DATE", "TIMESTAMP", "TIME"}:
                        low, high = connection.execute(
                            f"SELECT MIN({quote(column_name)}), MAX({quote(column_name)}) FROM {quote(table_name)}"
                        ).fetchone()
                        stats.update(
                            observed_min=json_value(low), observed_max=json_value(high)
                        )
                    column_profiles[column_name] = stats
                    columns.append(
                        ColumnMetadata(
                            column_name,
                            dtype,
                            null_count > 0,
                            null_count / count if count else 0,
                            cardinality,
                            mapping["columns"][column_name]["original_name"],
                        )
                    )
                projection = ", ".join(quote(column.name) for column in columns)
                samples = connection.execute(
                    f"SELECT {projection} FROM {quote(table_name)} ORDER BY __dm_row_id LIMIT 5"
                ).fetchall()
                sample_rows = tuple(
                    {
                        column.name: json_value(value)
                        for column, value in zip(columns, row, strict=True)
                    }
                    for row in samples
                )
                profiles[table_name] = {
                    "row_count": count,
                    "columns": column_profiles,
                    "samples": sample_rows,
                    "profile_mode": "exact",
                    "coverage_semantics": "observed only; business completeness unknown",
                }
                tables.append(
                    TableMetadata(
                        table_name,
                        tuple(columns),
                        row_count=count,
                        grain=mapping.get("grain"),
                        provenance="; ".join(mapping["source_ids"]),
                        profile_rows=sample_rows,
                        profile_is_complete=False,
                    )
                )
        return FoundationMetadata(
            business_id,
            tuple(tables),
            self.relationships,
            profiles,
            {"schema_mapping": self.mapping},
            None,
            {
                "engine": "duckdb",
                "sql_dialect": "duckdb",
                "database": "data.duckdb",
                "schema": "main",
            },
        )


def metadata_dict(metadata: FoundationMetadata) -> dict[str, Any]:
    obj = asdict(metadata)
    for relationship in obj["relationships"]:
        relationship.pop("status", None)
        relationship.pop("fanout_warning", None)
    obj["metadata_version"] = "1.1"
    return obj
