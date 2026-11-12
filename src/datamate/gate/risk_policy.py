"""Deterministic release policy for B0.5 v2 proof contracts."""

from .contracts import (
    AnswerType,
    CapabilityStatus,
    GateRequest,
    ProofStatus,
    ReleaseStatus,
    RiskAssessment,
)
from .errors import ErrorCode


POLICY_VERSION = "b05-risk.v1"


def capability_proof_complete(request: GateRequest) -> bool:
    """Return whether the capability proof carries catalog provenance."""
    proof = request.capability_proof
    base = bool(
        proof.capability_ids
        and proof.checked_source_ids
        and proof.catalog_version
        and proof.proof_hash
        and not proof.conflicts
    )
    if proof.status == CapabilityStatus.UNSUPPORTED:
        return base and bool(proof.missing_requirement_ids)
    return base


def repair_invariants_changed(request: GateRequest) -> bool:
    if request.attempt == 0:
        return False
    origin = request.repair_origin
    generation = request.generation
    if origin is None or generation is None:
        return True
    return (
        origin.plan_id != generation.plan_id
        or origin.metric_id != generation.metric_id
        or origin.expected_answer_type != generation.expected_answer_type
    )


def assess_risk(request: GateRequest) -> RiskAssessment:
    """Assess v2 release risk without consulting GT, IDs, or model confidence."""
    failures: list[str] = []
    warnings: list[str] = []
    generation = request.generation

    if generation is None:
        failures.append(ErrorCode.CONTRACT_ERROR)
    elif generation.answer_type != generation.expected_answer_type:
        failures.append(ErrorCode.ANSWER_TYPE_MISMATCH)

    if repair_invariants_changed(request):
        failures.append(ErrorCode.REPAIR_SEMANTICS_CHANGED)

    capability = request.capability_proof
    capability_complete = capability_proof_complete(request)
    is_unanswerable = bool(generation and generation.expected_answer_type == AnswerType.UNANSWERABLE)

    if capability.status == CapabilityStatus.UNKNOWN:
        warnings.append(ErrorCode.CAPABILITY_PROOF_MISSING)
    elif not capability_complete:
        failures.append(ErrorCode.CAPABILITY_PROOF_INVALID)
    elif is_unanswerable and capability.status != CapabilityStatus.UNSUPPORTED:
        failures.append(ErrorCode.CAPABILITY_PROOF_INVALID)
    elif not is_unanswerable and capability.status != CapabilityStatus.SUPPORTED:
        failures.append(ErrorCode.CAPABILITY_PROOF_INVALID)

    if not is_unanswerable:
        semantic = request.semantic_proof
        if semantic.status == ProofStatus.UNKNOWN:
            warnings.append(ErrorCode.SEMANTIC_PROOF_MISSING)
        elif semantic.status == ProofStatus.FAIL:
            failures.append(ErrorCode.SEMANTIC_PROOF_FAILED)
        elif not (
            semantic.plan_id == (generation.plan_id if generation else None)
            and semantic.checks
            and semantic.schema_version
            and semantic.rule_version
            and all(check.status == ProofStatus.PASS for check in semantic.checks)
        ):
            failures.append(ErrorCode.SEMANTIC_PROOF_FAILED)

    status = ReleaseStatus.SAFE
    if failures:
        status = ReleaseStatus.UNSAFE
    elif warnings:
        status = ReleaseStatus.UNKNOWN

    return RiskAssessment(
        policy_version=POLICY_VERSION,
        policy_mode=request.policy_mode,
        hard_failures=failures,
        warnings=warnings,
        release_status=status,
    )


def blocking_reason(risk: RiskAssessment) -> str:
    if risk.hard_failures:
        return risk.hard_failures[0]
    if risk.warnings:
        return risk.warnings[-1]
    return ErrorCode.RISK_NOT_RELEASED
