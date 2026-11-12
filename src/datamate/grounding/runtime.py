"""Runtime boundary for deterministic question grounding."""

from __future__ import annotations

from .contracts import GroundedQuestion, QuestionRequest
from .engine import QuestionGroundingEngine
from .protocols import BusinessContextProtocol

GROUNDING_REQUEST_INVALID = "GROUNDING_REQUEST_INVALID"
GROUNDING_CONTEXT_INVALID = "GROUNDING_CONTEXT_INVALID"
GROUNDING_BUSINESS_MISMATCH = "GROUNDING_BUSINESS_MISMATCH"
GROUNDING_FAILED = "GROUNDING_FAILED"


class QuestionGroundingRuntimeError(RuntimeError):
    """Expose a stable grounding error without leaking question/context data."""

    def __init__(
        self,
        *,
        code: str,
        question_id: str,
        business_id: str,
        message: str,
    ) -> None:
        self.code = code
        self.question_id = _safe_identifier(question_id)
        self.business_id = _safe_identifier(business_id)
        super().__init__(
            f"{code}: {message} "
            f"(question_id={self.question_id!r}, business_id={self.business_id!r})"
        )


def _safe_identifier(value: object) -> str:
    """Normalize trace identifiers without including arbitrary payload values."""
    return value.strip() if isinstance(value, str) else ""


class QuestionGroundingRuntime:
    """Validate the runtime boundary and execute Grounding C1 through C5 once."""

    def __init__(self, engine: QuestionGroundingEngine | None = None) -> None:
        self._engine = engine if engine is not None else QuestionGroundingEngine()

    def ground_question(
        self,
        *,
        question_id: str,
        business_id: str,
        question: str,
        as_of_date: str,
        context: BusinessContextProtocol,
    ) -> GroundedQuestion:
        """Return one grounded question or raise a classified boundary error."""
        try:
            request = QuestionRequest(
                question_id=question_id,
                business_id=business_id,
                question=question,
                as_of_date=as_of_date,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise QuestionGroundingRuntimeError(
                code=GROUNDING_REQUEST_INVALID,
                question_id=question_id,
                business_id=business_id,
                message="Grounding request is invalid",
            ) from exc

        try:
            context_is_valid = isinstance(context, BusinessContextProtocol)
            context_business_id = (
                _safe_identifier(context.business_id) if context_is_valid else ""
            )
        except Exception as exc:
            raise QuestionGroundingRuntimeError(
                code=GROUNDING_CONTEXT_INVALID,
                question_id=request.question_id,
                business_id=request.business_id,
                message="Grounding context identity cannot be read",
            ) from exc

        if not context_is_valid:
            raise QuestionGroundingRuntimeError(
                code=GROUNDING_CONTEXT_INVALID,
                question_id=request.question_id,
                business_id=request.business_id,
                message="Grounding context does not satisfy the required protocol",
            )

        if not context_business_id:
            raise QuestionGroundingRuntimeError(
                code=GROUNDING_CONTEXT_INVALID,
                question_id=request.question_id,
                business_id=request.business_id,
                message="Grounding context has no valid business identity",
            )
        if context_business_id != request.business_id:
            raise QuestionGroundingRuntimeError(
                code=GROUNDING_BUSINESS_MISMATCH,
                question_id=request.question_id,
                business_id=request.business_id,
                message="Grounding request and context belong to different businesses",
            )

        try:
            return self._engine.ground(request, context)
        except Exception as exc:
            raise QuestionGroundingRuntimeError(
                code=GROUNDING_FAILED,
                question_id=request.question_id,
                business_id=request.business_id,
                message="Question grounding failed",
            ) from exc


__all__ = [
    "GROUNDING_BUSINESS_MISMATCH",
    "GROUNDING_CONTEXT_INVALID",
    "GROUNDING_FAILED",
    "GROUNDING_REQUEST_INVALID",
    "QuestionGroundingRuntime",
    "QuestionGroundingRuntimeError",
]
