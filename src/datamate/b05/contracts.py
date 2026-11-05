"""Data contracts and schemas for B0.5 Basic Output Gate (DataMate 2026)."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AnswerType(str, Enum):
    NUMBER = "number"
    PERCENT = "percent"
    STRING = "string"
    DATE = "date"
    BOOLEAN = "boolean"
    LIST = "list"
    TABLE = "table"
    UNANSWERABLE = "unanswerable"
    ABSTAIN = "abstain"


class NumericKind(str, Enum):
    COUNT = "count"
    MONEY_VND = "money_vnd"
    AVERAGE_MONEY_VND = "average_money_vnd"
    AVERAGE_NONMONEY = "average_nonmoney"
    QUANTITY = "quantity"
    GENERIC = "generic"


class PercentUnit(str, Enum):
    PERCENT_POINTS = "percent_points"
    FRACTION = "fraction"


class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    NOT_EXECUTED = "not_executed"


class GateAction(str, Enum):
    FINAL = "FINAL"
    RETRY = "RETRY"


class Decision(str, Enum):
    ANSWER = "answer"
    UNANSWERABLE = "unanswerable"
    ABSTAIN = "abstain"
    RETRY = "retry"


@dataclass
class QuestionMeta:
    id: str
    business_id: str
    question: str
    as_of_date: str


@dataclass
class AnswerSemantics:
    numeric_kind: Optional[str] = None
    percent_unit: Optional[str] = None
    list_ordered: Optional[bool] = None
    time_role: Optional[str] = None
    empty_set_policy: Optional[str] = None


@dataclass
class GenerationResult:
    answer_type: str
    sql: str = ""
    tables_used: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    answer_semantics: AnswerSemantics = field(default_factory=AnswerSemantics)


@dataclass
class ExecutionErrorDetail:
    type: str
    message: str
    code: Optional[str] = None


@dataclass
class ExecutionResult:
    status: str
    columns: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    row_count: Optional[int] = None
    truncated: bool = False
    elapsed_ms: Optional[float] = None
    error: Optional[ExecutionErrorDetail] = None
    warnings: List[Any] = field(default_factory=list)


@dataclass
class EvidenceProof:
    capability_status: str = "unknown"
    coverage_status: str = "unknown"
    checked_all_sources: bool = False
    required_fields: List[str] = field(default_factory=list)
    available_fields: List[str] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)
    alternative_sources_checked: List[str] = field(default_factory=list)
    source_kind: str = "unverified"
    proof: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class GateRequest:
    contract_version: str
    question: QuestionMeta
    generation: Optional[GenerationResult]
    execution: ExecutionResult
    evidence: EvidenceProof = field(default_factory=EvidenceProof)
    attempt: int = 0
    trace: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RepairRequest:
    attempt: int
    failed_sql: str
    error_type: str
    error_message: str
    error_code: str
    schema_hint: Optional[str] = None
    available_columns: Optional[List[str]] = None
    do_not_change_question: bool = True
    instruction: str = "Fix the SQL error without changing question semantics."


@dataclass
class ValidationResult:
    passed: bool
    error_code: Optional[str] = None
    details: Optional[str] = None
    normalized_candidate: Any = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class FinalAnswer:
    id: str
    type: str
    answer: Any = None
    reason: Optional[str] = None

    def to_submission_dict(self) -> Dict[str, Any]:
        """Convert to official submission format (no extra metadata, strict type)."""
        if self.type == AnswerType.ABSTAIN:
            # abstain: id + type only, NO answer field
            return {"id": self.id, "type": "abstain"}
        elif self.type == AnswerType.UNANSWERABLE:
            # unanswerable: id + type, optional reason, NO answer field
            res: Dict[str, Any] = {"id": self.id, "type": "unanswerable"}
            if self.reason is not None and str(self.reason).strip():
                res["reason"] = str(self.reason).strip()
            return res
        else:
            return {"id": self.id, "type": self.type, "answer": self.answer}


@dataclass
class GateOutcome:
    action: str  # FINAL or RETRY
    question_id: str
    decision: str  # answer, unanswerable, abstain, retry
    final_answer: Optional[FinalAnswer] = None
    reason_code: str = ""
    validation: Dict[str, Any] = field(default_factory=lambda: {"passed": True, "errors": [], "warnings": []})
    retry_count: int = 0
    repair_request: Optional[RepairRequest] = None

