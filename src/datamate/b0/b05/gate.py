"""Main Evaluation Engine for B0.5 Basic Output Gate (DataMate 2026)."""

import copy
from typing import Any, Dict

from .answerability import evaluate_answerability
from .contracts import (
    AnswerType,
    Decision,
    FinalAnswer,
    GateAction,
    GateOutcome,
    GateRequest,
    PolicyMode,
    ReleaseStatus,
)
from .errors import ErrorCode, FormattingError
from .formatter import format_answer
from .retry import classify_error, decide_retry
from .risk_policy import assess_risk, blocking_reason
from .validators import validate_execution


def evaluate_gate(request: GateRequest) -> GateOutcome:
    """Evaluate v1 in legacy mode and v2 in shadow or enforce mode."""
    if request.contract_version == "b05.v1" or request.policy_mode == PolicyMode.LEGACY:
        return _evaluate_legacy(request)

    if request.policy_mode == PolicyMode.SHADOW:
        legacy_request = copy.deepcopy(request)
        legacy_request.contract_version = "b05.v1"
        legacy_request.policy_mode = PolicyMode.LEGACY
        legacy = _evaluate_legacy(legacy_request)
        counterfactual = _evaluate_v2(request)
        legacy.risk_assessment = counterfactual.risk_assessment
        legacy.legacy_decision = legacy.decision
        legacy.shadow_decision = counterfactual.decision
        legacy.shadow_reason_code = counterfactual.reason_code
        return legacy

    return _evaluate_v2(request)


def _abstain(request: GateRequest, reason_code: str, risk=None) -> GateOutcome:
    return GateOutcome(
        action=GateAction.FINAL,
        question_id=request.question.id,
        decision=Decision.ABSTAIN,
        final_answer=FinalAnswer(id=request.question.id, type=AnswerType.ABSTAIN),
        reason_code=reason_code,
        validation={"passed": False, "errors": [reason_code], "warnings": []},
        retry_count=request.attempt,
        risk_assessment=risk,
    )


def _retry_or_abstain(request: GateRequest, error_code: str, warnings=None, risk=None) -> GateOutcome:
    classification = classify_error(request.execution.error, error_code)
    repair = decide_retry(request, classification)
    if repair is None:
        reason = ErrorCode.RETRY_EXHAUSTED if request.attempt >= 1 else error_code
        return _abstain(request, reason, risk)
    return GateOutcome(
        action=GateAction.RETRY,
        question_id=request.question.id,
        decision=Decision.RETRY,
        reason_code=error_code,
        validation={"passed": False, "errors": [error_code], "warnings": warnings or []},
        retry_count=request.attempt,
        repair_request=repair,
        risk_assessment=risk,
    )


def _evaluate_v2(request: GateRequest) -> GateOutcome:
    risk = assess_risk(request)
    reason = blocking_reason(risk)

    if ErrorCode.REPAIR_SEMANTICS_CHANGED in risk.hard_failures:
        return _abstain(request, ErrorCode.REPAIR_SEMANTICS_CHANGED, risk)

    if ErrorCode.ANSWER_TYPE_MISMATCH in risk.hard_failures:
        return _retry_or_abstain(request, ErrorCode.ANSWER_TYPE_MISMATCH, risk=risk)

    is_unanswerable, ua_reason = evaluate_answerability(request)
    if is_unanswerable and risk.release_status == ReleaseStatus.SAFE:
        return GateOutcome(
            action=GateAction.FINAL,
            question_id=request.question.id,
            decision=Decision.UNANSWERABLE,
            final_answer=FinalAnswer(
                id=request.question.id,
                type=AnswerType.UNANSWERABLE,
                reason=ua_reason,
            ),
            reason_code=ErrorCode.CONFIRMED_MISSING_EVIDENCE,
            validation={"passed": True, "errors": [], "warnings": []},
            retry_count=request.attempt,
            risk_assessment=risk,
        )

    if request.generation and request.generation.expected_answer_type == AnswerType.UNANSWERABLE:
        return _abstain(request, reason, risk)

    if risk.release_status != ReleaseStatus.SAFE:
        if ErrorCode.SEMANTIC_PROOF_FAILED in risk.hard_failures:
            return _retry_or_abstain(request, ErrorCode.SEMANTIC_PROOF_FAILED, risk=risk)
        return _abstain(request, reason, risk)

    validation = validate_execution(request)
    if not validation.passed:
        return _retry_or_abstain(
            request,
            classify_error(request.execution.error, validation.error_code).code,
            validation.warnings,
            risk,
        )

    generation = request.generation
    assert generation is not None  # risk policy rejects missing generation
    semantics = {
        "numeric_kind": generation.answer_semantics.numeric_kind,
        "percent_unit": generation.answer_semantics.percent_unit,
        "list_ordered": generation.answer_semantics.list_ordered,
        "time_role": generation.answer_semantics.time_role,
        "empty_set_policy": generation.answer_semantics.empty_set_policy,
    }
    try:
        answer = format_answer(generation.expected_answer_type, validation.normalized_candidate, semantics)
    except FormattingError as exc:
        return _retry_or_abstain(
            request,
            exc.code or ErrorCode.OUTPUT_TYPE_ERROR,
            validation.warnings,
            risk,
        )

    reason_code = ErrorCode.VALID_RESULT_AFTER_RETRY if request.attempt else ErrorCode.VALID_RESULT
    return GateOutcome(
        action=GateAction.FINAL,
        question_id=request.question.id,
        decision=Decision.ANSWER,
        final_answer=FinalAnswer(
            id=request.question.id,
            type=generation.expected_answer_type,
            answer=answer,
        ),
        reason_code=reason_code,
        validation={"passed": True, "errors": [], "warnings": validation.warnings},
        retry_count=request.attempt,
        risk_assessment=risk,
    )


def _evaluate_legacy(request: GateRequest) -> GateOutcome:
    """Evaluate a GateRequest end-to-end and emit either RETRY or FINAL GateOutcome."""
    question_id = request.question.id

    # 1. Evidence-Based Answerability Check (Prioritized before execution)
    is_unanswerable, ua_reason = evaluate_answerability(request)
    if is_unanswerable:
        return GateOutcome(
            action=GateAction.FINAL,
            question_id=question_id,
            decision=Decision.UNANSWERABLE,
            final_answer=FinalAnswer(
                id=question_id,
                type=AnswerType.UNANSWERABLE,
                reason=ua_reason,
            ),
            reason_code=ErrorCode.CONFIRMED_MISSING_EVIDENCE,
            validation={"passed": False, "errors": [], "warnings": []},
            retry_count=request.attempt,
            repair_request=None,
        )

    # If generation claims unanswerable without trusted catalog-verified proof -> abstain
    if request.generation and request.generation.answer_type == AnswerType.UNANSWERABLE:
        return GateOutcome(
            action=GateAction.FINAL,
            question_id=question_id,
            decision=Decision.ABSTAIN,
            final_answer=FinalAnswer(id=question_id, type=AnswerType.ABSTAIN),
            reason_code=ErrorCode.MISSING_EVIDENCE,
            validation={"passed": False, "errors": [ErrorCode.MISSING_EVIDENCE], "warnings": []},
            retry_count=request.attempt,
            repair_request=None,
        )

    # 2. Execution and Shape Validation
    val_res = validate_execution(request)
    if not val_res.passed:
        classification = classify_error(request.execution.error, val_res.error_code)
        repair = decide_retry(request, classification)

        if repair is not None:
            return GateOutcome(
                action=GateAction.RETRY,
                question_id=question_id,
                decision=Decision.RETRY,
                final_answer=None,
                reason_code=classification.code,
                validation={"passed": False, "errors": [classification.code], "warnings": val_res.warnings},
                retry_count=request.attempt,
                repair_request=repair,
            )
        else:
            reason_code = ErrorCode.RETRY_EXHAUSTED if request.attempt >= 1 else classification.code
            return GateOutcome(
                action=GateAction.FINAL,
                question_id=question_id,
                decision=Decision.ABSTAIN,
                final_answer=FinalAnswer(id=question_id, type=AnswerType.ABSTAIN),
                reason_code=reason_code,
                validation={"passed": False, "errors": [classification.code], "warnings": val_res.warnings},
                retry_count=request.attempt,
                repair_request=None,
            )

    # 3. Typed Output Formatting
    try:
        semantics_dict: Dict[str, Any] = {}
        if request.generation and request.generation.answer_semantics:
            semantics_dict = {
                "numeric_kind": request.generation.answer_semantics.numeric_kind,
                "percent_unit": request.generation.answer_semantics.percent_unit,
                "list_ordered": request.generation.answer_semantics.list_ordered,
                "time_role": request.generation.answer_semantics.time_role,
                "empty_set_policy": request.generation.answer_semantics.empty_set_policy,
            }

        target_type = request.generation.answer_type if request.generation else AnswerType.ABSTAIN
        formatted_answer = format_answer(target_type, val_res.normalized_candidate, semantics_dict)

        reason_code = ErrorCode.VALID_RESULT_AFTER_RETRY if request.attempt >= 1 else ErrorCode.VALID_RESULT
        return GateOutcome(
            action=GateAction.FINAL,
            question_id=question_id,
            decision=Decision.ANSWER,
            final_answer=FinalAnswer(id=question_id, type=target_type, answer=formatted_answer),
            reason_code=reason_code,
            validation={"passed": True, "errors": [], "warnings": val_res.warnings},
            retry_count=request.attempt,
            repair_request=None,
        )

    except FormattingError as f_err:
        # Cứu vãn kiểu dữ liệu an toàn nếu model gán nhầm nhãn (ví dụ nhầm 'number' với 'date' hoặc 'string'):
        cand = val_res.normalized_candidate
        if cand is not None:
            cand_str = str(cand).strip()
            import re
            # 1. Cứu vãn ngày tháng nếu chuỗi có định dạng ISO date (YYYY-MM-DD hoặc YYYY-MM):
            if re.match(r"^\d{4}-\d{2}(-\d{2})?$", cand_str):
                try:
                    formatted_answer = format_answer(AnswerType.DATE, cand, semantics_dict)
                    return GateOutcome(
                        action=GateAction.FINAL,
                        question_id=question_id,
                        decision=Decision.ANSWER,
                        final_answer=FinalAnswer(id=question_id, type=AnswerType.DATE, answer=formatted_answer),
                        reason_code=ErrorCode.VALID_RESULT,
                        validation={"passed": True, "errors": [], "warnings": val_res.warnings},
                        retry_count=request.attempt,
                        repair_request=None,
                    )
                except Exception:
                    pass

            # 2. Cứu vãn chuỗi ký tự nếu target_type ban đầu là number nhưng candidate là text hợp lệ (chứa chữ cái, không phải NaN/Inf):
            if target_type == AnswerType.NUMBER and isinstance(cand, str) and cand_str:
                if cand_str.lower() not in ("nan", "inf", "-inf", "null", "none"):
                    import unicodedata
                    if any(unicodedata.category(c)[0] == "L" for c in cand_str):
                        try:
                            formatted_answer = format_answer(AnswerType.STRING, cand, semantics_dict)
                            return GateOutcome(
                                action=GateAction.FINAL,
                                question_id=question_id,
                                decision=Decision.ANSWER,
                                final_answer=FinalAnswer(id=question_id, type=AnswerType.STRING, answer=formatted_answer),
                                reason_code=ErrorCode.VALID_RESULT,
                                validation={"passed": True, "errors": [], "warnings": val_res.warnings},
                                retry_count=request.attempt,
                                repair_request=None,
                            )
                        except Exception:
                            pass

        classification = classify_error(None, f_err.code or ErrorCode.OUTPUT_TYPE_ERROR)
        repair = decide_retry(request, classification)

        if repair is not None:
            return GateOutcome(
                action=GateAction.RETRY,
                question_id=question_id,
                decision=Decision.RETRY,
                final_answer=None,
                reason_code=classification.code,
                validation={"passed": False, "errors": [classification.code], "warnings": val_res.warnings},
                retry_count=request.attempt,
                repair_request=repair,
            )
        else:
            reason_code = ErrorCode.RETRY_EXHAUSTED if request.attempt >= 1 else classification.code
            return GateOutcome(
                action=GateAction.FINAL,
                question_id=question_id,
                decision=Decision.ABSTAIN,
                final_answer=FinalAnswer(id=question_id, type=AnswerType.ABSTAIN),
                reason_code=reason_code,
                validation={"passed": False, "errors": [classification.code], "warnings": val_res.warnings},
                retry_count=request.attempt,
                repair_request=None,
            )
