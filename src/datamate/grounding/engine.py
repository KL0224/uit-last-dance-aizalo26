"""QuestionGroundingEngine: Coordinator orchestrating C1 -> C2 -> C3 -> C4 -> C5."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Self

from .answerability import AnswerabilityPrechecker
from .contracts import (
    AnswerTypeHint,
    CoverageStatus,
    DateRole,
    GroundedQuestion,
    QuestionRequest,
)
from .normalizer import VietnameseQuestionNormalizer
from .parser import QuestionIntentParser
from .protocols import BusinessContextProtocol
from .schema_grounder import SchemaGrounder
from .temporal import QuestionTemporalResolver
from .value_grounder import ValueGrounder


class QuestionGroundingEngine:
    """Central orchestrator for Component C (Question Grounding)."""

    def __init__(
        self,
        intent_parser: QuestionIntentParser | None = None,
        temporal_resolver: QuestionTemporalResolver | None = None,
        schema_grounder: SchemaGrounder | None = None,
        value_grounder: ValueGrounder | None = None,
        answerability_prechecker: AnswerabilityPrechecker | None = None,
        question_normalizer: VietnameseQuestionNormalizer | None = None,
    ) -> None:
        self._question_normalizer = question_normalizer or VietnameseQuestionNormalizer()
        self._intent_parser = intent_parser or QuestionIntentParser()
        self._temporal_resolver = temporal_resolver or QuestionTemporalResolver()
        self._schema_grounder = schema_grounder or SchemaGrounder()
        self._value_grounder = value_grounder or ValueGrounder()
        self._answerability_prechecker = (
            answerability_prechecker or AnswerabilityPrechecker()
        )

    @property
    def chat_fn(self) -> Any | None:
        """Return the underlying 3B chat function if loaded."""
        if self._intent_parser is not None:
            return getattr(self._intent_parser, "chat_fn", None)
        return None

    @classmethod
    def from_qwen3b_vllm(
        cls,
        config_path: str | Path,
        *,
        fallback_threshold: float = 0.7,
        model_path_override: str | Path | None = None,
    ) -> Self:
        """Build an engine whose C1 fallback is a local Qwen 3B vLLM model."""
        from .llm_fallback import create_qwen3b_vllm_parser

        if model_path_override is not None:
            llm_fallback = create_qwen3b_vllm_parser(
                config_path,
                model_path_override=model_path_override,
            )
        else:
            llm_fallback = create_qwen3b_vllm_parser(config_path)
        return cls(
            intent_parser=QuestionIntentParser(
                llm_fallback=llm_fallback,
                fallback_threshold=fallback_threshold,
            )
        )

    def _infer_preferred_date_role(
        self,
        target_metrics: tuple[str, ...],
        context: BusinessContextProtocol,
    ) -> DateRole | None:
        """Look up preferred date_role from the matched metric in MetricRegistry."""
        metrics_map = {m.metric_id: m for m in context.get_metrics()}
        for m_id in target_metrics:
            m_spec = metrics_map.get(m_id)
            if m_spec and m_spec.date_role:
                try:
                    return DateRole(m_spec.date_role)
                except ValueError:
                    pass
        return None

    def ground(
        self,
        request: QuestionRequest,
        context: BusinessContextProtocol,
    ) -> GroundedQuestion:
        """Execute full C1 -> C2 -> C3 -> C4 -> C5 grounding pipeline."""
        normalized_question = self._question_normalizer.normalize(request.question)

        # Step C1: Extract QuestionIntent
        raw_intent = self._intent_parser.parse(
            question=normalized_question,
            as_of_date=request.as_of_date,
            context=context,
        )
        effective_question = self._question_normalizer.normalize(
            raw_intent.normalized_question or normalized_question
        )
        raw_intent = replace(
            raw_intent,
            normalized_question=effective_question,
        )

        # Step C2: Resolve Temporal Constraints relative to as_of_date
        preferred_role = self._infer_preferred_date_role(
            raw_intent.target_metrics, context
        )
        resolved_times = self._temporal_resolver.resolve(
            question=effective_question,
            as_of_date=request.as_of_date,
            context=context,
            preferred_date_role=preferred_role,
        )

        # Step C3: Ground Schema (Top-K tables, columns, and safe join paths)
        selected_schema = self._schema_grounder.ground(
            question=effective_question,
            intent=raw_intent,
            context=context,
        )

        # Step C4: Ground Entity Values & Filter Conditions
        matched_values, updated_filters = self._value_grounder.ground(
            question=effective_question,
            intent=raw_intent,
            selected_schema=selected_schema,
            context=context,
        )
        enriched_intent = replace(raw_intent, filters=updated_filters)

        # Step C5: Answerability Precheck
        evidence_reqs, coverage_status, missing_proof, risk_flags = (
            self._answerability_prechecker.evaluate(
                question=effective_question,
                intent=enriched_intent,
                resolved_time_ranges=resolved_times,
                selected_schema=selected_schema,
                context=context,
            )
        )

        final_answer_hint = (
            AnswerTypeHint.UNANSWERABLE
            if coverage_status == CoverageStatus.UNSUPPORTED
            else enriched_intent.answer_type_hint
        )

        active_rules = tuple(context.get_active_rules())

        return GroundedQuestion(
            question_id=request.question_id,
            business_id=request.business_id,
            question=request.question,
            as_of_date=request.as_of_date,
            intent=enriched_intent,
            resolved_time_ranges=resolved_times,
            selected_schema=selected_schema,
            matched_values=matched_values,
            answer_type_hint=final_answer_hint,
            evidence_requirements=evidence_reqs,
            coverage_status=coverage_status,
            missing_evidence_proof=missing_proof,
            applicable_rules=active_rules,
            risk_flags=risk_flags,
        )


__all__ = ["QuestionGroundingEngine"]
