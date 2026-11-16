"""Runtime boundary for deterministic and neural question grounding."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

from .contracts import (
    AnswerTypeHint,
    CandidateJoinPath,
    CoverageStatus,
    DateRole,
    EvidenceRequirement,
    FilterCondition,
    GroundedQuestion,
    MatchedValue,
    MissingEvidenceProof,
    OperationKind,
    QuestionIntent,
    QuestionRequest,
    ResolvedTimeRange,
    SchemaCandidate,
    SelectedSchema,
)
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
    """Validate the runtime boundary and execute a grounding engine once."""

    def __init__(self, engine: Any = None) -> None:
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


def serialize_grounded_question(
    grounded: GroundedQuestion,
    *,
    elapsed_ms: float | None = None,
    index_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Serialize a GroundedQuestion and optional timing metadata for cache persistence."""
    return {
        "question_id": grounded.question_id,
        "business_id": grounded.business_id,
        "grounding_source": grounded.grounding_source,
        "elapsed_ms": elapsed_ms,
        "index_fingerprint": index_fingerprint,
        "grounded": grounded.to_dict(),
    }


def _coerce_enum(enum_cls: type[Any], value: Any, default: Any) -> Any:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (TypeError, ValueError):
        return default


def deserialize_grounded_question(
    record: Mapping[str, Any],
) -> tuple[GroundedQuestion, float | None]:
    """Reconstruct a GroundedQuestion and its cached elapsed_ms from a JSONL record."""
    raw = record.get("grounded") if isinstance(record.get("grounded"), Mapping) else record
    raw_intent = raw.get("intent") or {}
    filters = tuple(
        FilterCondition(
            field_hint=str(f.get("field_hint", "")),
            operator=str(f.get("operator", "=")),
            raw_value=f.get("raw_value"),
            grounded_column=f.get("grounded_column"),
            grounded_value=f.get("grounded_value"),
            is_having=bool(f.get("is_having", False)),
        )
        for f in (raw_intent.get("filters") or ())
    )
    intent = QuestionIntent(
        operation=_coerce_enum(OperationKind, raw_intent.get("operation"), OperationKind.UNKNOWN),
        target_metrics=tuple(str(x) for x in (raw_intent.get("target_metrics") or ())),
        entities=tuple(str(x) for x in (raw_intent.get("entities") or ())),
        filters=filters,
        group_by=tuple(str(x) for x in (raw_intent.get("group_by") or ())),
        top_k=raw_intent.get("top_k"),
        sort_order=str(raw_intent.get("sort_order", "desc")),
        tie_break_rule=str(raw_intent.get("tie_break_rule", "entity_asc")),
        answer_type_hint=_coerce_enum(
            AnswerTypeHint, raw_intent.get("answer_type_hint"), AnswerTypeHint.UNKNOWN
        ),
        confidence=float(raw_intent.get("confidence", 1.0)),
        used_llm_fallback=bool(raw_intent.get("used_llm_fallback", False)),
        fallback_reasons=tuple(str(x) for x in (raw_intent.get("fallback_reasons") or ())),
        normalized_question=raw_intent.get("normalized_question"),
    )

    time_ranges = tuple(
        ResolvedTimeRange(
            raw_expression=str(tr.get("raw_expression", "")),
            start_date=str(tr["start_date"]),
            end_date=str(tr["end_date"]),
            date_role=_coerce_enum(DateRole, tr.get("date_role"), DateRole.GENERIC_DATE),
            inclusive=bool(tr.get("inclusive", True)),
            comparison_start_date=tr.get("comparison_start_date"),
            comparison_end_date=tr.get("comparison_end_date"),
            interpretation=str(tr.get("interpretation", "")),
        )
        for tr in (raw.get("resolved_time_ranges") or ())
    )

    raw_schema = raw.get("selected_schema") or {}
    tables = tuple(
        SchemaCandidate(
            table_name=str(t.get("table_name", "")),
            relevant_columns=tuple(str(c) for c in (t.get("relevant_columns") or ())),
            grain=t.get("grain"),
            score=float(t.get("score", 0.0)),
            rationale=str(t.get("rationale", "")),
        )
        for t in (raw_schema.get("tables") or ())
    )
    join_paths = tuple(
        CandidateJoinPath(
            left_table=str(j.get("left_table", "")),
            left_column=str(j.get("left_column", "")),
            right_table=str(j.get("right_table", "")),
            right_column=str(j.get("right_column", "")),
            cardinality=str(j.get("cardinality", "many_to_one")),
            fanout_warning=bool(j.get("fanout_warning", False)),
            confidence=float(j.get("confidence", 1.0)),
            additional_key_pairs=tuple(
                (str(pair[0]), str(pair[1])) for pair in (j.get("additional_key_pairs") or ())
            ),
            null_key_warning=bool(j.get("null_key_warning", False)),
        )
        for j in (raw_schema.get("join_paths") or ())
    )
    selected_schema = SelectedSchema(
        primary_table=raw_schema.get("primary_table"),
        tables=tables,
        join_paths=join_paths,
        fanout_warning=bool(raw_schema.get("fanout_warning", False)),
        warnings=tuple(str(w) for w in (raw_schema.get("warnings") or ())),
    )

    matched_values = tuple(
        MatchedValue(
            raw_text=str(mv.get("raw_text", "")),
            table_name=str(mv.get("table_name", "")),
            column_name=str(mv.get("column_name", "")),
            matched_db_value=mv.get("matched_db_value"),
            match_type=str(mv.get("match_type", "exact")),
            confidence=float(mv.get("confidence", 1.0)),
        )
        for mv in (raw.get("matched_values") or ())
    )

    evidence_requirements = tuple(
        EvidenceRequirement(
            capability_key=str(er.get("capability_key", "")),
            required_concepts=tuple(str(c) for c in (er.get("required_concepts") or ())),
            is_mandatory=bool(er.get("is_mandatory", True)),
        )
        for er in (raw.get("evidence_requirements") or ())
    )

    raw_mp = raw.get("missing_evidence_proof")
    missing_proof = (
        MissingEvidenceProof(
            capability_key=str(raw_mp.get("capability_key", "")),
            missing_fields=tuple(str(f) for f in (raw_mp.get("missing_fields") or ())),
            checked_tables=tuple(str(t) for t in (raw_mp.get("checked_tables") or ())),
            checked_all_sources=bool(raw_mp.get("checked_all_sources", True)),
            reason=str(raw_mp.get("reason", "")),
        )
        if isinstance(raw_mp, Mapping)
        else None
    )

    grounded = GroundedQuestion(
        question_id=str(raw["question_id"]),
        business_id=str(raw["business_id"]),
        question=str(raw["question"]),
        as_of_date=str(raw["as_of_date"]),
        intent=intent,
        resolved_time_ranges=time_ranges,
        selected_schema=selected_schema,
        matched_values=matched_values,
        answer_type_hint=_coerce_enum(
            AnswerTypeHint, raw.get("answer_type_hint"), AnswerTypeHint.UNKNOWN
        ),
        evidence_requirements=evidence_requirements,
        coverage_status=_coerce_enum(
            CoverageStatus, raw.get("coverage_status"), CoverageStatus.UNKNOWN
        ),
        missing_evidence_proof=missing_proof,
        applicable_rules=tuple(str(r) for r in (raw.get("applicable_rules") or ())),
        risk_flags=tuple(str(r) for r in (raw.get("risk_flags") or ())),
        grounding_source=str(raw.get("grounding_source", "rules")),
        planner_input=dict(raw["planner_input"]) if isinstance(raw.get("planner_input"), Mapping) else None,
    )
    elapsed = record.get("elapsed_ms")
    return grounded, (float(elapsed) if elapsed is not None else None)


def save_grounding_cache(path: str | Path, entries: Sequence[Mapping[str, Any]]) -> Path:
    """Persist serialized Phase-1 grounding entries into a JSONL cache file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(entry, ensure_ascii=False) for entry in entries]
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return target


def load_grounding_cache(path: str | Path) -> dict[str, tuple[GroundedQuestion, float | None]]:
    """Load Phase-1 grounding cache JSONL keyed by question_id."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Grounding cache not found: {source}")
    cached: dict[str, tuple[GroundedQuestion, float | None]] = {}
    with source.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            grounded, elapsed_ms = deserialize_grounded_question(record)
            cached[grounded.question_id] = (grounded, elapsed_ms)
    return cached


class CachedGroundingRuntime:
    """Serve precomputed Phase-1 GroundedQuestion artifacts during Phase-2 Planner execution."""

    def __init__(
        self,
        cache_by_question_id: Mapping[str, tuple[GroundedQuestion, float | None] | GroundedQuestion],
        *,
        fallback_runtime: QuestionGroundingRuntime | None = None,
    ) -> None:
        self._cache: dict[str, GroundedQuestion] = {}
        self._elapsed_ms: dict[str, float] = {}
        for q_id, item in cache_by_question_id.items():
            if isinstance(item, tuple):
                grounded, elapsed = item
            else:
                grounded, elapsed = item, None
            key = str(q_id)
            self._cache[key] = grounded
            if elapsed is not None:
                self._elapsed_ms[key] = float(elapsed)
        self._fallback_runtime = fallback_runtime

    def get_cached_elapsed_ms(self, question_id: str) -> float | None:
        return self._elapsed_ms.get(str(question_id).strip())

    def ground_question(
        self,
        *,
        question_id: str,
        business_id: str,
        question: str,
        as_of_date: str,
        context: BusinessContextProtocol,
    ) -> GroundedQuestion:
        key = _safe_identifier(question_id)
        req_biz = _safe_identifier(business_id)
        cached = self._cache.get(key)
        if cached is not None:
            if cached.business_id != req_biz:
                raise QuestionGroundingRuntimeError(
                    code=GROUNDING_BUSINESS_MISMATCH,
                    question_id=key,
                    business_id=req_biz,
                    message="Cached grounding entry belongs to a different business",
                )
            return cached
        if self._fallback_runtime is not None:
            return self._fallback_runtime.ground_question(
                question_id=question_id,
                business_id=business_id,
                question=question,
                as_of_date=as_of_date,
                context=context,
            )
        raise QuestionGroundingRuntimeError(
            code=GROUNDING_FAILED,
            question_id=key,
            business_id=req_biz,
            message="Question is missing from grounding cache",
        )


__all__ = [
    "CachedGroundingRuntime",
    "GROUNDING_BUSINESS_MISMATCH",
    "GROUNDING_CONTEXT_INVALID",
    "GROUNDING_FAILED",
    "GROUNDING_REQUEST_INVALID",
    "QuestionGroundingRuntime",
    "QuestionGroundingRuntimeError",
    "deserialize_grounded_question",
    "load_grounding_cache",
    "save_grounding_cache",
    "serialize_grounded_question",
]
