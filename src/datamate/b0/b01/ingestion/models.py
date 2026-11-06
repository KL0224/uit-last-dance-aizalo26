"""Contracts for immutable source discovery and prepared artifact bundles."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PARSER_VERSION = "1.0.0"


@dataclass(frozen=True)
class PreparationConfig:
    memory_limit: str = "512MB"
    threads: int = 2
    batch_size: int = 10_000
    source_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.memory_limit or self.threads < 1 or self.batch_size < 1:
            raise ValueError("memory_limit, threads and batch_size must be positive")
        allowed = {"header_row", "encoding", "delimiter", "roles", "logical_table"}
        for override in self.source_overrides.values():
            if not isinstance(override, dict) or set(override) - allowed:
                raise ValueError("unsupported source override")
            if "header_row" in override and (
                not isinstance(override["header_row"], int)
                or override["header_row"] < 1
            ):
                raise ValueError("header_row is one-based and must be positive")


@dataclass(frozen=True)
class SourceTable:
    path: Path
    relative_path: str
    source_id: str
    sheet: str | None
    headers: tuple[str, ...]
    header_row: int
    end_row: int | None = None
    encoding: str = "utf-8-sig"
    delimiter: str = ","
    epoch: str = "1900"
    year: int | None = None
    logical_family: str = ""
    sqlite_types: tuple[str, ...] = ()
    sqlite_foreign_keys: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class SourceRow:
    number: int
    values: tuple[Any, ...]
    formulas: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedBusinessArtifacts:
    business_id: str
    cache_key: str
    bundle_dir: Path
    status: str
    cache_hit: bool
    quality_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "business_id": self.business_id,
            "cache_key": self.cache_key,
            "bundle_dir": str(self.bundle_dir),
            "database": str(self.bundle_dir / "data.duckdb"),
            "status": self.status,
            "cache_hit": self.cache_hit,
            "quality_summary": self.quality_summary,
        }


class PreparationError(ValueError):
    """A preparation failed; its diagnostic bundle is retained separately."""
