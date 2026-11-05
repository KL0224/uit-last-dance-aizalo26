"""Adapters for B0.5 Basic Output Gate input contracts."""

import datetime
import re
from typing import Any, Dict, List, Optional

from .contracts import (
    AnswerSemantics,
    AnswerType,
    EvidenceProof,
    ExecutionErrorDetail,
    ExecutionResult,
    ExecutionStatus,
    GateRequest,
    GenerationResult,
    QuestionMeta,
)
from .errors import ContractError


def _validate_iso_date(date_str: str) -> str:
    """Validate strict calendar date YYYY-MM-DD."""
    if not isinstance(date_str, str):
        raise ContractError(f"as_of_date must be a string, got {type(date_str).__name__}")
    s = date_str.strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        raise ContractError(f"as_of_date '{s}' must follow ISO YYYY-MM-DD")
    try:
        datetime.date.fromisoformat(s)
        return s
    except ValueError as exc:
        raise ContractError(f"as_of_date '{s}' is not a valid calendar date: {exc}")


def adapt_generation(raw: Optional[Dict[str, Any]]) -> Optional[GenerationResult]:
    """Adapt generation dictionary into GenerationResult."""
    if raw is None:
        return None

    answer_type_str = raw.get("answer_type")
    valid_types = [t.value for t in AnswerType]
    if answer_type_str not in valid_types:
        raise ContractError(f"Invalid answer_type '{answer_type_str}'. Must be one of {valid_types}")

    semantics_raw = raw.get("answer_semantics") or {}
    semantics = AnswerSemantics(
        numeric_kind=semantics_raw.get("numeric_kind"),
        percent_unit=semantics_raw.get("percent_unit"),
        list_ordered=semantics_raw.get("list_ordered"),
        time_role=semantics_raw.get("time_role"),
        empty_set_policy=semantics_raw.get("empty_set_policy"),
    )

    return GenerationResult(
        answer_type=answer_type_str,
        sql=str(raw.get("sql") or ""),
        tables_used=list(raw.get("tables_used") or []),
        assumptions=list(raw.get("assumptions") or []),
        answer_semantics=semantics,
    )


def adapt_execution(raw: Optional[Dict[str, Any]]) -> ExecutionResult:
    """Adapt execution dictionary into ExecutionResult."""
    if raw is None:
        return ExecutionResult(status=ExecutionStatus.NOT_EXECUTED)

    status_str = raw.get("status")
    valid_statuses = [s.value for s in ExecutionStatus]
    if status_str not in valid_statuses:
        raise ContractError(f"Invalid execution status '{status_str}'. Must be one of {valid_statuses}")

    error_raw = raw.get("error")
    error_detail = None
    if isinstance(error_raw, dict):
        error_detail = ExecutionErrorDetail(
            type=str(error_raw.get("type") or "UnknownError"),
            message=str(error_raw.get("message") or ""),
            code=error_raw.get("code"),
        )
    elif error_raw is not None:
        error_detail = ExecutionErrorDetail(
            type="ExecutionError",
            message=str(error_raw),
        )

    rows = raw.get("rows")
    if rows is None:
        rows = []
    elif not isinstance(rows, list):
        raise ContractError("execution.rows must be a list of rows")

    columns = raw.get("columns")
    if columns is None:
        columns = []
    elif not isinstance(columns, list):
        raise ContractError("execution.columns must be a list of column names")

    return ExecutionResult(
        status=status_str,
        columns=[str(c) for c in columns],
        rows=rows,
        row_count=raw.get("row_count"),
        truncated=bool(raw.get("truncated", False)),
        elapsed_ms=raw.get("elapsed_ms"),
        error=error_detail,
        warnings=list(raw.get("warnings") or []),
    )


def adapt_evidence(raw: Optional[Dict[str, Any]]) -> EvidenceProof:
    """Adapt evidence dictionary into EvidenceProof."""
    if not isinstance(raw, dict):
        return EvidenceProof()

    return EvidenceProof(
        capability_status=str(raw.get("capability_status") or "unknown"),
        coverage_status=str(raw.get("coverage_status") or "unknown"),
        checked_all_sources=bool(raw.get("checked_all_sources", False)),
        required_fields=list(raw.get("required_fields") or []),
        available_fields=list(raw.get("available_fields") or []),
        missing_fields=list(raw.get("missing_fields") or []),
        alternative_sources_checked=list(raw.get("alternative_sources_checked") or []),
        source_kind=str(raw.get("source_kind") or "unverified"),
        proof=list(raw.get("proof") or []),
    )


def adapt_gate_request(raw: Dict[str, Any]) -> GateRequest:
    """Parse and strictly validate a raw request dictionary into GateRequest."""
    if not isinstance(raw, dict):
        raise ContractError("Request payload must be a JSON object / dictionary")

    version = raw.get("contract_version")
    if version != "b05.v1":
        raise ContractError(f"Unsupported contract_version '{version}'. Expected 'b05.v1'")

    q_raw = raw.get("question")
    if not isinstance(q_raw, dict):
        raise ContractError("Field 'question' is required and must be an object")

    q_id = str(q_raw.get("id") or "").strip()
    if not q_id:
        raise ContractError("question.id must be a non-empty string")

    business_id = str(q_raw.get("business_id") or "").strip()
    question_text = str(q_raw.get("question") or "")
    as_of_date = _validate_iso_date(q_raw.get("as_of_date"))

    question_meta = QuestionMeta(
        id=q_id,
        business_id=business_id,
        question=question_text,
        as_of_date=as_of_date,
    )

    generation = adapt_generation(raw.get("generation"))
    execution = adapt_execution(raw.get("execution"))
    evidence = adapt_evidence(raw.get("evidence"))

    attempt = raw.get("attempt", 0)
    if attempt not in (0, 1):
        raise ContractError(f"Field 'attempt' must be 0 or 1, got {attempt}")

    trace = raw.get("trace") or {}

    return GateRequest(
        contract_version=version,
        question=question_meta,
        generation=generation,
        execution=execution,
        evidence=evidence,
        attempt=attempt,
        trace=trace,
    )

