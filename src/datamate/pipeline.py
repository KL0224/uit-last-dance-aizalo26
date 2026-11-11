"""End-to-End Orchestrator for DataMate 2026 B0 Baseline (B0.1 -> B0.2 -> B0.3 -> B0.4 -> B0.5)."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

from datamate.ingestion.ingestion import PreparedBusinessArtifacts, prepare_business
from datamate.planner.diagnostics import diagnostics_dict
from datamate.planner.errors import LLMError
from datamate.planner.generator import Text2SQLGenerator
from datamate.planner.types import GenerationOptions, Text2SQLResult
from datamate.execution import ExecutionRequest, execute_query
from datamate.gate import SubmissionWriter, evaluate_gate
from datamate.gate.contracts import (
    AnswerType,
    Decision,
    ExecutionResult,
    FinalAnswer,
    GateAction,
    GateOutcome,
    GateRequest,
    QuestionMeta,
    RepairRequest,
)
from datamate.gate.errors import ErrorCode


class B0Pipeline:
    """Điều phối luồng B0 End-to-End: B0.1/B0.2 -> B0.3 -> B0.4 -> B0.5 (với 1 lần Bounded Retry)."""

    def __init__(
        self,
        generator: Text2SQLGenerator,
        *,
        timeout_sec: float = 10.0,
        max_rows: int = 10000,
        options: GenerationOptions | None = None,
    ) -> None:
        self.generator = generator
        self.timeout_sec = timeout_sec
        self.max_rows = max_rows
        self.options = options

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
        """Chuẩn bị bundle B0.1 + B0.2 cho một thư mục doanh nghiệp."""
        return prepare_business(
            business_dir=business_dir,
            output_dir=output_dir,
            rulebook=rulebook,
            calendar=calendar,
            relationships=relationships,
            config=config,
        )

    @staticmethod
    def load_context(bundle_dir: str | Path) -> dict[str, Any]:
        """Đọc business_context.json từ thư mục bundle và bổ sung profiling + join graph nếu có data.duckdb."""
        bundle_path = Path(bundle_dir)
        context_path = bundle_path / "business_context.json"
        ctx = json.loads(context_path.read_text(encoding="utf-8"))
        db_path = bundle_path / "data.duckdb"
        if db_path.is_file():
            try:
                import duckdb
                with duckdb.connect(str(db_path), read_only=True) as con:
                    cat_samples: dict[str, dict[str, list[Any]]] = {}
                    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
                    cols_by_tbl: dict[str, list[str]] = {}
                    for tname in tables:
                        cat_samples[tname] = {}
                        cols = con.execute(f"DESCRIBE {tname}").fetchall()
                        cols_by_tbl[tname] = [c[0] for c in cols]
                        for cname, ctype, *_ in cols:
                            if cname.startswith("__dm_"):
                                continue
                            if ctype in ("VARCHAR", "BOOLEAN") or "INT" in ctype:
                                try:
                                    cnt = con.execute(f'SELECT COUNT(DISTINCT "{cname}") FROM {tname}').fetchone()[0]
                                    if 0 < cnt <= 12:
                                        vals = [r[0] for r in con.execute(f'SELECT DISTINCT "{cname}" FROM {tname} WHERE "{cname}" IS NOT NULL LIMIT 12').fetchall()]
                                        cat_samples[tname][cname] = vals
                                except Exception:
                                    pass
                    ctx["categorical_samples"] = cat_samples

                    schema_cat = ctx.get("schema_catalog", {})
                    existing_edges = schema_cat.get("join_graph") or schema_cat.get("join_edges") or []
                    if not existing_edges:
                        discovered_edges = []
                        id_keywords = ("id", "ma_", "so_", "sku", "code", "hd")
                        for i, t1 in enumerate(tables):
                            for c1 in cols_by_tbl[t1]:
                                if c1.startswith("__dm_") or not any(k in c1.lower() for k in id_keywords):
                                    continue
                                for t2 in tables[i + 1:]:
                                    for c2 in cols_by_tbl[t2]:
                                        if c2.startswith("__dm_") or not any(k in c2.lower() for k in id_keywords):
                                            continue
                                        try:
                                            overlap = con.execute(
                                                f'SELECT COUNT(*) FROM {t1} JOIN {t2} ON {t1}."{c1}" = {t2}."{c2}"'
                                            ).fetchone()[0]
                                            if overlap > 0:
                                                discovered_edges.append({
                                                    "left_table": t1,
                                                    "left_column": c1,
                                                    "right_table": t2,
                                                    "right_column": c2,
                                                    "cardinality": "many_to_one",
                                                    "status": "validated",
                                                    "confidence": 0.9,
                                                    "overlap": overlap,
                                                })
                                        except Exception:
                                            pass
                        discovered_edges.sort(key=lambda x: -x["overlap"])
                        schema_cat["join_graph"] = discovered_edges
            except Exception:
                pass
        return ctx

    def answer_question(
        self,
        question: QuestionMeta | Mapping[str, Any],
        bundle_dir: str | Path,
        *,
        context: Mapping[str, Any] | None = None,
        industry: str | None = None,
        writer: SubmissionWriter | None = None,
    ) -> GateOutcome:
        """Chạy trọn vẹn 1 câu hỏi từ B0.3 -> B0.4 -> B0.5 (kèm tối đa 1 lần retry)."""
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
        ctx = dict(context) if context is not None else self.load_context(bundle_path)
        resolved_industry = industry or (ctx.get("business_metadata") or {}).get("industry")

        t_llm0 = time.perf_counter()
        try:
            gen_res = self.generator.generate(
                context=ctx,
                question=q_meta.question,
                as_of_date=q_meta.as_of_date,
                options=self.options,
                industry=resolved_industry,
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
            return self._abstain_outcome(q_meta.id, str(exc), attempt=0)

        outcome = self._evaluate_attempt(
            q_meta=q_meta,
            bundle_path=bundle_path,
            context=ctx,
            gen_res=gen_res,
            attempt=0,
            llm_generation_ms=llm_ms0,
            writer=writer,
        )

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
                return self._abstain_outcome(q_meta.id, str(exc), attempt=1)

            outcome = self._evaluate_attempt(
                q_meta=q_meta,
                bundle_path=bundle_path,
                context=ctx,
                gen_res=repaired_res,
                attempt=1,
                llm_generation_ms=llm_ms1,
                writer=writer,
            )

        return outcome

    def run_questions(
        self,
        questions: Sequence[QuestionMeta | Mapping[str, Any]],
        bundles: Mapping[str, str | Path],
        output_dir: str | Path,
        *,
        batch_size: int = 1,
        verbose: bool = False,
    ) -> list[GateOutcome]:
        """Chạy danh sách câu hỏi và ghi kết quả ra submission.jsonl + logs/*.json + detailed_logs.jsonl.

        Hỗ trợ batch_size > 1 để thực hiện suy luận song song (batch inference) trên GPU lớn như A100.
        """
        out_path = Path(output_dir)
        writer = SubmissionWriter(out_path)
        detailed_log_path = out_path / "detailed_logs.jsonl"
        context_cache: dict[str, dict[str, Any]] = {}
        outcomes: list[GateOutcome] = []
        total_q = len(questions)

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
                    if bundle_key not in context_cache:
                        context_cache[bundle_key] = self.load_context(bundle_dir)
                    outcome = self.answer_question(
                        question=item,
                        bundle_dir=bundle_dir,
                        context=context_cache[bundle_key],
                        writer=writer,
                    )
                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                writer.write_final(
                    outcome,
                    trace_meta={"business_id": biz_id, "total_elapsed_ms": elapsed_ms},
                )
                attempts_history = writer.audit_logger._history.get(q_id, [])
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
                    "attempts": attempts_history,
                }
                with detailed_log_path.open("a", encoding="utf-8") as df:
                    df.write(json.dumps(detailed_entry, ensure_ascii=False) + "\n")
                outcomes.append(outcome)

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
                        "outcome": self._abstain_outcome(q_meta.id, f"Missing bundle for business_id={biz_id}", attempt=0),
                        "t0": time.perf_counter(),
                    })
                else:
                    bundle_path = Path(bundle_dir)
                    bundle_key = str(bundle_dir)
                    if bundle_key not in context_cache:
                        context_cache[bundle_key] = self.load_context(bundle_dir)
                    ctx = context_cache[bundle_key]
                    resolved_ind = (ctx.get("business_metadata") or {}).get("industry")
                    chunk_prepared.append({
                        "q_meta": q_meta,
                        "bundle_path": bundle_path,
                        "context": ctx,
                        "industry": resolved_ind,
                        "outcome": None,
                        "t0": time.perf_counter(),
                    })

            # 1. Batch Generation: Attempt 0
            valid_for_gen = [entry for entry in chunk_prepared if entry["outcome"] is None]
            if valid_for_gen:
                gen_inputs = [
                    {
                        "context": entry["context"],
                        "question": entry["q_meta"].question,
                        "as_of_date": entry["q_meta"].as_of_date,
                        "industry": entry["industry"],
                    }
                    for entry in valid_for_gen
                ]
                t_b0 = time.perf_counter()
                try:
                    gen_results: list[Any] = self.generator.generate_batch(gen_inputs, options=self.options)
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
                        # Cho phép Bounded Retry (Attempt 1) để cứu vãn lỗi parse
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
                        prev_sql = repair_req.failed_sql or ((entry.get("gen_res_0") or None) and entry["gen_res_0"].sql or "")
                        repair_inputs.append({
                            "context": entry["context"],
                            "question": entry["q_meta"].question,
                            "as_of_date": entry["q_meta"].as_of_date,
                            "previous_sql": prev_sql,
                            "error_message": error_feedback,
                            "industry": entry["industry"],
                        })
                    t_b1 = time.perf_counter()
                    try:
                        repaired_results: list[Any] = self.generator.repair_batch(repair_inputs, options=self.options)
                        per_item_llm_ms1 = round(((time.perf_counter() - t_b1) * 1000.0) / max(len(repair_needed), 1), 2)
                    except Exception as batch_error:
                        for entry in repair_needed:
                            entry["batch_fallback_1"] = diagnostics_dict(batch_error)
                        repaired_results = []
                        for entry, r_inp in zip(repair_needed, repair_inputs):
                            try:
                                t_indiv1 = time.perf_counter()
                                r_res = self.generator.repair(
                                    context=r_inp["context"],
                                    question=r_inp["question"],
                                    as_of_date=r_inp["as_of_date"],
                                    previous_sql=r_inp["previous_sql"],
                                    error_message=r_inp["error_message"],
                                    options=self.options,
                                    industry=r_inp["industry"],
                                )
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
                                writer=writer,
                            )
                            entry["outcome"] = outcome_1

            # 4. Ghi nhận kết quả và logs cho từng câu theo đúng thứ tự
            for entry in chunk_prepared:
                q_meta = entry["q_meta"]
                outcome = entry["outcome"]
                elapsed_ms = round((time.perf_counter() - entry["t0"]) * 1000.0, 2)
                writer.write_final(
                    outcome,
                    trace_meta={"business_id": q_meta.business_id, "total_elapsed_ms": elapsed_ms},
                )
                attempts_history = writer.audit_logger._history.get(q_meta.id, [])
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
                    "attempts": attempts_history,
                }
                with detailed_log_path.open("a", encoding="utf-8") as df:
                    df.write(json.dumps(detailed_entry, ensure_ascii=False) + "\n")
                outcomes.append(outcome)

        return outcomes

    def _evaluate_attempt(
        self,
        *,
        q_meta: QuestionMeta,
        bundle_path: Path,
        context: Mapping[str, Any],
        gen_res: Text2SQLResult,
        attempt: int,
        llm_generation_ms: float | None = None,
        batch_fallback_error: dict[str, Any] | None = None,
        writer: SubmissionWriter | None = None,
    ) -> GateOutcome:
        b05_gen = gen_res.to_b05_generation_result()
        evidence = gen_res.to_b05_evidence_proof(context)

        if gen_res.status == "unanswerable":
            b05_exec = ExecutionResult(status="not_executed")
        else:
            exec_req = ExecutionRequest(
                question_id=q_meta.id,
                db_path=str(bundle_path),
                sql_query=gen_res.sql or "",
                answer_type=b05_gen.answer_type,
                retry_count=attempt,
                max_retries=1,
                timeout_sec=self.timeout_sec,
                max_rows=self.max_rows,
            )
            exec_resp = execute_query(exec_req)
            b05_exec = exec_resp.to_b05_execution_result()

        gate_req = GateRequest(
            contract_version="b05.v1",
            question=q_meta,
            generation=b05_gen,
            execution=b05_exec,
            evidence=evidence,
            attempt=attempt,
        )
        outcome = evaluate_gate(gate_req)
        if writer is not None:
            err_msg = b05_exec.error.message if b05_exec.error else (gen_res.reason if gen_res.status == "unanswerable" else None)
            writer.record_attempt(
                question_id=q_meta.id,
                attempt=attempt,
                sql=gen_res.sql or "",
                execution_status=b05_exec.status,
                error_code=outcome.reason_code if outcome.decision != Decision.ANSWER else None,
                execution_ms=b05_exec.elapsed_ms,
                row_count=b05_exec.row_count,
                thinking=gen_res.thinking,
                generation_diagnostics=diagnostics_dict(gen_res),
                batch_fallback_error=batch_fallback_error,
                assumptions=list(gen_res.assumptions) if gen_res.assumptions else None,
                error_message=err_msg,
                llm_generation_ms=llm_generation_ms,
            )
        return outcome

    @staticmethod
    def _abstain_outcome(question_id: str, error_detail: str, attempt: int) -> GateOutcome:
        code = ErrorCode.RETRY_EXHAUSTED if attempt >= 1 else ErrorCode.GENERATION_INVALID
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


Pipeline = B0Pipeline

__all__ = ["Pipeline", "B0Pipeline"]
