"""Data contracts and schemas for Component C: Question Grounding (DataMate 2026)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class OperationKind(str, Enum):
    """Primary analytical operation requested by the Vietnamese question."""

    SUM = "sum"
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    AVG = "avg"
    ARGMAX = "argmax"
    ARGMIN = "argmin"
    TOP_K = "top_k"
    PERCENT_CHANGE = "percent_change"
    RATIO = "ratio"
    COMPARISON = "comparison"
    LOOKUP = "lookup"
    EXISTENCE = "existence"
    TABLE_REPORT = "table_report"


class AnswerTypeHint(str, Enum):
    """Expected answer type hints matching the competition's output types."""

    NUMBER = "number"
    PERCENT = "percent"
    STRING = "string"
    DATE = "date"
    BOOLEAN = "boolean"
    LIST = "list"
    TABLE = "table"
    UNANSWERABLE = "unanswerable"
    ABSTAIN = "abstain"


class CoverageStatus(str, Enum):
    """Evidence and capability coverage status evaluated by C5 Precheck."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class DateRole(str, Enum):
    """Semantic role of a temporal column in business operations."""

    ORDER_DATE = "order_date"
    PAYMENT_DATE = "payment_date"
    STOCK_EVENT_DATE = "stock_event_date"
    EXPIRY_DATE = "expiry_date"
    GENERIC_DATE = "generic_date"


@dataclass(frozen=True)
class QuestionRequest:
    """Normalized incoming question request with anchor as_of_date."""

    question_id: str
    business_id: str
    question: str
    as_of_date: str

    def __post_init__(self) -> None:
        q_id = self.question_id.strip()
        b_id = self.business_id.strip()
        q_text = self.question.strip()
        a_date = self.as_of_date.strip()

        if not q_id:
            raise ValueError("question_id must be non-empty")
        if not b_id:
            raise ValueError("business_id must be non-empty")
        if not q_text:
            raise ValueError("question must be non-empty")
        try:
            date.fromisoformat(a_date)
        except ValueError as exc:
            raise ValueError(f"as_of_date must be valid ISO YYYY-MM-DD, got {a_date!r}") from exc

        object.__setattr__(self, "question_id", q_id)
        object.__setattr__(self, "business_id", b_id)
        object.__setattr__(self, "question", q_text)
        object.__setattr__(self, "as_of_date", a_date)


@dataclass(frozen=True)
class FilterCondition:
    """A filter condition extracted from the question before/after value grounding."""

    field_hint: str
    operator: str
    raw_value: Any
    grounded_column: str | None = None
    grounded_value: Any | None = None
    is_having: bool = False


@dataclass(frozen=True)
class QuestionIntent:
    """Structured semantic representation of the user's question (C1 output)."""

    operation: OperationKind
    target_metrics: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    filters: tuple[FilterCondition, ...] = ()
    group_by: tuple[str, ...] = ()
    top_k: int | None = None
    sort_order: str = "desc"
    tie_break_rule: str = "entity_asc"
    answer_type_hint: AnswerTypeHint = AnswerTypeHint.NUMBER
    confidence: float = 1.0
    used_llm_fallback: bool = False
    fallback_reasons: tuple[str, ...] = ()
    normalized_question: str | None = None


@dataclass(frozen=True)
class ResolvedTimeRange:
    """Deterministic date range resolved from relative expressions and as_of_date (C2 output)."""

    raw_expression: str
    start_date: str
    end_date: str
    date_role: DateRole = DateRole.ORDER_DATE
    inclusive: bool = True
    comparison_start_date: str | None = None
    comparison_end_date: str | None = None
    interpretation: str = ""

    def __post_init__(self) -> None:
        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        if start > end:
            raise ValueError(
                f"start_date ({self.start_date}) must not be after end_date ({self.end_date})"
            )
        if self.comparison_start_date and self.comparison_end_date:
            c_start = date.fromisoformat(self.comparison_start_date)
            c_end = date.fromisoformat(self.comparison_end_date)
            if c_start > c_end:
                raise ValueError(
                    "comparison_start_date must not be after comparison_end_date"
                )


@dataclass(frozen=True)
class SchemaCandidate:
    """A candidate table and its relevant columns ranked by C3 Schema Grounder."""

    table_name: str
    relevant_columns: tuple[str, ...]
    grain: str | None = None
    score: float = 0.0
    rationale: str = ""


@dataclass(frozen=True)
class CandidateJoinPath:
    """A validated join path between two tables from the Join Graph."""

    left_table: str
    left_column: str
    right_table: str
    right_column: str
    cardinality: str = "many_to_one"
    fanout_warning: bool = False
    confidence: float = 1.0
    additional_key_pairs: tuple[tuple[str, str], ...] = ()
    null_key_warning: bool = False

    @property
    def key_pairs(self) -> tuple[tuple[str, str], ...]:
        """Return all (left_column, right_column) pairs in deterministic order."""
        return ((self.left_column, self.right_column),) + self.additional_key_pairs


@dataclass(frozen=True)
class SelectedSchema:
    """Selected tables, columns, and safe join paths for the Planner (C3 output)."""

    primary_table: str | None
    tables: tuple[SchemaCandidate, ...] = ()
    join_paths: tuple[CandidateJoinPath, ...] = ()
    fanout_warning: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchedValue:
    """Grounded database value linked from an entity or filter phrase (C4 output)."""

    raw_text: str
    table_name: str
    column_name: str
    matched_db_value: Any
    match_type: str = "exact"
    confidence: float = 1.0


@dataclass(frozen=True)
class EvidenceRequirement:
    """Required capability or domain concept needed to answer the question."""

    capability_key: str
    required_concepts: tuple[str, ...] = ()
    is_mandatory: bool = True


@dataclass(frozen=True)
class MissingEvidenceProof:
    """Catalog-verified proof of missing evidence when a question is UNSUPPORTED (C5 output)."""

    capability_key: str
    missing_fields: tuple[str, ...]
    checked_tables: tuple[str, ...]
    checked_all_sources: bool = True
    reason: str = ""


@dataclass(frozen=True)
class GroundedQuestion:
    """Deliverable contract of Component C passed to Component D (Planner) and G (Gate)."""

    question_id: str
    business_id: str
    question: str
    as_of_date: str
    intent: QuestionIntent
    resolved_time_ranges: tuple[ResolvedTimeRange, ...]
    selected_schema: SelectedSchema
    matched_values: tuple[MatchedValue, ...]
    answer_type_hint: AnswerTypeHint
    evidence_requirements: tuple[EvidenceRequirement, ...]
    coverage_status: CoverageStatus
    missing_evidence_proof: MissingEvidenceProof | None = None
    applicable_rules: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()

    @property
    def is_directly_unanswerable(self) -> bool:
        """Return True only when C5 proved that mandatory evidence is unsupported."""
        return (
            self.coverage_status == CoverageStatus.UNSUPPORTED
            and self.missing_evidence_proof is not None
            and self.missing_evidence_proof.checked_all_sources
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize GroundedQuestion to a plain JSON-compatible dictionary."""
        return asdict(self)


__all__ = [
    "OperationKind",
    "AnswerTypeHint",
    "CoverageStatus",
    "DateRole",
    "QuestionRequest",
    "FilterCondition",
    "QuestionIntent",
    "ResolvedTimeRange",
    "SchemaCandidate",
    "CandidateJoinPath",
    "SelectedSchema",
    "MatchedValue",
    "EvidenceRequirement",
    "MissingEvidenceProof",
    "GroundedQuestion",
]
