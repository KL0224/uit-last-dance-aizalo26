"""Data contracts for B0.1 Schema & Join Catalog (DataMate 2026)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ColumnMetadata:
    """Metadata for a single database/table column."""

    name: str
    data_type: str = "unknown"
    nullable: bool | None = None
    null_ratio: float | None = None
    cardinality: int | None = None
    provenance: str | None = None


@dataclass(frozen=True)
class TableMetadata:
    """Metadata for a discovered table including candidate keys and grain evidence."""

    name: str
    columns: tuple[ColumnMetadata, ...]
    row_count: int | None = None
    grain: str | None = None
    primary_key_candidates: tuple[str, ...] = ()
    provenance: str | None = None
    # Rows may be supplied by a trusted Data Foundation profiler for key checks.
    profile_rows: tuple[dict[str, Any], ...] = field(default=(), repr=False)
    profile_is_complete: bool = False
    composite_key_candidates: tuple[tuple[str, ...], ...] = ()
    grain_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class KeyCandidate:
    """Candidate primary key or composite key identity for a table."""

    table: str
    columns: tuple[str, ...]
    key_type: str
    status: str
    confidence: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class JoinEdge:
    """Directed/undirected join edge between tables with single or composite key components."""

    left_table: str
    left_column: str
    right_table: str
    right_column: str
    cardinality: str
    status: str
    confidence: float
    evidence: tuple[str, ...]
    fanout_warning: bool = False
    additional_key_pairs: tuple[tuple[str, str], ...] = ()

    @property
    def key_pairs(self) -> tuple[tuple[str, str], ...]:
        """Ordered column pairs; the first pair preserves the single-key API."""
        return ((self.left_column, self.right_column),) + self.additional_key_pairs


@dataclass(frozen=True)
class SchemaCatalog:
    """Unified schema catalog containing all discovered tables, candidate keys, and join graph."""

    tables: tuple[TableMetadata, ...]
    key_candidates: tuple[KeyCandidate, ...] = ()
    join_graph: tuple[JoinEdge, ...] = ()
    warnings: tuple[str, ...] = ()

