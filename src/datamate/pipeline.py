"""End-to-End Orchestrator for DataMate 2026.

Canonical Pipeline Architecture:
Business Context (A/B) -> Question Grounding (C) -> Agent Planner (D)
-> Safe Execution (E) -> Verification & Bounded Repair (F)
-> Decision & Output Gate (G) -> Telemetry & Audit Logs (H).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence

from datamate.context.runtime import (
    BusinessContextRuntimeLoader,
    BusinessRuntimeContext,
    enrich_context_from_duckdb,
)
from datamate.grounding import (
    BusinessContextAdapter,
    GroundedQuestion,
    GroundingToPlannerAdapter,
    QuestionGroundingRuntime,
    QuestionGroundingRuntimeError,
)
from datamate.ingestion.ingestion import PreparedBusinessArtifacts, prepare_business
from datamate.voting import VotingConfig, run_voting
from datamate.planner.diagnostics import diagnostics_dict
from datamate.planner.generator import Text2SQLGenerator
from datamate.planner.types import GenerationOptions, Text2SQLResult
from datamate.execution import ExecutionRequest, execute_query
from datamate.gate import SubmissionWriter, evaluate_gate
from datamate.gate.contracts import (
    AnswerType,
    Decision,
    EvidenceProof,
    ExecutionResult,
    FinalAnswer,
    GateAction,
    GateOutcome,
    GateRequest,
    QuestionMeta,
    RepairRequest,
)
from datamate.gate.errors import ErrorCode

logger = logging.getLogger(__name__)


class DataMatePipeline:
    """Điều phối toàn trình DataMate: Context -> Grounding -> Planner -> Executor -> Gate."""

    def __init__(
        self,
        generator: Text2SQLGenerator,
        *,
        timeout_sec: float = 10.0,
        max_rows: int = 10000,
        options: GenerationOptions | None = None,
        enable_grounding: bool = True,
        voting: VotingConfig | None = None,
        gate_contract_version: str = "b05.v1",
        grounding_runtime: QuestionGroundingRuntime | None = None,
        context_loader: BusinessContextRuntimeLoader | None = None,
        grounded_hint_mode: str | None = None,
    ) -> None:
        self.generator = generator
        self.voting = voting or VotingConfig()
        self.timeout_sec = timeout_sec
        self.max_rows = max_rows
        self.options = options
        self.enable_grounding = enable_grounding
        self.gate_contract_version = gate_contract_version
        self.grounded_hint_mode = grounded_hint_mode
        self.grounding_runtime = (
            grounding_runtime if grounding_runtime is not None else QuestionGroundingRuntime()
        )
        self.context_loader = (
            context_loader if context_loader is not None else BusinessContextRuntimeLoader()
        )

    def _format_grounded_hint(self, grounded: GroundedQuestion) -> str | None:
        mode = self.grounded_hint_mode
        if mode is None or mode == "auto":
            mode = getattr(self.generator, "effective_grounded_hint_mode", None)
            if mode is None:
                pfmt = getattr(self.generator, "prompt_format", "legacy")
                mode = "compact_json" if pfmt == "v1_2" else "markdown"
        if mode == "off":
            return None
        if mode == "compact_json":
            return GroundingToPlannerAdapter.format_grounded_hint_for_v1_2(grounded)
        return GroundingToPlannerAdapter.format_grounded_hint_for_planner(grounded)

    def _resolve_grounding_ms(self, question_id: str, fallback_ms: float) -> float:
        cached_fn = getattr(self.grounding_runtime, "get_cached_elapsed_ms", None)
        if callable(cached_fn):
            cached_ms = cached_fn(question_id)
            if cached_ms is not None:
                return float(cached_ms)
        return fallback_ms

    @staticmethod
    def prepare_bundle(
        business_dir: str | Path,
        output_dir: str | Path,
        *,
        rulebook: str | Path | None = None,
        calendar: str | Path | None = None,
        relationships: str | Path | None = None,
        config: Any = None,
    ) -> PreparedBusinessArtifacts:
        """Chuẩn bị bundle dữ liệu và ngữ nghĩa cho một thư mục doanh nghiệp."""
        return prepare_business(
            business_dir=business_dir,
            output_dir=output_dir,
            rulebook=rulebook,
            calendar=calendar,
            relationships=relationships,
            config=config,
        )

    @classmethod
    def load_runtime_context(
        cls,
        bundle_dir: str | Path,
        *,
        expected_business_id: str | None = None,
        loader: BusinessContextRuntimeLoader | None = None,
    ) -> BusinessRuntimeContext:
        """Load đối tượng BusinessRuntimeContext chứa cả planner_context và grounding_context."""
        active_loader = loader if loader is not None else BusinessContextRuntimeLoader()
        return active_loader.load(bundle_dir, expected_business_id=expected_business_id)

    @classmethod
    def load_context(cls, bundle_dir: str | Path) -> dict[str, Any]:
        """Load context định dạng dictionary tương thích với Planner."""
        return BusinessContextRuntimeLoader().load(bundle_dir).planner_context

    @staticmethod
    def _enrich_context_from_duckdb(ctx: dict[str, Any], db_path: Path) -> None:
        """Compatibility wrapper for callers using the former pipeline helper."""
        enrich_context_from_duckdb(ctx, db_path)

    @staticmethod
    def _build_grounding_summary(
        grounded: GroundedQuestion | None,
        elapsed_ms: float | None = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        if grounded is None:
            if error is not None:
                return {
                    "status": "error",
                    "error": error,
                    "elapsed_ms": elapsed_ms,
                }
            return None

        intent = grounded.intent
        summary: dict[str, Any] = {
            "status": "ok",
            "grounding_source": getattr(grounded, "grounding_source", "rules"),
            "operation": (
                intent.operation.value
                if (intent and hasattr(intent.operation, "value"))
                else str(getattr(intent, "operation", ""))
            ),
            "target_metrics": list(intent.target_metrics) if intent else [],
            "entities": list(intent.entities) if intent else [],
            "filters": [
                {
                    "column": getattr(f, "field_hint", getattr(f, "column", "")),
                    "op": getattr(f, "operator", getattr(f, "op", "")),
                    "value": getattr(f, "raw_value", getattr(f, "value", "")),
                    "grounded_column": getattr(f, "grounded_column", None),
                    "grounded_value": getattr(f, "grounded_value", None),
                }
                for f in (intent.filters if intent else ())
            ],
            "group_by": list(intent.group_by) if intent else [],
            "top_k": intent.top_k if intent else None,
            "sort_order": intent.sort_order if intent else None,
            "used_llm_fallback": intent.used_llm_fallback if intent else False,
            "fallback_reasons": list(intent.fallback_reasons) if intent else [],
            "primary_table": grounded.selected_schema.primary_table if grounded.selected_schema else None,
            "tables": [getattr(t, "table_name", t) for t in grounded.selected_schema.tables] if grounded.selected_schema else [],
            "coverage_status": (
                grounded.coverage_status.value
                if (grounded.coverage_status and hasattr(grounded.coverage_status, "value"))
                else str(grounded.coverage_status)
            ),
            "is_directly_unanswerable": grounded.is_directly_unanswerable,
            "missing_evidence_proof": (
                {
                    "capability_key": grounded.missing_evidence_proof.capability_key,
                    "missing_fields": list(grounded.missing_evidence_proof.missing_fields),
                    "checked_tables": list(grounded.missing_evidence_proof.checked_tables),
                    "reason": grounded.missing_evidence_proof.reason,
                }
                if grounded.missing_evidence_proof
                else None
            ),
            "resolved_time_ranges": [
                {
                    "raw": tr.raw_expression,
                    "role": tr.date_role.value if hasattr(tr.date_role, "value") else str(tr.date_role),
                    "start": tr.start_date,
                    "end": tr.end_date,
                }
                for tr in grounded.resolved_time_ranges
            ],
            "matched_values": [
                {
                    "raw_text": getattr(mv, "raw_text", ""),
                    "table_name": getattr(mv, "table_name", ""),
                    "column_name": getattr(mv, "column_name", ""),
                    "matched_db_value": getattr(mv, "matched_db_value", None),
                    "match_type": getattr(mv, "match_type", ""),
                    "confidence": getattr(mv, "confidence", 1.0),
                }
                for mv in grounded.matched_values
            ],
            "applicable_rules": list(grounded.applicable_rules),
            "risk_flags": list(grounded.risk_flags),
            "elapsed_ms": elapsed_ms,
            "error": error,
        }
        if isinstance(grounded.planner_input, Mapping):
            req = grounded.planner_input.get("request") or {}
            version = req.get("contract_version")
            if version:
                summary["contract_version"] = version
            if version == "3.0":
                tplan = grounded.planner_input.get("temporal_plan") or {}
                assess = grounded.planner_input.get("assessment") or {}
                summary.update(
                    temporal_intent=grounded.planner_input.get("temporal_intent"),
                    temporal_completeness=tplan.get("completeness_status"),
                    resolved_windows=list(tplan.get("resolved_windows") or ()),
                    metric_mentions=list(grounded.planner_input.get("metric_mentions") or ()),
                    entity_mentions=list(grounded.planner_input.get("entity_mentions") or ()),
                    condition_mentions=list(grounded.planner_input.get("condition_mentions") or ()),
                    validation_status=assess.get("validation_status"),
                    unresolved=list(assess.get("unresolved") or ()),
                    warnings=list(assess.get("warnings") or ()),
                    rejected_claims_count=len(assess.get("rejected_claims") or ()),
                )
        return summary

    @staticmethod
    def _record_grounding_trace(
        output_dir: str | Path | None,
        grounded: GroundedQuestion | None,
        outcome: GateOutcome | None = None,
        elapsed_ms: float | None = None,
    ) -> None:
        if output_dir is None or grounded is None:
            return
        try:
            trace_path = Path(output_dir) / "grounding_trace.jsonl"
            trace_entry: dict[str, Any] = {
                "question_id": grounded.question_id,
                "business_id": grounded.business_id,
                "grounding_source": getattr(grounded, "grounding_source", "rules"),
                "coverage_status": grounded.coverage_status.value,
                "is_directly_unanswerable": grounded.is_directly_unanswerable,
                "operation": grounded.intent.operation.value,
                "target_metrics": list(grounded.intent.target_metrics),
                "primary_table": grounded.selected_schema.primary_table,
                "tables": [t.table_name for t in grounded.selected_schema.tables],
                "resolved_time_ranges": [
                    {
                        "raw": tr.raw_expression,
                        "role": tr.date_role.value,
                        "start": tr.start_date,
                        "end": tr.end_date,
                    }
                    for tr in grounded.resolved_time_ranges
                ],
                "matched_values_count": len(grounded.matched_values),
                "grounding_elapsed_ms": elapsed_ms,
                "decision": outcome.decision if outcome else None,
                "reason_code": outcome.reason_code if outcome else None,
            }
            if isinstance(grounded.planner_input, Mapping):
                version = (grounded.planner_input.get("request") or {}).get("contract_version")
                if version:
                    trace_entry["contract_version"] = version
                if version == "3.0":
                    tplan = grounded.planner_input.get("temporal_plan") or {}
                    assess = grounded.planner_input.get("assessment") or {}
                    trace_entry.update(
                        temporal_intent=grounded.planner_input.get("temporal_intent"),
                        temporal_completeness=tplan.get("completeness_status"),
                        validation_status=assess.get("validation_status"),
                        resolved_windows=list(tplan.get("resolved_windows") or ()),
                        unresolved_count=len(assess.get("unresolved") or ()),
                        metric_mentions=list(grounded.planner_input.get("metric_mentions") or ()),
                        entity_mentions=list(grounded.planner_input.get("entity_mentions") or ()),
                        condition_mentions=list(grounded.planner_input.get("condition_mentions") or ()),
                    )
            with trace_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(trace_entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.debug("Failed to record grounding trace: %s", exc)

    def _record_writer_grounding_trace(
        self,
        writer: SubmissionWriter | None,
        grounded: GroundedQuestion | None,
        outcome: GateOutcome | None,
        elapsed_ms: float | None,
    ) -> None:
        """Record grounding trace when writer exposes an output directory."""
        if writer is None:
            return
        out_dir = getattr(writer, "result_dir", None) or getattr(writer, "output_dir", None)
        if out_dir:
            self._record_grounding_trace(out_dir, grounded, outcome, elapsed_ms)

    def answer_question(
        self,
        question: QuestionMeta | Mapping[str, Any],
        bundle_dir: str | Path,
        *,
        context: Mapping[str, Any] | None = None,
        industry: str | None = None,
        writer: SubmissionWriter | None = None,
        runtime_context: BusinessRuntimeContext | None = None,
    ) -> GateOutcome:
        """Chạy trọn vẹn 1 câu hỏi qua Grounding -> Planner -> Executor -> Gate (với tối đa 1 retry)."""
        if isinstance(question, QuestionMeta):
            q_meta = question
        else:
            q_meta = QuestionMeta(
                id=str(question["id"]),
                business_id=str(question.get("business_id", "")),
                question=str(question["question"]),
                as_of_date=str(question.get("as_of_date", "")),
            )

        bundle_path = Path(bundle_dir)

        # 1. Tải ngữ nghĩa nghiệp vụ (Context)
        grounding_ctx = None
        if runtime_context is not None:
            ctx = dict(context) if context is not None else runtime_context.planner_context
            grounding_ctx = runtime_context.grounding_context
        elif context is not None:
            ctx = dict(context)
            try:
                rt = self.load_runtime_context(bundle_path, expected_business_id=q_meta.business_id or None)
                grounding_ctx = rt.grounding_context
            except Exception:
                try:
                    grounding_ctx = BusinessContextAdapter.from_dict(ctx)
                except Exception:
                    grounding_ctx = None
        else:
            try:
                rt = self.load_runtime_context(bundle_path, expected_business_id=q_meta.business_id or None)
                ctx = rt.planner_context
                grounding_ctx = rt.grounding_context
            except Exception:
                ctx = self.load_context(bundle_path)
                grounding_ctx = None

        resolved_industry = industry or (ctx.get("business_metadata") or {}).get("industry")

        # 2. Phân tích câu hỏi và liên kết dữ liệu (Grounding C1-C5)
        grounded: GroundedQuestion | None = None
        grounded_hint: str | None = None
        grounding_ms: float = 0.0
        grounding_error: str | None = None

        if self.enable_grounding and grounding_ctx is not None:
            t_g0 = time.perf_counter()
            try:
                grounded = self.grounding_runtime.ground_question(
                    question_id=q_meta.id,
                    business_id=q_meta.business_id,
                    question=q_meta.question,
                    as_of_date=q_meta.as_of_date,
                    context=grounding_ctx,
                )
                grounded_hint = self._format_grounded_hint(grounded)
            except Exception as g_exc:
                grounding_error = str(g_exc)
                logger.warning("Grounding failed for %s: %s; falling back to ungrounded planner", q_meta.id, g_exc)
            grounding_ms = self._resolve_grounding_ms(
                q_meta.id, round((time.perf_counter() - t_g0) * 1000.0, 2)
            )

        if writer is not None:
            g_summary = self._build_grounding_summary(grounded, grounding_ms, error=grounding_error)
            writer.record_grounding(q_meta.id, g_summary)

        # Fast-Path: Nếu Grounding C5 xác nhận thiếu dữ liệu không thể trả lời -> đi thẳng vào Gate
        if (
            grounded is not None
            and grounded.is_directly_unanswerable
            and grounded.missing_evidence_proof is not None
        ):
            evidence = GroundingToPlannerAdapter.to_gate_evidence_proof(grounded)
            gate_exec = ExecutionResult(status="not_executed")
            gate_req = GateRequest(
                contract_version=self.gate_contract_version,
                question=q_meta,
                generation=None,
                execution=gate_exec,
                evidence=evidence,
                attempt=0,
            )
            outcome = evaluate_gate(gate_req)
            if writer is not None:
                writer.record_attempt(
                    question_id=q_meta.id,
                    attempt=0,
                    sql="",
                    execution_status="not_executed",
                    error_code=ErrorCode.CONFIRMED_MISSING_EVIDENCE,
                    error_message=grounded.missing_evidence_proof.reason,
                    llm_generation_ms=0.0,
                )
                self._record_writer_grounding_trace(writer, grounded, outcome, grounding_ms)
            return outcome

        if self.voting.enabled:
            entry = dict(q_meta=q_meta, bundle_path=bundle_path, context=ctx,
                         industry=resolved_industry, grounded=grounded, grounded_hint=grounded_hint)
            run_voting(self, [entry], writer)
            outcome = entry["outcome"]
            self._record_writer_grounding_trace(writer, grounded, outcome, grounding_ms)
            return outcome

        # 3. Lập kế hoạch và sinh câu truy vấn SQL (Planner D)
        t_llm0 = time.perf_counter()
        try:
            gen_res = self.generator.generate(
                context=ctx,
                question=q_meta.question,
                as_of_date=q_meta.as_of_date,
                options=self.options,
                industry=resolved_industry,
                grounded_hint=grounded_hint,
            )
            llm_ms0 = round((time.perf_counter() - t_llm0) * 1000.0, 2)
        except Exception as exc:
            llm_ms0 = round((time.perf_counter() - t_llm0) * 1000.0, 2)
            if writer is not None:
                writer.record_attempt(
                    question_id=q_meta.id,
                    attempt=0,
                    sql="",
                    execution_status="error",
                    error_code=ErrorCode.GENERATION_INVALID,
                    error_message=str(exc),
                    generation_diagnostics=diagnostics_dict(exc),
                    llm_generation_ms=llm_ms0,
                )
            outcome = self._abstain_outcome(q_meta.id, str(exc), attempt=0)
            self._record_writer_grounding_trace(writer, grounded, outcome, grounding_ms)
            return outcome

        # 4. Thực thi và Đánh giá (Execution E -> Gate F/G)
        outcome = self._evaluate_attempt(
            q_meta=q_meta,
            bundle_path=bundle_path,
            context=ctx,
            gen_res=gen_res,
            attempt=0,
            llm_generation_ms=llm_ms0,
            grounded=grounded,
            writer=writer,
        )

        # 5. Sửa lỗi có giới hạn (Bounded Repair - tối đa 1 retry)
        if outcome.action == GateAction.RETRY and outcome.repair_request is not None:
            repair_req = outcome.repair_request
            error_feedback = f"[{repair_req.error_type}] {repair_req.error_message}"
            if repair_req.instruction:
                error_feedback = f"{error_feedback}\nHướng dẫn: {repair_req.instruction}"
            t_llm1 = time.perf_counter()
            try:
                repaired_res = self.generator.repair(
                    context=ctx,
                    question=q_meta.question,
                    as_of_date=q_meta.as_of_date,
                    previous_sql=repair_req.failed_sql or (gen_res.sql or ""),
                    error_message=error_feedback,
                    options=self.options,
                    industry=resolved_industry,
                    grounded_hint=grounded_hint,
                    previous_plan=gen_res.structured_plan,
                    error_code=repair_req.error_code or outcome.reason_code,
                    failed_checks=outcome.validation.get("errors", []),
                )
                llm_ms1 = round((time.perf_counter() - t_llm1) * 1000.0, 2)
            except Exception as exc:
                llm_ms1 = round((time.perf_counter() - t_llm1) * 1000.0, 2)
                if writer is not None:
                    writer.record_attempt(
                        question_id=q_meta.id,
                        attempt=1,
                        sql="",
                        execution_status="error",
                        error_code=ErrorCode.GENERATION_INVALID,
                        error_message=str(exc),
                        generation_diagnostics=diagnostics_dict(exc),
                        llm_generation_ms=llm_ms1,
                    )
                outcome = self._abstain_outcome(q_meta.id, str(exc), attempt=1)
                self._record_writer_grounding_trace(writer, grounded, outcome, grounding_ms)
                return outcome

            outcome = self._evaluate_attempt(
                q_meta=q_meta,
                bundle_path=bundle_path,
                context=ctx,
                gen_res=repaired_res,
                attempt=1,
                llm_generation_ms=llm_ms1,
                grounded=grounded,
                writer=writer,
            )

        self._record_writer_grounding_trace(writer, grounded, outcome, grounding_ms)
        return outcome

    def run_questions(
        self,
        questions: Sequence[QuestionMeta | Mapping[str, Any]],
        bundles: Mapping[str, str | Path],
        output_dir: str | Path,
        *,
        batch_size: int = 1,
        verbose: bool = False,
        on_outcomes_flushed: Callable[[Sequence[GateOutcome]], None] | None = None,
    ) -> list[GateOutcome]:
        """Chạy danh sách câu hỏi và ghi kết quả ra submission.jsonl + logs/*.json + detailed_logs.jsonl.

        Hỗ trợ batch_size > 1 để thực hiện suy luận song song (batch inference) trên GPU.
        """
        out_path = Path(output_dir)
        writer = SubmissionWriter(out_path)
        detailed_log_path = out_path / "detailed_logs.jsonl"
        grounding_trace_path = out_path / "grounding_trace.jsonl"
        if not writer.seen_ids:
            if detailed_log_path.exists():
                detailed_log_path.unlink()
            if grounding_trace_path.exists():
                grounding_trace_path.unlink()

        context_cache: dict[str, dict[str, Any]] = {}
        runtime_context_cache: dict[str, BusinessRuntimeContext | None] = {}
        outcomes: list[GateOutcome] = []
        total_q = len(questions)

        def finalize_submission() -> None:
            expected_ids = [
                str(item.id if isinstance(item, QuestionMeta) else item.get("id", ""))
                for item in questions
            ]
            writer.finalize(outcomes, expected_ids=expected_ids)

        if batch_size <= 1 or total_q <= 1:
            for idx, item in enumerate(questions, start=1):
                t0 = time.perf_counter()
                biz_id = item.business_id if isinstance(item, QuestionMeta) else str(item.get("business_id", ""))
                q_id = item.id if isinstance(item, QuestionMeta) else str(item.get("id", ""))
                q_text = item.question if isinstance(item, QuestionMeta) else str(item.get("question", ""))
                as_of = item.as_of_date if isinstance(item, QuestionMeta) else str(item.get("as_of_date", ""))
                if verbose:
                    print(
                        f"\n[{idx}/{total_q}] {q_id} | {biz_id} | as_of={as_of}\n"
                        f"  Câu hỏi : {q_text}",
                        flush=True,
                    )
                bundle_dir = bundles.get(biz_id)
                if bundle_dir is None:
                    outcome = self._abstain_outcome(q_id, f"Missing bundle for business_id={biz_id}", attempt=0)
                else:
                    bundle_key = str(bundle_dir)
                    if bundle_key not in runtime_context_cache:
                        try:
                            runtime_context_cache[bundle_key] = self.load_runtime_context(
                                bundle_dir, expected_business_id=biz_id or None
                            )
                        except Exception:
                            runtime_context_cache[bundle_key] = None

                    rt_ctx = runtime_context_cache[bundle_key]
                    if bundle_key not in context_cache:
                        context_cache[bundle_key] = rt_ctx.planner_context if rt_ctx else self.load_context(bundle_dir)

                    outcome = self.answer_question(
                        question=item,
                        bundle_dir=bundle_dir,
                        context=context_cache[bundle_key],
                        runtime_context=rt_ctx,
                        writer=writer,
                    )
                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                g_summary = writer.audit_logger.get_grounding(q_id)
                writer.write_final(
                    outcome,
                    trace_meta={
                        "business_id": biz_id,
                        "total_elapsed_ms": elapsed_ms,
                        "grounding": g_summary,
                    },
                )
                attempts_history = writer.audit_logger.get_history(q_id)
                if verbose:
                    for att in attempts_history:
                        att_no = att.get("attempt", 0)
                        sql_preview = (att.get("sql") or "").replace("\n", " ").strip()
                        print(
                            f"  Attempt {att_no}: status={att.get('execution_status')} | SQL: {sql_preview[:140]}",
                            flush=True,
                        )
                        if att.get("error_message"):
                            print(f"    -> Lỗi: {att.get('error_message')}", flush=True)
                    ans_dict = outcome.final_answer.to_submission_dict() if outcome.final_answer else None
                    print(
                        f"  => Kết quả ({elapsed_ms:.0f} ms): decision={outcome.decision} "
                        f"({outcome.reason_code}) | {ans_dict}",
                        flush=True,
                    )
                detailed_entry = {
                    "id": q_id,
                    "business_id": biz_id,
                    "question": q_text,
                    "as_of_date": as_of,
                    "decision": outcome.decision,
                    "reason_code": outcome.reason_code,
                    "retry_count": outcome.retry_count,
                    "total_elapsed_ms": elapsed_ms,
                    "final_answer": outcome.final_answer.to_submission_dict() if outcome.final_answer else None,
                    "voting": outcome.voting,
                    "grounding": g_summary,
                    "attempts": attempts_history,
                }
                with detailed_log_path.open("a", encoding="utf-8") as df:
                    df.write(json.dumps(detailed_entry, ensure_ascii=False) + "\n")
                outcomes.append(outcome)
                if on_outcomes_flushed is not None:
                    on_outcomes_flushed([outcome])

            finalize_submission()
            return outcomes

        # === Chế độ Batch Processing trên GPU (batch_size > 1) ===
        for chunk_start in range(0, total_q, batch_size):
            chunk_items = list(questions[chunk_start : chunk_start + batch_size])
            chunk_prepared: list[dict[str, Any]] = []

            for item in chunk_items:
                if isinstance(item, QuestionMeta):
                    q_meta = item
                else:
                    q_meta = QuestionMeta(
                        id=str(item["id"]),
                        business_id=str(item.get("business_id", "")),
                        question=str(item["question"]),
                        as_of_date=str(item.get("as_of_date", "")),
                    )
                biz_id = q_meta.business_id
                bundle_dir = bundles.get(biz_id)
                if bundle_dir is None:
                    chunk_prepared.append({
                        "q_meta": q_meta,
                        "bundle_path": None,
                        "context": None,
                        "industry": None,
                        "grounded": None,
                        "grounded_hint": None,
                        "grounding_ms": 0.0,
                        "outcome": self._abstain_outcome(q_meta.id, f"Missing bundle for business_id={biz_id}", attempt=0),
                        "t0": time.perf_counter(),
                    })
                else:
                    bundle_path = Path(bundle_dir)
                    bundle_key = str(bundle_dir)
                    if bundle_key not in runtime_context_cache:
                        try:
                            runtime_context_cache[bundle_key] = self.load_runtime_context(
                                bundle_dir, expected_business_id=biz_id or None
                            )
                        except Exception:
                            runtime_context_cache[bundle_key] = None

                    rt_ctx = runtime_context_cache[bundle_key]
                    if bundle_key not in context_cache:
                        context_cache[bundle_key] = rt_ctx.planner_context if rt_ctx else self.load_context(bundle_dir)

                    ctx = context_cache[bundle_key]
                    grounding_ctx = rt_ctx.grounding_context if rt_ctx else None
                    resolved_ind = (ctx.get("business_metadata") or {}).get("industry")

                    # Chạy Grounding C1-C5
                    grounded_res: GroundedQuestion | None = None
                    grounded_hint_str: str | None = None
                    g_ms: float = 0.0
                    g_err_msg: str | None = None
                    fast_outcome: GateOutcome | None = None

                    if self.enable_grounding and grounding_ctx is not None:
                        t_g0 = time.perf_counter()
                        try:
                            grounded_res = self.grounding_runtime.ground_question(
                                question_id=q_meta.id,
                                business_id=q_meta.business_id,
                                question=q_meta.question,
                                as_of_date=q_meta.as_of_date,
                                context=grounding_ctx,
                            )
                            grounded_hint_str = self._format_grounded_hint(grounded_res)
                        except Exception as g_err:
                            g_err_msg = str(g_err)
                            logger.warning("Grounding failed for %s: %s", q_meta.id, g_err)
                        g_ms = self._resolve_grounding_ms(
                            q_meta.id, round((time.perf_counter() - t_g0) * 1000.0, 2)
                        )

                    g_summary = self._build_grounding_summary(grounded_res, g_ms, error=g_err_msg)
                    writer.record_grounding(q_meta.id, g_summary)

                    # Fast-path check unanswerable
                    if (
                        grounded_res is not None
                        and grounded_res.is_directly_unanswerable
                        and grounded_res.missing_evidence_proof is not None
                    ):
                        evidence = GroundingToPlannerAdapter.to_gate_evidence_proof(grounded_res)
                        gate_exec = ExecutionResult(status="not_executed")
                        gate_req = GateRequest(
                            contract_version=self.gate_contract_version,
                            question=q_meta,
                            generation=None,
                            execution=gate_exec,
                            evidence=evidence,
                            attempt=0,
                        )
                        fast_outcome = evaluate_gate(gate_req)
                        writer.record_attempt(
                            question_id=q_meta.id,
                            attempt=0,
                            sql="",
                            execution_status="not_executed",
                            error_code=ErrorCode.CONFIRMED_MISSING_EVIDENCE,
                            error_message=grounded_res.missing_evidence_proof.reason,
                            llm_generation_ms=0.0,
                        )

                    chunk_prepared.append({
                        "q_meta": q_meta,
                        "bundle_path": bundle_path,
                        "context": ctx,
                        "industry": resolved_ind,
                        "grounded": grounded_res,
                        "grounded_hint": grounded_hint_str,
                        "grounding_ms": g_ms,
                        "grounding_summary": g_summary,
                        "outcome": fast_outcome,
                        "t0": time.perf_counter(),
                    })

            # 1. Batch Generation: Attempt 0 (cho những câu chưa giải bằng fast-path)
            valid_for_gen = [entry for entry in chunk_prepared if entry["outcome"] is None]
            if valid_for_gen and self.voting.enabled:
                run_voting(self, valid_for_gen, writer)
                valid_for_gen = []
            if valid_for_gen:
                gen_inputs = [
                    {
                        "context": entry["context"],
                        "question": entry["q_meta"].question,
                        "as_of_date": entry["q_meta"].as_of_date,
                        "industry": entry["industry"],
                        "grounded_hint": entry.get("grounded_hint"),
                    }
                    for entry in valid_for_gen
                ]
                t_b0 = time.perf_counter()
                try:
                    gen_results: list[Any] = self.generator.generate_batch(gen_inputs, options=self.options)
                    gen_results = self._pad_batch_results(gen_results, len(valid_for_gen))
                    per_item_llm_ms0 = round(((time.perf_counter() - t_b0) * 1000.0) / max(len(valid_for_gen), 1), 2)
                except Exception as batch_error:
                    for entry in valid_for_gen:
                        entry["batch_fallback_0"] = diagnostics_dict(batch_error)
                    gen_results = []
                    for entry in valid_for_gen:
                        try:
                            t_indiv = time.perf_counter()
                            gr = self.generator.generate(
                                context=entry["context"],
                                question=entry["q_meta"].question,
                                as_of_date=entry["q_meta"].as_of_date,
                                options=self.options,
                                industry=entry["industry"],
                                grounded_hint=entry.get("grounded_hint"),
                            )
                            entry["indiv_llm_ms"] = round((time.perf_counter() - t_indiv) * 1000.0, 2)
                            gen_results.append(gr)
                        except Exception as err:
                            entry["indiv_llm_ms"] = round((time.perf_counter() - t_indiv) * 1000.0, 2)
                            gen_results.append(err)
                    per_item_llm_ms0 = None

                # 2. Evaluate Attempt 0 trong DuckDB & Output Gate
                repair_needed: list[dict[str, Any]] = []
                for entry, gr in zip(valid_for_gen, gen_results):
                    llm_dur0 = entry.get("indiv_llm_ms", per_item_llm_ms0)
                    if isinstance(gr, Exception):
                        writer.record_attempt(
                            question_id=entry["q_meta"].id,
                            attempt=0,
                            sql="",
                            execution_status="error",
                            error_code=ErrorCode.GENERATION_INVALID,
                            error_message=str(gr),
                            generation_diagnostics=diagnostics_dict(gr),
                            batch_fallback_error=entry.get("batch_fallback_0"),
                            llm_generation_ms=llm_dur0,
                        )
                        repair_req = RepairRequest(
                            attempt=1,
                            failed_sql="",
                            error_type="JSON_OR_SQL_PARSE_ERROR",
                            error_message=str(gr),
                            error_code=ErrorCode.GENERATION_INVALID,
                            instruction=(
                                "Bạn chưa xuất khối JSON hợp lệ theo định dạng quy định. "
                                "Hãy xuất trực tiếp khối ```json ... ``` gồm 'status', 'answer_type', 'sql' "
                                "mà không thêm văn bản dẫn dắt hay giải thích bên ngoài."
                            ),
                        )
                        entry["outcome"] = GateOutcome(
                            action=GateAction.RETRY,
                            question_id=entry["q_meta"].id,
                            decision="retry",
                            reason_code="GENERATION_INVALID",
                            repair_request=repair_req,
                            retry_count=0,
                        )
                        repair_needed.append(entry)
                    else:
                        entry["gen_res_0"] = gr
                        outcome_0 = self._evaluate_attempt(
                            q_meta=entry["q_meta"],
                            bundle_path=entry["bundle_path"],
                            context=entry["context"],
                            gen_res=gr,
                            attempt=0,
                            llm_generation_ms=llm_dur0,
                            batch_fallback_error=entry.get("batch_fallback_0"),
                            grounded=entry.get("grounded"),
                            writer=writer,
                        )
                        entry["outcome"] = outcome_0
                        if outcome_0.action == GateAction.RETRY and outcome_0.repair_request is not None:
                            repair_needed.append(entry)

                # 3. Batch Repair: Attempt 1 (cho các câu hỏi cần retry)
                if repair_needed:
                    repair_inputs: list[dict[str, Any]] = []
                    for entry in repair_needed:
                        repair_req = entry["outcome"].repair_request
                        error_feedback = f"[{repair_req.error_type}] {repair_req.error_message}"
                        if repair_req.instruction:
                            error_feedback = f"{error_feedback}\nHướng dẫn: {repair_req.instruction}"
                        gen_0 = entry.get("gen_res_0")
                        prev_sql = repair_req.failed_sql or (gen_0.sql or "" if gen_0 is not None else "")
                        repair_inputs.append({
                            "context": entry["context"],
                            "question": entry["q_meta"].question,
                            "as_of_date": entry["q_meta"].as_of_date,
                            "previous_sql": prev_sql,
                            "error_message": error_feedback,
                            "industry": entry["industry"],
                            "grounded_hint": entry.get("grounded_hint"),
                            "previous_plan": gen_0.structured_plan if gen_0 is not None else None,
                            "error_code": repair_req.error_code or entry["outcome"].reason_code,
                            "failed_checks": list(entry["outcome"].validation.get("errors", [])),
                        })
                    t_b1 = time.perf_counter()
                    try:
                        repaired_results: list[Any] = self.generator.repair_batch(repair_inputs, options=self.options)
                        repaired_results = self._pad_batch_results(repaired_results, len(repair_needed))
                        per_item_llm_ms1 = round(((time.perf_counter() - t_b1) * 1000.0) / max(len(repair_needed), 1), 2)
                    except Exception as batch_error:
                        for entry in repair_needed:
                            entry["batch_fallback_1"] = diagnostics_dict(batch_error)
                        repaired_results = []
                        for entry, r_inp in zip(repair_needed, repair_inputs):
                            try:
                                t_indiv1 = time.perf_counter()
                                r_res = self.generator.repair(**r_inp, options=self.options)
                                entry["indiv_llm_ms1"] = round((time.perf_counter() - t_indiv1) * 1000.0, 2)
                                repaired_results.append(r_res)
                            except Exception as err:
                                entry["indiv_llm_ms1"] = round((time.perf_counter() - t_indiv1) * 1000.0, 2)
                                repaired_results.append(err)
                        per_item_llm_ms1 = None

                    for entry, r_res in zip(repair_needed, repaired_results):
                        llm_dur1 = entry.get("indiv_llm_ms1", per_item_llm_ms1)
                        if isinstance(r_res, Exception):
                            writer.record_attempt(
                                question_id=entry["q_meta"].id,
                                attempt=1,
                                sql="",
                                execution_status="error",
                                error_code=ErrorCode.GENERATION_INVALID,
                                error_message=str(r_res),
                                generation_diagnostics=diagnostics_dict(r_res),
                                batch_fallback_error=entry.get("batch_fallback_1"),
                                llm_generation_ms=llm_dur1,
                            )
                            entry["outcome"] = self._abstain_outcome(entry["q_meta"].id, str(r_res), attempt=1)
                        else:
                            outcome_1 = self._evaluate_attempt(
                                q_meta=entry["q_meta"],
                                bundle_path=entry["bundle_path"],
                                context=entry["context"],
                                gen_res=r_res,
                                attempt=1,
                                llm_generation_ms=llm_dur1,
                                batch_fallback_error=entry.get("batch_fallback_1"),
                                grounded=entry.get("grounded"),
                                writer=writer,
                            )
                            entry["outcome"] = outcome_1

            # 4. Ghi nhận kết quả và logs cho từng câu theo đúng thứ tự
            chunk_outcomes: list[GateOutcome] = []
            for entry in chunk_prepared:
                q_meta = entry["q_meta"]
                outcome = entry["outcome"]
                if outcome is None:
                    outcome = self._abstain_outcome(q_meta.id, "Không có kết quả xử lý", attempt=0, code=ErrorCode.UNKNOWN_ERROR)
                elapsed_ms = round((time.perf_counter() - entry["t0"]) * 1000.0, 2)
                g_summary = entry.get("grounding_summary") or writer.audit_logger.get_grounding(q_meta.id)
                writer.write_final(
                    outcome,
                    trace_meta={
                        "business_id": q_meta.business_id,
                        "total_elapsed_ms": elapsed_ms,
                        "grounding": g_summary,
                    },
                )
                self._record_grounding_trace(
                    out_path,
                    entry.get("grounded"),
                    outcome,
                    entry.get("grounding_ms"),
                )
                attempts_history = writer.audit_logger.get_history(q_meta.id)
                if verbose:
                    global_idx = len(outcomes) + 1
                    print(
                        f"\n[{global_idx}/{total_q}] {q_meta.id} | {q_meta.business_id} | as_of={q_meta.as_of_date}\n"
                        f"  Câu hỏi : {q_meta.question}",
                        flush=True,
                    )
                    for att in attempts_history:
                        att_no = att.get("attempt", 0)
                        sql_preview = (att.get("sql") or "").replace("\n", " ").strip()
                        print(
                            f"  Attempt {att_no}: status={att.get('execution_status')} | SQL: {sql_preview[:140]}",
                            flush=True,
                        )
                        if att.get("error_message"):
                            print(f"    -> Lỗi: {att.get('error_message')}", flush=True)
                    ans_dict = outcome.final_answer.to_submission_dict() if outcome.final_answer else None
                    print(
                        f"  => Kết quả ({elapsed_ms:.0f} ms): decision={outcome.decision} "
                        f"({outcome.reason_code}) | {ans_dict}",
                        flush=True,
                    )
                detailed_entry = {
                    "id": q_meta.id,
                    "business_id": q_meta.business_id,
                    "question": q_meta.question,
                    "as_of_date": q_meta.as_of_date,
                    "decision": outcome.decision,
                    "reason_code": outcome.reason_code,
                    "retry_count": outcome.retry_count,
                    "total_elapsed_ms": elapsed_ms,
                    "final_answer": outcome.final_answer.to_submission_dict() if outcome.final_answer else None,
                    "voting": outcome.voting,
                    "grounding": g_summary,
                    "attempts": attempts_history,
                }
                with detailed_log_path.open("a", encoding="utf-8") as df:
                    df.write(json.dumps(detailed_entry, ensure_ascii=False) + "\n")
                outcomes.append(outcome)
                chunk_outcomes.append(outcome)
            if on_outcomes_flushed is not None and chunk_outcomes:
                on_outcomes_flushed(chunk_outcomes)

        finalize_submission()
        return outcomes

    def _evaluate_attempt(
        self,
        *,
        q_meta: QuestionMeta,
        attempt: int,
        writer: SubmissionWriter | None = None,
        **kwargs: Any,
    ) -> GateOutcome:
        """Đánh giá 1 attempt; mọi ngoại lệ ngoài dự kiến được chuyển thành abstain thay vì làm sập cả lượt chạy."""
        try:
            return self._evaluate_attempt_unsafe(q_meta=q_meta, attempt=attempt, writer=writer, **kwargs)
        except Exception as exc:
            logger.exception("Lỗi nội bộ khi đánh giá %s (attempt %s)", q_meta.id, attempt)
            if writer is not None:
                try:
                    writer.record_attempt(
                        question_id=q_meta.id,
                        attempt=attempt,
                        sql="",
                        execution_status="error",
                        error_code=ErrorCode.UNKNOWN_ERROR,
                        error_message=f"{type(exc).__name__}: {exc}",
                        candidate_id=kwargs.get("candidate_id"),
                        round_id=kwargs.get("round_id"),
                    )
                except Exception:
                    logger.exception("Không ghi được attempt lỗi cho %s", q_meta.id)
            return self._abstain_outcome(q_meta.id, f"{type(exc).__name__}: {exc}", attempt=attempt, code=ErrorCode.UNKNOWN_ERROR)

    def _evaluate_attempt_unsafe(
        self,
        *,
        q_meta: QuestionMeta,
        bundle_path: Path,
        context: Mapping[str, Any],
        gen_res: Text2SQLResult,
        attempt: int,
        max_retries: int = 1,
        candidate_id: int | None = None,
        round_id: int | None = None,
        llm_generation_ms: float | None = None,
        batch_fallback_error: dict[str, Any] | None = None,
        grounded: GroundedQuestion | None = None,
        writer: SubmissionWriter | None = None,
    ) -> GateOutcome:
        if gen_res.status == "needs_more_context":
            requested = ", ".join(gen_res.requested_context)
            reason_text = gen_res.reason or (
                f"Requested extra context: {requested}" if requested else "Model requested more context"
            )
            if attempt < max_retries:
                outcome = GateOutcome(
                    action=GateAction.RETRY,
                    question_id=q_meta.id,
                    decision=Decision.RETRY,
                    reason_code=ErrorCode.MISSING_EVIDENCE,
                    validation={"passed": False, "errors": [ErrorCode.MISSING_EVIDENCE], "warnings": []},
                    retry_count=attempt,
                    repair_request=RepairRequest(
                        attempt=attempt + 1,
                        failed_sql="",
                        error_type="NEEDS_MORE_CONTEXT",
                        error_message=reason_text,
                        error_code=ErrorCode.MISSING_EVIDENCE,
                        instruction=(
                            "Toàn bộ schema, cột, liên kết và quy tắc khả dụng đã được cung cấp đầy đủ trong context. "
                            "Không trả status='needs_more_context'; hãy dùng thông tin trong context để trả "
                            "status='answerable' kèm SQL, hoặc status='unanswerable' nếu thực sự thiếu dữ liệu."
                        ),
                    ),
                )
            else:
                outcome = self._abstain_outcome(q_meta.id, reason_text, attempt=attempt, code=ErrorCode.RETRY_EXHAUSTED)
            if writer is not None:
                writer.record_attempt(
                    question_id=q_meta.id,
                    attempt=attempt,
                    sql="",
                    execution_status="not_executed",
                    error_code=outcome.reason_code,
                    error_message=reason_text,
                    thinking=gen_res.thinking,
                    generation_diagnostics=diagnostics_dict(gen_res),
                    batch_fallback_error=batch_fallback_error,
                    candidate_id=candidate_id,
                    round_id=round_id,
                    llm_generation_ms=llm_generation_ms,
                )
            return outcome

        gate_gen = gen_res.to_gate_generation_result()
        if gen_res.status == "unanswerable":
            gate_exec = ExecutionResult(status="not_executed")
            evidence = gen_res.to_gate_evidence_proof(context)
        else:
            if grounded is not None:
                evidence = GroundingToPlannerAdapter.to_gate_evidence_proof(grounded)
            else:
                evidence = gen_res.to_gate_evidence_proof(context)
            exec_req = ExecutionRequest(
                question_id=q_meta.id,
                db_path=str(bundle_path),
                sql_query=gen_res.sql or "",
                answer_type=gate_gen.answer_type,
                retry_count=attempt,
                max_retries=max_retries,
                timeout_sec=self.timeout_sec,
                max_rows=self.max_rows,
            )
            exec_resp = execute_query(exec_req)
            gate_exec = exec_resp.to_gate_execution_result()

        gate_req = GateRequest(
            contract_version=self.gate_contract_version,
            question=q_meta,
            generation=gate_gen,
            execution=gate_exec,
            evidence=evidence,
            attempt=attempt,
            max_retries=max_retries,
        )
        outcome = evaluate_gate(gate_req)
        if writer is not None:
            err_msg = gate_exec.error.message if gate_exec.error else (gen_res.reason if gen_res.status == "unanswerable" else None)
            writer.record_attempt(
                question_id=q_meta.id,
                attempt=attempt,
                sql=gen_res.sql or "",
                execution_status=gate_exec.status,
                error_code=outcome.reason_code if outcome.decision != Decision.ANSWER else None,
                execution_ms=gate_exec.elapsed_ms,
                row_count=gate_exec.row_count,
                thinking=gen_res.thinking,
                generation_diagnostics=diagnostics_dict(gen_res),
                batch_fallback_error=batch_fallback_error,
                candidate_id=candidate_id,
                round_id=round_id,
                assumptions=list(gen_res.assumptions) if gen_res.assumptions else None,
                error_message=err_msg,
                llm_generation_ms=llm_generation_ms,
            )
        return outcome

    @staticmethod
    def _pad_batch_results(results: list[Any], expected: int) -> list[Any]:
        """Đảm bảo số kết quả batch khớp số đầu vào (tránh `zip` âm thầm cắt bớt câu hỏi)."""
        results = list(results)
        if len(results) != expected:
            logger.error("Batch trả về %d kết quả cho %d đầu vào", len(results), expected)
        if len(results) < expected:
            results += [RuntimeError("Batch inference trả thiếu kết quả")] * (expected - len(results))
        return results[:expected]

    @staticmethod
    def _abstain_outcome(question_id: str, error_detail: str, attempt: int, code: str | None = None) -> GateOutcome:
        code = code or (ErrorCode.RETRY_EXHAUSTED if attempt >= 1 else ErrorCode.GENERATION_INVALID)
        return GateOutcome(
            action=GateAction.FINAL,
            question_id=question_id,
            decision=Decision.ABSTAIN,
            final_answer=FinalAnswer(id=question_id, type=AnswerType.ABSTAIN),
            reason_code=code,
            validation={"passed": False, "errors": [code], "warnings": [error_detail]},
            retry_count=attempt,
            repair_request=None,
        )


B0Pipeline = DataMatePipeline
Pipeline = DataMatePipeline

__all__ = [
    "DataMatePipeline",
    "Pipeline",
    "B0Pipeline",
]
