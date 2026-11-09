"""Evidence-Based Answerability Decision Engine for B0.5 Basic Output Gate."""

from typing import Optional, Tuple

from .contracts import CapabilityStatus, GateRequest
from .risk_policy import capability_proof_complete


def evaluate_answerability(request: GateRequest) -> Tuple[bool, Optional[str]]:
    """Determine whether the question is proven unanswerable based on trusted evidence.
    
    Returns:
        (is_unanswerable: bool, reason: Optional[str])
    """
    if request.contract_version == "b05.v2":
        proof = request.capability_proof
        if proof.status != CapabilityStatus.UNSUPPORTED or not capability_proof_complete(request):
            return False, None
        requirements = ", ".join(sorted(proof.missing_requirement_ids))
        capabilities = ", ".join(sorted(proof.capability_ids))
        return True, f"Unsupported capability {capabilities}; missing requirements: {requirements}"

    evidence = request.evidence

    # Reject unverified self-claims from LLM
    if evidence.source_kind != "catalog_verified":
        return False, None

    # Must be confirmed unsupported capability
    if evidence.capability_status != "unsupported":
        return False, None

    # Must have verified all alternative and primary sources
    if not evidence.checked_all_sources:
        return False, None

    # Must have documented missing fields or verification proofs
    if not evidence.missing_fields and not evidence.proof:
        return False, None

    # Format human-readable evidence-based reason
    if evidence.missing_fields:
        missing_str = ", ".join(evidence.missing_fields)
        reason = f"Dữ liệu được kiểm chứng thiếu các trường thông tin: {missing_str}"
    else:
        reason = "Dữ liệu được kiểm chứng không hỗ trợ chỉ số theo yêu cầu câu hỏi"

    return True, reason
