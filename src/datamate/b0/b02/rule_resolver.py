"""Select business rules conservatively for a specific question and industry."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from .contracts import BusinessRule, RuleCatalog

PRECEDENCE = {
    "question_override": 400,
    "business": 300,
    "industry": 200,
    "split_default": 100,
}


@dataclass(frozen=True)
class ResolvedRules:
    """Applicable rules plus blocked topics that must be reviewed by the caller."""

    rules: tuple[BusinessRule, ...]
    blocked_topics: tuple[str, ...]
    warnings: tuple[str, ...]


class RuleResolver:
    """Resolve only matching topics; no semantic equivalence is invented."""

    def resolve(
        self,
        catalog: RuleCatalog,
        business_id: str,
        industry: str | None = None,
        question_id: str | None = None,
    ) -> ResolvedRules:
        """Apply scope filters before precedence, blocking conflicting winners."""
        if catalog.business_id is not None and catalog.business_id != business_id:
            raise ValueError("rule catalog belongs to another business")
        if not business_id.strip():
            raise ValueError("business_id is required")
        grouped: dict[str, list[BusinessRule]] = {}
        warnings = list(catalog.warnings)
        for rule in catalog.rules:
            if rule.scope not in PRECEDENCE:
                warnings.append(f"{rule.rule_id}: unknown scope excluded")
                continue
            if (
                rule.scope in {"business", "question_override"}
                and catalog.business_id is None
            ):
                warnings.append(f"{rule.rule_id}: business scope lacks business_id")
                continue
            if rule.scope == "industry" and (
                not industry
                or not rule.industry
                or _normalize(industry) != _normalize(rule.industry)
            ):
                continue
            if rule.scope == "question_override" and (
                not question_id or rule.question_id != question_id
            ):
                continue
            topic = _normalize(rule.topic) if rule.topic else rule.rule_id
            grouped.setdefault(topic, []).append(rule)
        selected: list[BusinessRule] = []
        blocked: list[str] = []
        for topic, rules in sorted(grouped.items()):
            highest = max(PRECEDENCE[rule.scope] for rule in rules)
            winners = [rule for rule in rules if PRECEDENCE[rule.scope] == highest]
            if any(rule.status not in {"descriptive", "validated"} for rule in winners):
                blocked.append(topic)
                warnings.append(
                    f"{topic}: highest-precedence rule is invalid or conflicting; no fallback"
                )
                continue
            first = winners[0]
            equivalent = all(
                rule.expression == first.expression
                and (rule.expression is not None or rule.text == first.text)
                for rule in winners
            )
            if not equivalent:
                blocked.append(topic)
                warnings.append(
                    f"{topic}: ambiguous highest-precedence rules; no rule selected"
                )
                continue
            selected.append(min(winners, key=lambda rule: rule.rule_id))
        return ResolvedRules(tuple(selected), tuple(blocked), tuple(warnings))


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())
