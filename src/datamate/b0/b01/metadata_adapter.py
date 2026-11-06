"""Strict JSON boundary for metadata produced by the team's Data Foundation."""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, overload

from .contracts import ColumnMetadata, JoinEdge, TableMetadata


@dataclass(frozen=True)
class FoundationMetadata:
    """Producer-owned metadata; this adapter does not read physical data sources."""

    business_id: str
    tables: tuple[TableMetadata, ...]
    relationships: tuple[JoinEdge, ...] = ()
    data_profiling: dict[str, Any] | None = None
    business_metadata: dict[str, Any] | None = None
    answerability_constraints: dict[str, Any] | None = None
    normalized_data_handle: dict[str, Any] | None = None


class BaseMetadataProvider(ABC):
    """Allow future Data Foundation integration without changing B01/B02."""

    @abstractmethod
    def load(self, business_id: str) -> FoundationMetadata:
        """Retrieve one business; mismatched scope must fail."""
        raise NotImplementedError


class JSONMetadataProvider(BaseMetadataProvider):
    """Load version 1.0 producer metadata from a JSON file, without caches/writes."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self, business_id: str) -> FoundationMetadata:
        """Validate a JSON envelope before exposing dataclasses to the semantic layer."""
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return self.from_dict(payload, business_id)

    def from_dict(self, payload: Any, business_id: str) -> FoundationMetadata:
        """Decode explicit types and reject unknown fields or unsupported versions."""
        obj = _object(
            payload,
            {
                "metadata_version",
                "business_id",
                "tables",
                "relationships",
                "data_profiling",
                "business_metadata",
                "answerability_constraints",
                "normalized_data_handle",
            },
            "metadata",
        )
        if obj.get("metadata_version") not in {"1.0", "1.1"}:
            raise ValueError("metadata_version must be '1.0' or '1.1'")
        if (
            not isinstance(obj.get("business_id"), str)
            or obj["business_id"] != business_id
            or not business_id.strip()
        ):
            raise ValueError(
                "producer metadata business_id does not match requested business"
            )
        handle = obj.get("normalized_data_handle")
        if handle is not None:
            if obj["metadata_version"] != "1.1" or not isinstance(handle, dict):
                raise ValueError("normalized_data_handle requires metadata 1.1")
            if handle != {
                "engine": "duckdb",
                "sql_dialect": "duckdb",
                "database": "data.duckdb",
                "schema": "main",
            }:
                raise ValueError("unsupported normalized_data_handle")
        tables = tuple(_table(value) for value in _list(obj.get("tables"), "tables"))
        relationships = tuple(
            _relationship(value)
            for value in _list(obj.get("relationships", []), "relationships")
        )
        columns_by_table = {
            table.name: {column.name for column in table.columns} for table in tables
        }
        if len(columns_by_table) != len(tables):
            raise ValueError("duplicate producer table names")
        for edge in relationships:
            for left, right in edge.key_pairs:
                if left not in columns_by_table.get(
                    edge.left_table, set()
                ) or right not in columns_by_table.get(edge.right_table, set()):
                    raise ValueError(
                        "producer relationship references unknown table or column"
                    )
            if len({left for left, _ in edge.key_pairs}) != len(edge.key_pairs) or len(
                {right for _, right in edge.key_pairs}
            ) != len(edge.key_pairs):
                raise ValueError("producer relationship repeats a join key column")
        for key in ("data_profiling", "business_metadata", "answerability_constraints"):
            if obj.get(key) is not None and not isinstance(obj[key], dict):
                raise TypeError(f"{key} must be an object or null")
        return FoundationMetadata(
            business_id,
            tables,
            relationships,
            obj.get("data_profiling"),
            obj.get("business_metadata"),
            obj.get("answerability_constraints"),
            handle,
        )


def _object(value: Any, allowed: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{label} has unsupported fields: {sorted(unknown)}")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def _strings(value: Any, label: str) -> tuple[str, ...]:
    items = _list(value, label)
    if any(not isinstance(item, str) or not item.strip() for item in items):
        raise ValueError(f"{label} must contain non-empty strings")
    return tuple(items)


def _pairs(value: Any, label: str) -> tuple[tuple[str, ...], ...]:
    return tuple(_strings(item, label) for item in _list(value, label))


@overload
def _text(value: Any, label: str, optional: Literal[False] = False) -> str: ...


@overload
def _text(value: Any, label: str, optional: Literal[True]) -> str | None: ...


def _text(value: Any, label: str, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _count(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer or null")
    return value


@overload
def _ratio(value: Any, label: str, optional: Literal[False] = False) -> float: ...


@overload
def _ratio(value: Any, label: str, optional: Literal[True]) -> float | None: ...


def _ratio(value: Any, label: str, optional: bool = False) -> float | None:
    if value is None and optional:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError(f"{label} must be a finite number between 0 and 1")
    return float(value)


def _column(value: Any) -> ColumnMetadata:
    obj = _object(
        value,
        {"name", "data_type", "nullable", "null_ratio", "cardinality", "provenance"},
        "column",
    )
    if obj.get("nullable") is not None and not isinstance(obj["nullable"], bool):
        raise TypeError("column nullable must be boolean or null")
    return ColumnMetadata(
        name=_text(obj.get("name"), "column.name"),
        data_type=_text(obj.get("data_type", "unknown"), "column.data_type"),
        nullable=obj.get("nullable"),
        null_ratio=_ratio(obj.get("null_ratio"), "null_ratio", optional=True),
        cardinality=_count(obj.get("cardinality"), "cardinality"),
        provenance=_text(obj.get("provenance"), "column.provenance", optional=True),
    )


def _table(value: Any) -> TableMetadata:
    obj = _object(
        value,
        {
            "name",
            "columns",
            "row_count",
            "grain",
            "primary_key_candidates",
            "provenance",
            "profile_rows",
            "profile_is_complete",
            "composite_key_candidates",
            "grain_evidence",
        },
        "table",
    )
    columns = tuple(_column(item) for item in _list(obj.get("columns"), "columns"))
    names = {column.name for column in columns}
    if len(names) != len(columns):
        raise ValueError("duplicate column names in producer metadata")
    rows = _list(obj.get("profile_rows", []), "profile_rows")
    for row in rows:
        _object(row, names, "profile row")
        for item in row.values():
            if not isinstance(item, (str, int, float, bool, type(None))) or (
                isinstance(item, float) and not math.isfinite(item)
            ):
                raise ValueError("profile values must be finite JSON scalars")
    complete = obj.get("profile_is_complete", False)
    if not isinstance(complete, bool):
        raise TypeError("profile_is_complete must be boolean")
    row_count = _count(obj.get("row_count"), "row_count")
    if complete and rows and row_count is not None and len(rows) != row_count:
        raise ValueError("complete profile rows do not match row_count")
    return TableMetadata(
        name=_text(obj.get("name"), "table.name"),
        columns=columns,
        row_count=row_count,
        grain=_text(obj.get("grain"), "grain", optional=True),
        primary_key_candidates=_strings(
            obj.get("primary_key_candidates", []), "primary_key_candidates"
        ),
        provenance=_text(obj.get("provenance"), "table.provenance", optional=True),
        profile_rows=tuple(rows),
        profile_is_complete=complete,
        composite_key_candidates=_pairs(
            obj.get("composite_key_candidates", []), "composite_key_candidates"
        ),
        grain_evidence=_strings(obj.get("grain_evidence", []), "grain_evidence"),
    )


def _relationship(value: Any) -> JoinEdge:
    obj = _object(
        value,
        {
            "left_table",
            "left_column",
            "right_table",
            "right_column",
            "cardinality",
            "confidence",
            "evidence",
            "additional_key_pairs",
        },
        "relationship",
    )
    cardinality = obj.get("cardinality", "unknown")
    if cardinality not in {
        "one_to_one",
        "one_to_many",
        "many_to_one",
        "many_to_many",
        "unknown",
    }:
        raise ValueError("unsupported relationship cardinality")
    pairs = _pairs(obj.get("additional_key_pairs", []), "additional_key_pairs")
    if any(len(pair) != 2 for pair in pairs):
        raise ValueError("additional_key_pairs must contain pairs of columns")
    return JoinEdge(
        left_table=_text(obj.get("left_table"), "left_table"),
        left_column=_text(obj.get("left_column"), "left_column"),
        right_table=_text(obj.get("right_table"), "right_table"),
        right_column=_text(obj.get("right_column"), "right_column"),
        cardinality=cardinality,
        status="candidate",
        confidence=_ratio(obj.get("confidence", 0.5), "confidence"),
        evidence=_strings(obj.get("evidence", []), "evidence"),
        additional_key_pairs=tuple((pair[0], pair[1]) for pair in pairs),
    )
