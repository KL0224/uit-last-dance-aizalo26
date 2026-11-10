"""Protocols decoupling Component C (Question Grounding) from B0.1/B0.2 and LLM backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

from .contracts import QuestionIntent


@dataclass(frozen=True)
class ColumnSpec:
    """Lightweight column metadata descriptor for grounding."""

    name: str
    data_type: str = "unknown"
    description: str = ""
    aliases: tuple[str, ...] = ()
    sample_values: tuple[Any, ...] = ()
    role: str = ""  # e.g., 'id', 'date', 'money', 'quantity', 'category', 'name', 'text'
    null_ratio: float = 0.0


@dataclass(frozen=True)
class TableSpec:
    """Lightweight table metadata descriptor for grounding."""

    name: str
    columns: tuple[ColumnSpec, ...]
    grain: str = "unknown"
    description: str = ""
    aliases: tuple[str, ...] = ()
    row_count: int = 0
    date_coverage_start: str | None = None
    date_coverage_end: str | None = None


@dataclass(frozen=True)
class JoinSpec:
    """Join edge specification between two tables."""

    left_table: str
    left_column: str
    right_table: str
    right_column: str
    cardinality: str = "many_to_one"
    fanout_warning: bool = False
    confidence: float = 1.0


@dataclass(frozen=True)
class MetricSpec:
    """Semantic metric contract from B3 Metric Registry."""

    metric_id: str
    aliases: tuple[str, ...]
    preferred_table: str
    required_columns: tuple[str, ...]
    date_role: str = "order_date"
    formula_hint: str = ""
    unit: str = "number"


@dataclass(frozen=True)
class CalendarEventSpec:
    """Named temporal period or holiday (e.g., Lunar New Year / Tết)."""

    event_key: str
    aliases: tuple[str, ...]
    year: int
    start_date: str
    end_date: str


@runtime_checkable
class BusinessContextProtocol(Protocol):
    """Protocol that any BusinessContext (mock or B0.2 adapter) must satisfy."""

    business_id: str

    def get_tables(self) -> Sequence[TableSpec]:
        """Return all discovered tables and their column descriptors."""
        ...

    def get_join_edges(self) -> Sequence[JoinSpec]:
        """Return all validated join graph edges."""
        ...

    def get_metrics(self) -> Sequence[MetricSpec]:
        """Return registered business metrics and their required schema bindings."""
        ...

    def get_capability_status(self, capability_key: str) -> str:
        """Return 'supported', 'unsupported', or 'unknown' for a business capability."""
        ...

    def get_calendar_events(self) -> Sequence[CalendarEventSpec]:
        """Return calendar events (such as Tết, holidays) for temporal resolution."""
        ...

    def get_active_rules(self, topic: str | None = None) -> Sequence[str]:
        """Return active business rules ordered by precedence."""
        ...

    def get_value_aliases(self) -> dict[str, tuple[str, str, Any]]:
        """Return mapping of normalized alias phrase -> (table_name, column_name, db_value)."""
        ...


@runtime_checkable
class LLMParserProtocol(Protocol):
    """Protocol for the 3B Semantic Extractor fallback (e.g., Qwen2.5-3B-Instruct)."""

    def extract_intent(
        self,
        question: str,
        as_of_date: str,
        available_metrics: Sequence[str],
        available_tables: Sequence[str],
    ) -> QuestionIntent:
        """Parse a complex Vietnamese question into a structured QuestionIntent."""
        ...


__all__ = [
    "ColumnSpec",
    "TableSpec",
    "JoinSpec",
    "MetricSpec",
    "CalendarEventSpec",
    "BusinessContextProtocol",
    "LLMParserProtocol",
]
