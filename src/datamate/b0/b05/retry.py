"""Error Classifier and Bounded Retry Controller for B0.5 Basic Output Gate."""

from typing import Optional

from .contracts import ExecutionErrorDetail, GateRequest, RepairRequest
from .errors import ErrorClassification, ErrorCode


def classify_error(
    error_detail: Optional[ExecutionErrorDetail],
    validation_error_code: Optional[str] = None,
) -> ErrorClassification:
    """Classify execution and validation errors into standard taxonomy."""
    # 1. Classify execution error
    if error_detail is not None:
        err_type = (error_detail.type or "").lower()
        err_msg = (error_detail.message or "").lower()
        text = f"{err_type} {err_msg}"

        is_known_recoverable_type = any(
            k in err_type
            for k in (
                "binder",
                "catalog",
                "parser",
                "syntax",
                "conversion",
                "dataerror",
                "emptyquery",
                "emptyresultwarning",
            )
        )

        if (
            "security" in err_type
            or "permission" in err_type
            or (
                not is_known_recoverable_type
                and any(w in err_msg for w in ["forbidden", "drop ", "delete ", "update ", "insert ", "read-only"])
            )
        ):
            return ErrorClassification(
                code=ErrorCode.SECURITY_VIOLATION,
                retryable=False,
                evidence=error_detail.message,
                safe_feedback="Security violation: only read-only SELECT queries are allowed.",
            )

        if "emptyresultwarning" in err_type or "all null values" in err_msg:
            return ErrorClassification(
                code=ErrorCode.NULL_RESULT,
                retryable=True,
                evidence=error_detail.message,
                safe_feedback="Query returned NULL for aggregation. Check WHERE filter values (exact Vietnamese text or date format).",
            )

        if "conversion" in err_type or "dataerror" in err_type:
            return ErrorClassification(
                code=ErrorCode.SQL_TYPE_ERROR,
                retryable=True,
                evidence=error_detail.message,
                safe_feedback="Fix type casting or operator mismatch in query.",
            )

        if (
            "binder" in text
            or "catalog" in text
            or "does not exist" in err_msg
            or "not found" in err_msg
            or "unknown table" in err_msg
            or "column" in err_msg
        ):
            return ErrorClassification(
                code=ErrorCode.SCHEMA_ERROR,
                retryable=True,
                evidence=error_detail.message,
                safe_feedback="Reinspect exact available column and table names from schema.",
            )

        if (
            "parser" in text
            or "syntax" in text
            or "emptyquery" in err_type
            or "query is empty" in err_msg
        ):
            return ErrorClassification(
                code=ErrorCode.SQL_SYNTAX,
                retryable=True,
                evidence=error_detail.message,
                safe_feedback="Fix SQL syntax error to match valid dialect.",
            )

        if (
            "cast" in text
            or "type mismatch" in text
            or "conversion" in text
            or "dataerror" in err_type
            or "out of range" in text
            or "invalid input" in text
        ):
            return ErrorClassification(
                code=ErrorCode.SQL_TYPE_ERROR,
                retryable=True,
                evidence=error_detail.message,
                safe_feedback="Fix type casting or operator mismatch in query.",
            )

        if "timeout" in text or "deadline" in text or "time limit" in text:
            return ErrorClassification(
                code=ErrorCode.QUERY_TIMEOUT,
                retryable=False,
                evidence=error_detail.message,
                safe_feedback="Query execution timed out or exceeded resource limit.",
            )

        return ErrorClassification(
            code=ErrorCode.EXECUTOR_FAILURE,
            retryable=False,
            evidence=error_detail.message,
            safe_feedback=f"Executor failed: {error_detail.message[:100]}",
        )

    # 2. Classify validation failure
    if validation_error_code is not None:
        if validation_error_code in (
            ErrorCode.ANSWER_TYPE_MISMATCH,
            ErrorCode.SEMANTIC_PROOF_FAILED,
        ):
            return ErrorClassification(
                code=validation_error_code,
                retryable=True,
                evidence=f"Proof validation failed with code: {validation_error_code}",
                safe_feedback="Repair the candidate while preserving plan_id, metric_id, and expected_answer_type.",
            )
        if validation_error_code == ErrorCode.SCALAR_SHAPE_MISMATCH:
            return ErrorClassification(
                code=ErrorCode.SCALAR_SHAPE_MISMATCH,
                retryable=True,
                evidence="Query returned multiple rows or columns for a scalar answer type.",
                safe_feedback="Add aggregate function or appropriate GROUP BY / LIMIT to return exactly 1 row and 1 column.",
            )

        if validation_error_code == ErrorCode.OUTPUT_TYPE_ERROR:
            return ErrorClassification(
                code=ErrorCode.OUTPUT_TYPE_ERROR,
                retryable=True,
                evidence="Output shape or value type does not match requested answer type.",
                safe_feedback="Adjust query projection and types to match the expected answer type.",
            )

        if validation_error_code in (
            ErrorCode.EMPTY_RESULT,
            ErrorCode.NULL_RESULT,
            ErrorCode.TRUNCATED_RESULT,
            ErrorCode.TABLE_SHAPE_ERROR,
            ErrorCode.CONTRACT_ERROR,
        ):
            return ErrorClassification(
                code=validation_error_code,
                retryable=False,
                evidence=f"Validation failed with code: {validation_error_code}",
                safe_feedback=f"Result failed validation: {validation_error_code}",
            )

        return ErrorClassification(
            code=validation_error_code,
            retryable=False,
            evidence=f"Validation code: {validation_error_code}",
            safe_feedback="Validation failed.",
        )

    return ErrorClassification(
        code=ErrorCode.UNKNOWN_ERROR,
        retryable=False,
        evidence="Unknown error",
        safe_feedback="An unknown error occurred.",
    )


def decide_retry(
    request: GateRequest,
    classification: ErrorClassification,
) -> Optional[RepairRequest]:
    """Determine whether to trigger a bounded retry (max 1 retry)."""
    # Invariant: Attempt 1 is the final retry attempt; if it fails, terminate with abstain
    if request.attempt >= 1:
        return None

    if not classification.retryable:
        return None

    failed_sql = ""
    if request.generation is not None:
        failed_sql = request.generation.sql

    err_type = classification.code
    err_msg = classification.evidence
    if request.execution.error is not None:
        err_type = request.execution.error.type or classification.code
        err_msg = request.execution.error.message or classification.evidence

    return RepairRequest(
        attempt=1,
        failed_sql=failed_sql,
        error_type=err_type,
        error_message=err_msg,
        error_code=classification.code,
        schema_hint=classification.safe_feedback,
        available_columns=None,
        do_not_change_question=True,
        instruction=classification.safe_feedback,
        plan_id=request.generation.plan_id if request.generation else None,
        metric_id=request.generation.metric_id if request.generation else None,
        expected_answer_type=request.generation.expected_answer_type if request.generation else None,
    )
