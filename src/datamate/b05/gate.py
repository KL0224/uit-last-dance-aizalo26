"""Main Evaluation Engine for B0.5 Basic Output Gate (DataMate 2026)."""

from typing import Any, Dict

from .answerability import evaluate_answerability
from .contracts import (
    AnswerType,
    Decision,
    FinalAnswer,
    GateAction,
    GateOutcome,
    GateRequest,
)
from .errors import ErrorCode, FormattingError
from .formatter import format_answer
from .retry import classify_error, decide_retry
from .validators import validate_execution


def evaluate_gate(request: GateRequest) -> GateOutcome:
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

