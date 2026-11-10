"""C1: Hybrid Question Parser & Intent Extractor (Rule Fast-Path + 3B LLM Fallback)."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, replace

from .contracts import OperationKind, QuestionIntent
from .protocols import BusinessContextProtocol, LLMParserProtocol
from .rules_matcher import VietnameseRuleMatcher


_LOGGER = logging.getLogger(__name__)
_METRIC_REQUIRED_OPERATIONS = frozenset(
    {
        OperationKind.SUM,
        OperationKind.AVG,
        OperationKind.ARGMAX,
        OperationKind.ARGMIN,
        OperationKind.TOP_K,
        OperationKind.PERCENT_CHANGE,
        OperationKind.RATIO,
        OperationKind.COMPARISON,
    }
)
_COMMON_VI_SHORTHANDS = frozenset(
    {
        "bth",
        "ck",
        "cp",
        "cty",
        "dh",
        "ds",
        "dt",
        "hqua",
        "hnay",
        "kh",
        "kq",
        "ln",
        "nv",
        "sl",
        "sp",
        "thg",
        "tk",
        "tmai",
        "tt",
        "đh",
        "đt",
    }
)


@dataclass(frozen=True)
class FallbackDecision:
    """Evidence-backed decision for routing C1 from rules to the 3B parser."""

    should_use_llm: bool
    reasons: tuple[str, ...] = ()


class QuestionIntentParser:
    """Hybrid C1 parser combining deterministic Vietnamese rules with 3B LLM fallback."""

    def __init__(
        self,
        rule_matcher: VietnameseRuleMatcher | None = None,
        llm_fallback: LLMParserProtocol | None = None,
        fallback_threshold: float = 0.7,
    ) -> None:
        self._rule_matcher = rule_matcher or VietnameseRuleMatcher()
        self._llm_fallback = llm_fallback
        self._fallback_threshold = fallback_threshold

    @staticmethod
    def _has_unresolved_symbol(
        question: str,
        context: BusinessContextProtocol | None,
    ) -> bool:
        """Return True for emoji/currency-like symbols not declared as value aliases."""
        q_norm = unicodedata.normalize("NFC", question).lower()
        resolved_symbols: set[str] = set()
        if context is not None:
            for alias in context.get_value_aliases():
                alias_norm = unicodedata.normalize("NFC", alias).lower()
                if alias_norm in q_norm:
                    resolved_symbols.update(
                        char
                        for char in alias_norm
                        if unicodedata.category(char) in {"So", "Sc"}
                    )
        return any(
            unicodedata.category(char) in {"So", "Sc"}
            and char not in resolved_symbols
            for char in q_norm
        )

    @staticmethod
    def _has_unresolved_shorthand(
        question: str,
        context: BusinessContextProtocol | None,
    ) -> bool:
        """Detect explicit shorthand forms while excluding context-declared aliases."""
        q_norm = unicodedata.normalize("NFC", question).lower()
        known_aliases: set[str] = set()
        if context is not None:
            known_aliases.update(
                unicodedata.normalize("NFC", alias).lower()
                for alias in context.get_value_aliases()
            )
            for metric in context.get_metrics():
                known_aliases.update(
                    unicodedata.normalize("NFC", alias).lower()
                    for alias in metric.aliases
                )
        uppercase_tokens = re.findall(r"(?<!\w)[A-ZĐ]{2,8}(?!\w)", question)
        if any(token.lower() not in known_aliases for token in uppercase_tokens):
            return True
        dotted_shorthand = r"(?<!\w)[A-Za-zĐđ]{1,4}(?:\.[A-Za-zĐđ]{1,8})+(?!\w)"
        dotted_tokens = re.findall(dotted_shorthand, question)
        if any(token.lower() not in known_aliases for token in dotted_tokens):
            return True
        compact_tokens = set(re.findall(r"(?<!\w)[^\W\d_]{2,5}(?!\w)", q_norm))
        return bool((compact_tokens & _COMMON_VI_SHORTHANDS) - known_aliases)

    def decide_fallback(
        self,
        question: str,
        rule_intent: QuestionIntent,
        context: BusinessContextProtocol | None = None,
    ) -> FallbackDecision:
        """Decide whether deterministic parsing has enough semantic evidence."""
        reasons: list[str] = []
        if rule_intent.confidence < self._fallback_threshold:
            reasons.append("LOW_RULE_CONFIDENCE")
        if (
            rule_intent.operation in _METRIC_REQUIRED_OPERATIONS
            and not rule_intent.target_metrics
        ):
            reasons.append("MISSING_REQUIRED_METRIC")
        if len(rule_intent.target_metrics) > 1:
            reasons.append("AMBIGUOUS_METRICS")

        if context is not None and rule_intent.target_metrics:
            available_metrics = {metric.metric_id for metric in context.get_metrics()}
            if available_metrics and any(
                metric not in available_metrics for metric in rule_intent.target_metrics
            ):
                reasons.append("METRIC_OUTSIDE_REGISTRY")

        if self._has_unresolved_symbol(question, context):
            reasons.append("UNRESOLVED_SYMBOL")
        if self._has_unresolved_shorthand(question, context):
            reasons.append("UNRESOLVED_SHORTHAND")

        return FallbackDecision(should_use_llm=bool(reasons), reasons=tuple(reasons))

    @staticmethod
    def _validate_llm_intent(intent: QuestionIntent) -> None:
        """Reject structurally valid JSON that is still semantically incomplete."""
        if intent.operation in _METRIC_REQUIRED_OPERATIONS and not intent.target_metrics:
            raise ValueError(
                f"LLM intent for {intent.operation.value} requires at least one metric"
            )
        if intent.operation == OperationKind.TOP_K and intent.top_k is None:
            raise ValueError("LLM top_k intent requires a positive top_k value")
        if intent.sort_order not in {"asc", "desc"}:
            raise ValueError("LLM sort_order must be 'asc' or 'desc'")

    def parse(
        self,
        question: str,
        as_of_date: str,
        context: BusinessContextProtocol | None = None,
    ) -> QuestionIntent:
        """Extract structured QuestionIntent via fast-path rules or 3B LLM fallback."""
        rule_intent = self._rule_matcher.match(question, context)
        decision = self.decide_fallback(question, rule_intent, context)

        if (
            decision.should_use_llm
            and self._llm_fallback is not None
        ):
            available_metrics = (
                [m.metric_id for m in context.get_metrics()] if context else []
            )
            available_tables = (
                [t.name for t in context.get_tables()] if context else []
            )
            try:
                llm_intent = self._llm_fallback.extract_intent(
                    question=question,
                    as_of_date=as_of_date,
                    available_metrics=available_metrics,
                    available_tables=available_tables,
                )
                self._validate_llm_intent(llm_intent)
                return replace(llm_intent, fallback_reasons=decision.reasons)
            except Exception as exc:
                _LOGGER.warning(
                    "grounding_llm_fallback_failed",
                    extra={
                        "event": "grounding_llm_fallback_failed",
                        "fallback_reasons": decision.reasons,
                        "error_type": type(exc).__name__,
                    },
                )
                # Safe degradation: return deterministic rule_intent if LLM fallback fails
                return replace(
                    rule_intent,
                    fallback_reasons=decision.reasons + ("LLM_FALLBACK_FAILED",),
                )

        return replace(rule_intent, fallback_reasons=decision.reasons)


__all__ = ["FallbackDecision", "QuestionIntentParser"]
