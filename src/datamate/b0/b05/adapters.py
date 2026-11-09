"""Adapters for B0.5 Basic Output Gate input contracts."""

import datetime
import re
from typing import Any, Dict, List, Optional

from .contracts import (
    AnswerSemantics,
    AnswerType,
    CapabilityProof,
    CapabilityStatus,
    EvidenceProof,
    ExecutionErrorDetail,
    ExecutionResult,
    ExecutionStatus,
    GateRequest,
    GenerationResult,
    PolicyMode,
    ProofStatus,
    QuestionMeta,
    RepairOrigin,
    SemanticCheck,
    SemanticProof,
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


def _enum_value(value: Any, enum_cls: Any, field_name: str) -> str:
    if isinstance(value, enum_cls):
        return value.value
    valid = [item.value for item in enum_cls]
    if value not in valid:
        raise ContractError(f"Invalid {field_name} '{value}'. Must be one of {valid}")
    return str(value)


def _required_text(raw: Dict[str, Any], field_name: str) -> str:
    value = str(raw.get(field_name) or "").strip()
    if not value:
        raise ContractError(f"{field_name} must be a non-empty string")
    return value


def adapt_generation(raw: Optional[Dict[str, Any]], *, version: str = "b05.v1") -> Optional[GenerationResult]:
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

    plan_id = raw.get("plan_id")
    metric_id = raw.get("metric_id")
    expected_answer_type = raw.get("expected_answer_type")
    if version == "b05.v2":
        plan_id = _required_text(raw, "plan_id")
        metric_id = _required_text(raw, "metric_id")
        expected_answer_type = _enum_value(expected_answer_type, AnswerType, "expected_answer_type")

    return GenerationResult(
        answer_type=answer_type_str,
        sql=str(raw.get("sql") or ""),
        tables_used=list(raw.get("tables_used") or []),
        assumptions=list(raw.get("assumptions") or []),
        answer_semantics=semantics,
        plan_id=str(plan_id).strip() if plan_id is not None else None,
        metric_id=str(metric_id).strip() if metric_id is not None else None,
        expected_answer_type=str(expected_answer_type) if expected_answer_type is not None else None,
    )


def adapt_capability_proof(raw: Optional[Dict[str, Any]]) -> CapabilityProof:
    if raw is None:
        return CapabilityProof()
    if not isinstance(raw, dict):
        raise ContractError("capability_proof must be an object")
    status = _enum_value(raw.get("status", "unknown"), CapabilityStatus, "capability_proof.status")
    proof = CapabilityProof(
        status=status,
        capability_ids=[str(v) for v in raw.get("capability_ids") or []],
        missing_requirement_ids=[str(v) for v in raw.get("missing_requirement_ids") or []],
        checked_source_ids=[str(v) for v in raw.get("checked_source_ids") or []],
        catalog_version=str(raw["catalog_version"]) if raw.get("catalog_version") else None,
        proof_hash=str(raw["proof_hash"]) if raw.get("proof_hash") else None,
        conflicts=[str(v) for v in raw.get("conflicts") or []],
    )
    if proof.status != CapabilityStatus.UNKNOWN:
        required = {
            "capability_ids": proof.capability_ids,
            "checked_source_ids": proof.checked_source_ids,
            "catalog_version": proof.catalog_version,
            "proof_hash": proof.proof_hash,
        }
        for field_name, value in required.items():
            if not value:
                raise ContractError(f"capability_proof.{field_name} is required for status '{proof.status}'")
        if proof.status == CapabilityStatus.UNSUPPORTED and not proof.missing_requirement_ids:
            raise ContractError("capability_proof.missing_requirement_ids is required for unsupported status")
    return proof


def adapt_semantic_proof(raw: Optional[Dict[str, Any]]) -> SemanticProof:
    if raw is None:
        return SemanticProof()
    if not isinstance(raw, dict):
        raise ContractError("semantic_proof must be an object")
    status = _enum_value(raw.get("status", "unknown"), ProofStatus, "semantic_proof.status")
    checks: List[SemanticCheck] = []
    for index, check in enumerate(raw.get("checks") or []):
        if not isinstance(check, dict):
            raise ContractError(f"semantic_proof.checks[{index}] must be an object")
        checks.append(
            SemanticCheck(
                check_id=_required_text(check, "check_id"),
                status=_enum_value(check.get("status"), ProofStatus, f"semantic_proof.checks[{index}].status"),
                source_id=_required_text(check, "source_id"),
                details=str(check["details"]) if check.get("details") is not None else None,
            )
        )
    proof = SemanticProof(
        status=status,
        plan_id=str(raw["plan_id"]).strip() if raw.get("plan_id") else None,
        checks=checks,
        schema_version=str(raw["schema_version"]) if raw.get("schema_version") else None,
        rule_version=str(raw["rule_version"]) if raw.get("rule_version") else None,
    )
    if proof.status != ProofStatus.UNKNOWN:
        required = {
            "plan_id": proof.plan_id,
            "checks": proof.checks,
            "schema_version": proof.schema_version,
            "rule_version": proof.rule_version,
        }
        for field_name, value in required.items():
            if not value:
                raise ContractError(f"semantic_proof.{field_name} is required for status '{proof.status}'")
    if proof.status == ProofStatus.PASS and any(check.status != ProofStatus.PASS for check in proof.checks):
        raise ContractError("semantic_proof.status pass cannot contain a non-pass check")
    return proof


def adapt_repair_origin(raw: Optional[Dict[str, Any]]) -> Optional[RepairOrigin]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ContractError("repair_origin must be an object")
    return RepairOrigin(
        plan_id=_required_text(raw, "plan_id"),
        metric_id=_required_text(raw, "metric_id"),
        expected_answer_type=_enum_value(raw.get("expected_answer_type"), AnswerType, "repair_origin.expected_answer_type"),
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
    if version not in ("b05.v1", "b05.v2"):
        raise ContractError(f"Unsupported contract_version '{version}'. Expected 'b05.v1' or 'b05.v2'")

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

    generation = adapt_generation(raw.get("generation"), version=version)
    execution = adapt_execution(raw.get("execution"))
    evidence = adapt_evidence(raw.get("evidence"))
    capability_proof = adapt_capability_proof(raw.get("capability_proof"))
    semantic_proof = adapt_semantic_proof(raw.get("semantic_proof"))

    attempt = raw.get("attempt", 0)
    if attempt not in (0, 1):
        raise ContractError(f"Field 'attempt' must be 0 or 1, got {attempt}")

    trace = raw.get("trace") or {}
    if not isinstance(trace, dict):
        raise ContractError("trace must be an object")
    policy_mode = PolicyMode.LEGACY
    repair_origin = None
    if version == "b05.v2":
        policy_mode = _enum_value(raw.get("policy_mode", PolicyMode.SHADOW), PolicyMode, "policy_mode")
        repair_origin = adapt_repair_origin(raw.get("repair_origin"))

    return GateRequest(
        contract_version=version,
        question=question_meta,
        generation=generation,
        execution=execution,
        evidence=evidence,
        capability_proof=capability_proof,
        semantic_proof=semantic_proof,
        policy_mode=policy_mode,
        repair_origin=repair_origin,
        attempt=attempt,
        trace=trace,
    )
