#!/usr/bin/env python3
"""CLI chuẩn để chạy luồng End-to-End DataMate Pipeline (Context -> Grounding -> Planner -> Executor -> Gate).

Các tệp đầu ra được lưu tại `--output-dir`:
  1. `submission.jsonl`     : Kết quả định dạng nộp bài chính thức (`{"id", "type", "answer"}`).
  2. `gate_trace.jsonl`     : Bản ghi tóm tắt quyết định của cổng kiểm định cho từng câu hỏi.
  3. `grounding_trace.jsonl`: Bản ghi chi tiết phân tích của Grounding C1-C5 (intent, thời gian, schema, giá trị).
  4. `detailed_logs.jsonl`  : Nhật ký đầy đủ gồm câu hỏi, từng lần thử (attempt 0/1), câu SQL,
                              suy nghĩ của LLM (`thinking`), giả định (`assumptions`) và lỗi DuckDB.
  5. `logs/<id>_<hash>.json` : File JSON kiểm toán riêng cho từng câu hỏi.
  6. `eval_report.json`     : Báo cáo đối chiếu độ chính xác (Exact Match / PA) nếu có `answers.jsonl`.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR / "src") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "src"))

from datamate.context.contracts import BusinessRule
from datamate.context.runtime import sync_unit_conversions_to_bundle
from datamate.gate import (
    merge_shard_artifacts,
    partition_questions_by_business,
    seed_abstain_submission,
    upsert_submission_records,
)
from datamate.pipeline import DataMatePipeline, Pipeline, B0Pipeline
from datamate.voting import VotingConfig
from datamate.planner import (
    BaseLLM,
    ChatMessage,
    GenerationDiagnostics,
    GenerationOptions,
    GenerationResult,
    Text2SQLGenerator,
    VLLMModel,
    load_config,
    load_pipeline_config,
)
from datamate.planner.errors import InferenceError

_DEFAULT_VOTING_FALLBACK = VotingConfig(
    enabled=True,
    rounds=1,
    initial_candidates=4,
    threshold=0.5,
    temperature=0.5,
    top_p=0.8,
    top_k=20,
    thinking_mode="always_off",
)


class OpenAICompatibleLLM(BaseLLM):
    """Client kết nối tới vLLM/OpenAI-compatible server từ xa (tùy chọn `--api-base`)."""

    def __init__(
        self,
        base_url: str,
        model_name: str,
        api_key: str = "EMPTY",
        timeout: float = 120.0,
        default_options: GenerationOptions | None = None,
        chat_template_kwargs: dict[str, Any] | None = None,
    ) -> None:
        from openai import OpenAI

        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.model_name = model_name
        self.default_options = default_options
        self.chat_template_kwargs = chat_template_kwargs or {}

    def load(self) -> None:
        pass

    def generate(self, prompt: str, *, options: GenerationOptions | None = None) -> GenerationResult:
        opts = options or self.default_options
        max_tokens = opts.max_new_tokens if opts else 2048
        temperature = opts.temperature if opts else 0.0
        response = self.client.completions.create(
            model=self.model_name,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = response.choices[0]
        return GenerationResult(
            text=choice.text,
            input_tokens=getattr(response.usage, "prompt_tokens", None),
            output_tokens=getattr(response.usage, "completion_tokens", None),
            finish_reason=choice.finish_reason,
        )

    def chat(
        self, messages: list[ChatMessage], *, options: GenerationOptions | None = None
    ) -> GenerationResult:
        opts = options or self.default_options
        max_tokens = opts.max_new_tokens if opts else 2048
        temperature = opts.temperature if opts else 0.0
        extra_body: dict[str, Any] = {}
        template_kwargs = dict(self.chat_template_kwargs)
        if opts and opts.enable_thinking is not None:
            template_kwargs["enable_thinking"] = opts.enable_thinking
        if template_kwargs:
            extra_body["chat_template_kwargs"] = template_kwargs
        if opts:
            extra_body.update(
                top_p=opts.top_p,
                top_k=opts.top_k,
                presence_penalty=opts.presence_penalty,
                repetition_penalty=opts.repetition_penalty,
            )
        if opts and getattr(opts, "thinking_token_budget", None) is not None:
            extra_body["thinking_token_budget"] = opts.thinking_token_budget

        msgs_payload = [{"role": m.role, "content": m.content} for m in messages]
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=msgs_payload,
                max_tokens=max_tokens,
                temperature=temperature,
                seed=opts.seed if opts else None,
                extra_body=extra_body if extra_body else None,
            )
        except Exception as exc:
            raise InferenceError(f"OpenAI endpoint call failed: {exc}") from exc

        choice = response.choices[0]
        content = choice.message.content or ""
        reasoning = getattr(choice.message, "reasoning_content", None)
        if reasoning and "<think>" not in content:
            content = f"<think>\n{reasoning}\n</think>\n{content}"

        return GenerationResult(
            text=content,
            input_tokens=getattr(response.usage, "prompt_tokens", None),
            output_tokens=getattr(response.usage, "completion_tokens", None),
            finish_reason=choice.finish_reason,
            diagnostics=GenerationDiagnostics(
                thinking_enabled=template_kwargs.get("enable_thinking"),
                thinking_token_budget=getattr(opts, "thinking_token_budget", None) if opts else None,
                max_new_tokens=max_tokens,
            ),
        )

    def generate_batch(
        self, prompts: list[str], *, options: GenerationOptions | None = None
    ) -> list[GenerationResult]:
        return [self.generate(p, options=options) for p in prompts]

    def chat_batch(
        self, messages_batch: list[list[ChatMessage]], *, options: GenerationOptions | None = None
    ) -> list[GenerationResult]:
        selected = options or self.default_options
        return [self.chat(m, options=replace(selected, seed=selected.seed + index)
                          if selected and selected.enable_thinking is not None and selected.seed is not None
                          else options) for index, m in enumerate(messages_batch)]


def _deserialize_business_rules(raw_rules: list[dict[str, Any]]) -> list[BusinessRule]:
    """Restore the complete BusinessRule contract from serialized context data."""
    return [
        BusinessRule(
            rule_id=str(rule.get("rule_id", "")),
            text=str(rule.get("text", "")),
            source=str(rule.get("source", "")),
            scope=str(rule.get("scope", "global")),
            precedence=int(rule.get("precedence", 0)),
            status=str(rule.get("status", "descriptive")),
            required_fields=tuple(str(field) for field in rule.get("required_fields") or ()),
            expression=rule.get("expression"),
            validation_messages=tuple(
                str(message) for message in rule.get("validation_messages") or ()
            ),
            topic=rule.get("topic"),
            industry=rule.get("industry"),
            question_id=rule.get("question_id"),
            requirements=tuple(str(item) for item in rule.get("requirements") or ()),
            binding_evidence=tuple(
                str(item) for item in rule.get("binding_evidence") or ()
            ),
        )
        for rule in raw_rules
        if isinstance(rule, dict)
    ]


def evaluate_predictions(
    submission_path: Path,
    answers_path: Path,
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Tính toán điểm Penalized Accuracy (PA) giữa submission.jsonl và answers.jsonl."""
    import unicodedata

    def _normalize(val: Any, answer_type: str | None = None) -> Any:
        if val is None:
            return None
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return round(float(val), 2)
        if isinstance(val, str):
            clean = " ".join(unicodedata.normalize("NFC", val).strip().casefold().split())
            try:
                num = float(clean.replace(",", ""))
                return round(num, 2)
            except ValueError:
                return clean
        if isinstance(val, list):
            normalized = [_normalize(x) for x in val if x is not None]
            if answer_type == "table":
                return sorted(
                    normalized,
                    key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True),
                )
            return normalized
        if isinstance(val, dict):
            if "rows" in val and isinstance(val["rows"], list):
                normalized_table = {
                    key: _normalize(value)
                    for key, value in val.items()
                    if key != "rows"
                }
                normalized_table["rows"] = _normalize(val["rows"], "table")
                return normalized_table
            return {k: _normalize(v) for k, v in val.items()}
        return val

    ground_truth: dict[str, Any] = {}
    with answers_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                ground_truth[str(rec["id"])] = rec

    preds: dict[str, Any] = {}
    with submission_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                preds[str(rec["id"])] = rec

    correct = 0
    wrong = 0
    abstained = 0
    details: list[dict[str, Any]] = []

    for q in questions:
        qid = str(q["id"])
        gt = ground_truth.get(qid)
        pr = preds.get(qid)
        if not gt:
            continue

        gt_type = gt.get("type")
        gt_ans = gt.get("answer")
        pr_type = pr.get("type") if pr else "abstain"
        pr_ans = pr.get("answer") if pr else None

        if pr_type == "abstain":
            status = "abstained"
            abstained += 1
            pa_delta = 0
        elif gt_type == "unanswerable":
            if pr_type == "unanswerable":
                status = "correct"
                correct += 1
                pa_delta = 1
            else:
                status = "wrong"
                wrong += 1
                pa_delta = -1
        else:
            if pr_type != gt_type:
                status = "wrong"
                wrong += 1
                pa_delta = -1
            else:
                norm_gt = _normalize(gt_ans, gt_type)
                norm_pr = _normalize(pr_ans, pr_type)
                if norm_gt == norm_pr:
                    status = "correct"
                    correct += 1
                    pa_delta = 1
                else:
                    status = "wrong"
                    wrong += 1
                    pa_delta = -1

        details.append({
            "id": qid,
            "business_id": q.get("business_id"),
            "status": status,
            "pa_delta": pa_delta,
            "gt_type": gt_type,
            "pred_type": pr_type,
            "gt_answer": gt_ans,
            "pred_answer": pr_ans,
        })

    total = len(details)
    pa_points = correct - wrong
    pa_score = round(pa_points / total, 4) if total > 0 else 0.0
    acc = round((correct / total) * 100.0, 2) if total > 0 else 0.0

    return {
        "total_evaluated": total,
        "correct": correct,
        "wrong": wrong,
        "abstained": abstained,
        "accuracy_percent": acc,
        "pa_points": pa_points,
        "pa_score": pa_score,
        "pa_percent": round(pa_score * 100.0, 2),
        "details": details,
    }


def _find_ready_bundle(out_b: Path, biz_id: str) -> Path | None:
    """Locate an already-prepared (and possibly Phase-1 enriched) bundle directory."""
    if not out_b.is_dir():
        return None

    search_roots = [out_b]
    nested_root = out_b / biz_id
    if nested_root.is_dir():
        search_roots.append(nested_root)

    candidates: list[tuple[bool, int, Path]] = []
    for root in search_roots:
        for cand in root.iterdir():
            if not cand.is_dir():
                continue
            if cand.name.startswith(("failed-", "corrupt-", ".build-")):
                continue
            ctx_path = cand / "business_context.json"
            duck_path = cand / "data.duckdb"
            if not (ctx_path.is_file() and duck_path.is_file()):
                continue
            manifest_path = cand / "source_manifest.json"
            if manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if manifest.get("status") != "ready":
                        continue
                except (OSError, json.JSONDecodeError):
                    continue
            has_semantic = False
            try:
                ctx_obj = json.loads(ctx_path.read_text(encoding="utf-8"))
                has_semantic = bool(ctx_obj.get("semantic_catalog"))
            except (OSError, json.JSONDecodeError):
                pass
            candidates.append((has_semantic, ctx_path.stat().st_mtime_ns, cand))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _resolve_split_knowledge_files(split_dir: Path) -> tuple[Path | None, Path | None, Path | None]:
    """Locate optional rulebook, calendar, and relationships files under split_dir."""
    rulebook = next(
        (
            p
            for p in (
                split_dir / "rulebook.md",
                split_dir / "rulebook.txt",
                split_dir / "data" / "rulebook.md",
                split_dir / "data" / "rulebook.txt",
            )
            if p.is_file()
        ),
        None,
    )
    calendar = next(
        (
            p
            for p in (
                split_dir / "calendar.csv",
                split_dir / "data" / "calendar.csv",
            )
            if p.is_file()
        ),
        None,
    )
    relationships = next(
        (
            p
            for p in (
                split_dir / "relationships.json",
                split_dir / "data" / "relationships.json",
            )
            if p.is_file()
        ),
        None,
    )
    return rulebook, calendar, relationships


def _run_semantic_discovery(bundles: dict[str, Path], chat_fn: Any) -> None:
    """Enrich business_context.json & DuckDB unit conversions using the loaded 3B chat function."""
    from datamate.context.semantic_extractor import create_semantic_extractor
    from datamate.ingestion.contracts import ColumnMetadata, SchemaCatalog, TableMetadata

    extractor = create_semantic_extractor(chat_fn=chat_fn)
    for b_id, b_path in bundles.items():
        b_ctx_file = Path(b_path) / "business_context.json"
        if not b_ctx_file.is_file():
            continue
        try:
            ctx_data = json.loads(b_ctx_file.read_text(encoding="utf-8"))
            raw_schema = ctx_data.get("schema_catalog", {})
            tables = [
                TableMetadata(
                    name=t.get("name"),
                    columns=tuple(
                        ColumnMetadata(name=c.get("name"), data_type=c.get("data_type"))
                        for c in t.get("columns", [])
                    ),
                )
                for t in raw_schema.get("tables", [])
            ]
            schema = SchemaCatalog(tables=tuple(tables))
            raw_rules = ctx_data.get("rule_catalog", {}).get("rules", [])
            rules = _deserialize_business_rules(raw_rules)
            sem_cat = extractor.extract_semantic_catalog(business_id=b_id, schema=schema, rules=rules)
            ctx_data["semantic_catalog"] = sem_cat.to_dict()

            if getattr(sem_cat, "unit_conversions", None):
                try:
                    duck_file = Path(b_path) / "data.duckdb"
                    if duck_file.is_file():
                        n_rows = sync_unit_conversions_to_bundle(
                            duck_file, ctx_data, ctx_data["semantic_catalog"].get("unit_conversions", [])
                        )
                        print(f"  => Doanh nghiệp {b_id}: Đã nạp {n_rows} quy tắc quy đổi đơn vị 2 chiều vào DuckDB.")
                except Exception as u_exc:
                    print(f"  ! Cảnh báo khi nạp unit_conversions vào DuckDB cho {b_id}: {u_exc}")

            b_ctx_file.write_text(json.dumps(ctx_data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"  => Doanh nghiệp {b_id}: 3B đã phát hiện {len(sem_cat.metrics)} chỉ số "
                f"và {len(sem_cat.suggested_joins)} liên kết bảng."
            )
        except Exception as exc:
            print(f"  ! Cảnh báo khi 3B phân tích ngữ nghĩa cho {b_id}: {exc}")


def _build_grounding_indexes(
    bundles: dict[str, Path],
    *,
    rulebook_path: Path | None,
    calendar_path: Path | None,
) -> dict[str, Any]:
    """Construct GroundingContextIndex for every prepared business bundle after enrichment."""
    from datamate.grounding import GroundingContextIndex

    if rulebook_path is None or not rulebook_path.is_file():
        raise FileNotFoundError(
            "NeoGroundingEngine yêu cầu file rulebook.md hoặc rulebook.txt trong split_dir."
        )
    if calendar_path is None or not calendar_path.is_file():
        raise FileNotFoundError(
            "NeoGroundingEngine yêu cầu file calendar.csv trong split_dir."
        )

    indexes: dict[str, Any] = {}
    for biz_id, b_path in bundles.items():
        indexes[biz_id] = GroundingContextIndex(
            b_path,
            rulebook=rulebook_path,
            calendar=calendar_path,
        )
    return indexes


def _init_grounding_runtime(
    *,
    grounding_engine: str,
    enable_grounding: bool,
    enable_grounding_llm: bool,
    grounding_config_path: Path | None,
    grounding_model_path: Path | None,
    bundles: dict[str, Path],
    rulebook_path: Path | None,
    calendar_path: Path | None,
    grounding_cache_path: Path | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Initialize grounding runtime (Cached, Neo v3, Rules/Fallback, or Disabled)."""
    if not enable_grounding or grounding_engine == "off":
        print("\n[2.1/4] Grounding Engine đang tắt (off).")
        return None, {}

    if grounding_cache_path is not None and grounding_cache_path.is_file():
        from datamate.grounding import CachedGroundingRuntime, load_grounding_cache

        cached = load_grounding_cache(grounding_cache_path)
        print(f"\n[2.1/4] Đang tái sử dụng {len(cached)} kết quả Grounding từ cache: {grounding_cache_path}")
        return CachedGroundingRuntime(cached), {}

    if grounding_engine == "neo":
        if rulebook_path is None or not rulebook_path.is_file():
            raise FileNotFoundError(
                "NeoGroundingEngine yêu cầu file rulebook.md hoặc rulebook.txt trong split_dir."
            )
        if calendar_path is None or not calendar_path.is_file():
            raise FileNotFoundError(
                "NeoGroundingEngine yêu cầu file calendar.csv trong split_dir."
            )

        g_cfg_path = (grounding_config_path or (ROOT_DIR / "configs" / "qwen2_5_3b_neo_grounding.toml")).resolve()
        print(f"\n[2.1/4] Đang khởi tạo NeoGroundingEngine v3 (3B) từ {g_cfg_path}...")
        from datamate.grounding import NeoGroundingEngine, QuestionGroundingRuntime

        g_engine = NeoGroundingEngine.from_qwen(
            g_cfg_path,
            {},
            model_path_override=grounding_model_path,
        )
        print("  => Đã nạp thành công mô hình Neo Grounding 3B vào VRAM.")

        discovery_chat = getattr(g_engine, "unstructured_chat_fn", None) or getattr(g_engine, "chat_fn", None)
        if discovery_chat is not None:
            print("\n[2.1b/4] Đang kích hoạt mô hình 3B phân tích ngữ nghĩa (Semantic Discovery) trước khi lập chỉ mục...")
            _run_semantic_discovery(bundles, discovery_chat)

        indexes = _build_grounding_indexes(
            bundles,
            rulebook_path=rulebook_path,
            calendar_path=calendar_path,
        )
        g_engine.indexes = indexes
        return QuestionGroundingRuntime(engine=g_engine), indexes

    if enable_grounding_llm:
        g_cfg_path = (grounding_config_path or (ROOT_DIR / "configs" / "qwen2_5_3b_grounding.toml")).resolve()
        print(f"\n[2.1/4] Đang khởi tạo mô hình Grounding C1 Fallback (3B) từ {g_cfg_path}...")
        from datamate.grounding import QuestionGroundingEngine, QuestionGroundingRuntime

        g_engine = QuestionGroundingEngine.from_qwen3b_vllm(
            config_path=g_cfg_path,
            model_path_override=grounding_model_path,
        )
        print("  => Đã nạp thành công mô hình Grounding 3B vào VRAM.")
        if g_engine.chat_fn is not None:
            print("\n[2.1b/4] Đang kích hoạt mô hình 3B phân tích toàn diện ngữ nghĩa (Semantic Discovery)...")
            _run_semantic_discovery(bundles, g_engine.chat_fn)
        return QuestionGroundingRuntime(engine=g_engine), {}

    print("\n[2.1/4] Grounding Engine sử dụng chế độ Pure Rule-Based (Deterministic Fast-Path).")
    return None, {}


def _execute_grounding_phase(
    *,
    questions: list[dict[str, Any]],
    bundles: dict[str, Path],
    grounding_runtime: Any,
    indexes: dict[str, Any],
    cache_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Run Phase 1 only (Semantic Discovery + Grounding) and write cache JSONL before freeing 3B VRAM."""
    from datamate.grounding import QuestionGroundingRuntime, serialize_grounded_question

    active_runtime = grounding_runtime or QuestionGroundingRuntime()
    rt_cache: dict[str, Any] = {}
    entries: list[dict[str, Any]] = []
    errors = 0

    trace_path = output_dir / "grounding_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    started = time.perf_counter()
    for q in questions:
        q_id = str(q["id"])
        biz_id = str(q.get("business_id", ""))
        b_path = bundles.get(biz_id)
        if b_path is None:
            errors += 1
            print(f"  ! Bỏ qua {q_id}: thiếu bundle cho business_id={biz_id}")
            continue
        key = str(b_path)
        if key not in rt_cache:
            rt_cache[key] = DataMatePipeline.load_runtime_context(
                b_path, expected_business_id=biz_id or None
            )
        rt_ctx = rt_cache[key]
        t_g0 = time.perf_counter()
        try:
            grounded = active_runtime.ground_question(
                question_id=q_id,
                business_id=biz_id,
                question=str(q["question"]),
                as_of_date=str(q.get("as_of_date", "")),
                context=rt_ctx.grounding_context,
            )
            g_ms = round((time.perf_counter() - t_g0) * 1000.0, 2)
            idx = indexes.get(biz_id)
            entries.append(
                serialize_grounded_question(
                    grounded,
                    elapsed_ms=g_ms,
                    index_fingerprint=getattr(idx, "fingerprint", None),
                )
            )
            DataMatePipeline._record_grounding_trace(output_dir, grounded, None, g_ms)
        except Exception as exc:
            errors += 1
            cause = getattr(exc, "__cause__", None) or exc
            diag = getattr(getattr(active_runtime, "_engine", None), "last_diagnostics", None) or {}
            stage = diag.get("stage")
            stage_info = f", stage={stage}" if stage else ""
            print(f"  ! Cảnh báo Grounding thất bại cho {q_id}: {type(cause).__name__}{stage_info}: {exc}")
            try:
                with trace_path.open("a", encoding="utf-8") as tf:
                    tf.write(
                        json.dumps(
                            {
                                "question_id": q_id,
                                "business_id": biz_id,
                                "status": "error",
                                "error_type": type(cause).__name__,
                                "stage": stage,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except OSError:
                pass

    save_fn_path = None
    from datamate.grounding import save_grounding_cache

    save_fn_path = save_grounding_cache(cache_path, entries)
    elapsed_sec = round(time.perf_counter() - started, 2)
    print(
        f"\n[Pha 1 hoàn tất] Đã cache {len(entries)}/{len(questions)} câu hỏi vào {save_fn_path} "
        f"trong {elapsed_sec}s (errors={errors}). Thoát process để giải phóng 100% VRAM."
    )
    return {
        "phase": "grounding",
        "total_questions": len(questions),
        "cached_questions": len(entries),
        "errors": errors,
        "grounding_cache": str(save_fn_path),
        "total_elapsed_seconds": elapsed_sec,
        "output_dir": str(output_dir),
    }


def _append_filter_flags(cmd: list[str], flag: str, values: list[str] | None) -> None:
    if not values:
        return
    for val in values:
        cmd.extend([flag, str(val)])


def _load_and_filter_questions(
    split_dir: Path,
    *,
    business_ids: list[str] | None = None,
    question_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    questions_path = split_dir / "questions.jsonl"
    if not questions_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file câu hỏi: {questions_path}")

    questions: list[dict[str, Any]] = []
    with questions_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line))

    if business_ids:
        b_set = set(business_ids)
        questions = [q for q in questions if q.get("business_id") in b_set]
    if question_ids:
        q_set = set(question_ids)
        questions = [q for q in questions if str(q.get("id")) in q_set]
    if limit and limit > 0:
        questions = questions[:limit]
    return questions


def _resolve_gpu_ids(*, num_gpus: int | None = None, gpu_ids: str | None = None) -> list[str]:
    """Determine physical CUDA device IDs to run independent shard pipelines on."""
    if gpu_ids:
        parsed = [d.strip() for d in gpu_ids.split(",") if d.strip() and d.strip() != "-1"]
        if parsed:
            return parsed[:num_gpus] if (num_gpus and num_gpus > 0) else parsed

    if num_gpus is not None and num_gpus <= 1:
        return ["0"]

    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    if visible and visible.lower() != "all":
        parsed_env = [d.strip() for d in visible.split(",") if d.strip() and d.strip() != "-1"]
        if parsed_env:
            if num_gpus is not None and num_gpus > 0:
                return parsed_env[:num_gpus] if len(parsed_env) >= num_gpus else [str(i) for i in range(num_gpus)]
            return parsed_env

    if num_gpus is not None and num_gpus > 1:
        return [str(i) for i in range(num_gpus)]

    try:
        probe = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if probe.returncode == 0:
            lines = [line for line in probe.stdout.splitlines() if line.strip().startswith("GPU ")]
            if len(lines) > 1:
                return [str(i) for i in range(len(lines))]
    except (OSError, subprocess.SubprocessError):
        pass
    return ["0"]


def _clean_stale_outputs(
    target_dir: Path,
    *,
    keep_submission: bool = False,
    keep_shards: bool = True,
) -> None:
    stale_names = [
        "gate_trace.jsonl",
        "detailed_logs.jsonl",
        "eval_report.json",
        "grounding_trace.jsonl",
    ]
    if not keep_submission:
        stale_names.extend(["submission.jsonl", "submission.manifest.json"])
    for stale in stale_names:
        stale_path = target_dir / stale
        if stale_path.exists():
            stale_path.unlink()
    for dir_name in (("logs",) if keep_shards else ("logs", "_shards")):
        stale_dir = target_dir / dir_name
        if stale_dir.is_dir():
            shutil.rmtree(stale_dir)


def _evaluate_if_answers_exist(
    *,
    split_dir: Path,
    output_dir: Path,
    questions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    answers_path = split_dir / "answers.jsonl"
    if not answers_path.is_file():
        print("[4/4] Hoàn tất (không có answers.jsonl trong thư mục này — chế độ public_test/submission).")
        return None
    print(f"\n[4/4] Đang đối chiếu với đáp án chuẩn: {answers_path}...")
    eval_report = evaluate_predictions(
        submission_path=output_dir / "submission.jsonl",
        answers_path=answers_path,
        questions=questions,
    )
    eval_path = output_dir / "eval_report.json"
    eval_path.write_text(json.dumps(eval_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_eval = {
        "total_evaluated": eval_report["total_evaluated"],
        "correct": eval_report["correct"],
        "wrong": eval_report["wrong"],
        "abstained": eval_report["abstained"],
        "accuracy_percent": eval_report["accuracy_percent"],
        "pa_points": eval_report["pa_points"],
        "pa_score": eval_report["pa_score"],
        "pa_percent": eval_report["pa_percent"],
        "eval_report_file": str(eval_path),
    }
    print(
        f"  => KẾT QUẢ ĐÁNH GIÁ (N={eval_report['total_evaluated']}):\n"
        f"     - Đúng (+1)   : {eval_report['correct']} ({eval_report['accuracy_percent']}%)\n"
        f"     - Sai (-1)    : {eval_report['wrong']}\n"
        f"     - Abstain (0) : {eval_report['abstained']}\n"
        f"     - ĐIỂM PA     : {eval_report['pa_score']} ({eval_report['pa_percent']}%) [PA Points = {eval_report['pa_points']}/{eval_report['total_evaluated']}]",
        flush=True,
    )
    return summary_eval


def _build_grounding_flags(
    *,
    enable_grounding: bool,
    enable_grounding_llm: bool,
    grounding_config_path: Path | None,
    grounding_model_path: Path | None,
) -> list[str]:
    flags: list[str] = []
    if not enable_grounding:
        flags.append("--no-enable-grounding")
    if enable_grounding_llm:
        flags.append("--enable-grounding-llm")
    if grounding_config_path is not None:
        flags.extend(["--grounding-config", str(grounding_config_path)])
    if grounding_model_path is not None:
        flags.extend(["--grounding-model-path", str(grounding_model_path)])
    return flags


def _build_planner_flags(
    *,
    enable_grounding: bool,
    model_path: Path | None,
    lora_path: Path | None,
    no_lora: bool,
    prompt_format: str | None,
    grounded_hint_mode: str | None,
    enable_thinking: bool | None,
    api_base: str | None,
    api_model: str | None,
    timeout_sec: float,
    max_rows: int,
    voting: bool | None,
    voting_rounds: int | None,
    voting_candidates: int | None,
    voting_threshold: float | None,
    voting_temperature: float | None,
    voting_top_p: float | None,
    voting_top_k: int | None,
    voting_thinking_mode: str | None,
) -> list[str]:
    flags: list[str] = [
        "--timeout-sec", str(timeout_sec),
        "--max-rows", str(max_rows),
    ]
    if not enable_grounding:
        flags.append("--no-enable-grounding")
    if model_path is not None:
        flags.extend(["--model-path", str(model_path)])
    if no_lora:
        flags.append("--no-lora")
    elif lora_path is not None:
        flags.extend(["--lora-path", str(lora_path)])
    if prompt_format is not None:
        flags.extend(["--prompt-format", prompt_format])
    if grounded_hint_mode is not None:
        flags.extend(["--grounded-hint-mode", grounded_hint_mode])
    if enable_thinking is True:
        flags.append("--enable-thinking")
    elif enable_thinking is False:
        flags.append("--no-enable-thinking")
    if api_base is not None:
        flags.extend(["--api-base", api_base])
    if api_model is not None:
        flags.extend(["--api-model", api_model])
    if voting is True:
        flags.append("--voting")
    elif voting is False:
        flags.append("--no-voting")
    if voting_rounds is not None:
        flags.extend(["--voting-rounds", str(voting_rounds)])
    if voting_candidates is not None:
        flags.extend(["--voting-candidates", str(voting_candidates)])
    if voting_threshold is not None:
        flags.extend(["--voting-threshold", str(voting_threshold)])
    if voting_temperature is not None:
        flags.extend(["--voting-temperature", str(voting_temperature)])
    if voting_top_p is not None:
        flags.extend(["--voting-top-p", str(voting_top_p)])
    if voting_top_k is not None:
        flags.extend(["--voting-top-k", str(voting_top_k)])
    if voting_thinking_mode is not None:
        flags.extend(["--voting-thinking-mode", voting_thinking_mode])
    return flags


def _run_multi_gpu_subprocesses(
    *,
    gpu_list: list[str],
    all_questions: list[dict[str, Any]],
    split_dir: Path,
    bundles_dir: Path,
    output_dir: Path,
    config_path: Path,
    grounding_engine: str,
    grounding_config_path: Path | None,
    grounding_model_path: Path | None,
    enable_grounding: bool,
    enable_grounding_llm: bool,
    grounding_cache_path: Path | None,
    two_phase: bool,
    model_path: Path | None,
    lora_path: Path | None,
    no_lora: bool,
    prompt_format: str | None,
    grounded_hint_mode: str | None,
    enable_thinking: bool | None,
    api_base: str | None,
    api_model: str | None,
    business_ids: list[str] | None,
    question_ids: list[str] | None,
    limit: int | None,
    batch_size: int,
    timeout_sec: float,
    max_rows: int,
    voting: bool | None,
    voting_rounds: int | None,
    voting_candidates: int | None,
    voting_threshold: float | None,
    voting_temperature: float | None,
    voting_top_p: float | None,
    voting_top_k: int | None,
    voting_thinking_mode: str | None,
) -> dict[str, Any]:
    """Pre-seed abstain submission, partition by business_id across GPUs, run in parallel, and merge."""
    num_shards = len(gpu_list)
    expected_ids = [str(q["id"]) for q in all_questions]
    _clean_stale_outputs(output_dir, keep_submission=False, keep_shards=False)
    seed_abstain_submission(output_dir, all_questions)
    print(
        f"\n=== CHẾ ĐỘ SONG SONG {num_shards} GPU (GPUs={','.join(gpu_list)}) ===\n"
        f"  - Đã khởi tạo sẵn {len(expected_ids)} dòng 'abstain' tại: {output_dir / 'submission.jsonl'}",
        flush=True,
    )

    script_path = str(Path(__file__).resolve())
    shards_base = Path(os.environ.get("DATAMATE_SHARDS_DIR", tempfile.gettempdir()))
    shards_root = shards_base / f"datamate_shards_{output_dir.name}_{os.getpid()}"
    shards_root.mkdir(parents=True, exist_ok=True)
    spill_base = Path(os.environ.get("B04_DUCKDB_TEMP_DIR", "/tmp/duckdb_spill"))

    shard_dirs: list[Path] = []
    procs: list[tuple[int, str, subprocess.Popen[Any]]] = []
    for shard_idx, gpu_id in enumerate(gpu_list):
        shard_qs, shard_biz = partition_questions_by_business(
            all_questions, num_shards=num_shards, shard_index=shard_idx
        )
        shard_dir = shards_root / f"gpu_{shard_idx}"
        shard_dirs.append(shard_dir)
        if not shard_qs:
            print(f"  - GPU {gpu_id} (shard {shard_idx}/{num_shards}): 0 câu hỏi, bỏ qua.")
            continue

        print(
            f"  - GPU {gpu_id} (shard {shard_idx}/{num_shards}): "
            f"{len(shard_qs)} câu hỏi / {len(shard_biz)} doanh nghiệp -> {shard_dir}",
            flush=True,
        )
        cmd = [
            sys.executable,
            script_path,
            "--split-dir", str(split_dir),
            "--bundles-dir", str(bundles_dir),
            "--output-dir", str(shard_dir),
            "--config", str(config_path),
            "--grounding-engine", grounding_engine,
            "--batch-size", str(batch_size),
            "--num-gpus", "1",
            "--num-shards", str(num_shards),
            "--shard-index", str(shard_idx),
            "--merge-target-dir", str(output_dir),
            "--no-init-abstain",
            "--two-phase" if two_phase else "--no-two-phase",
        ]
        _append_filter_flags(cmd, "--business-id", business_ids)
        _append_filter_flags(cmd, "--question-id", question_ids)
        if grounding_cache_path is not None:
            cmd.extend(["--grounding-cache", str(grounding_cache_path)])
        if limit is not None:
            cmd.extend(["--limit", str(limit)])
        cmd.extend(
            _build_grounding_flags(
                enable_grounding=enable_grounding,
                enable_grounding_llm=enable_grounding_llm,
                grounding_config_path=grounding_config_path,
                grounding_model_path=grounding_model_path,
            )
        )
        cmd.extend(
            _build_planner_flags(
                enable_grounding=enable_grounding,
                model_path=model_path,
                lora_path=lora_path,
                no_lora=no_lora,
                prompt_format=prompt_format,
                grounded_hint_mode=grounded_hint_mode,
                enable_thinking=enable_thinking,
                api_base=api_base,
                api_model=api_model,
                timeout_sec=timeout_sec,
                max_rows=max_rows,
                voting=voting,
                voting_rounds=voting_rounds,
                voting_candidates=voting_candidates,
                voting_threshold=voting_threshold,
                voting_temperature=voting_temperature,
                voting_top_p=voting_top_p,
                voting_top_k=voting_top_k,
                voting_thinking_mode=voting_thinking_mode,
            )
        )

        worker_env = dict(os.environ)
        worker_env["CUDA_VISIBLE_DEVICES"] = gpu_id
        worker_spill = spill_base / f"gpu_{shard_idx}"
        worker_spill.mkdir(parents=True, exist_ok=True)
        worker_env["B04_DUCKDB_TEMP_DIR"] = str(worker_spill)
        procs.append((shard_idx, gpu_id, subprocess.Popen(cmd, env=worker_env)))

    started = time.perf_counter()
    failures: list[tuple[int, str, int]] = []
    try:
        for shard_idx, gpu_id, proc in procs:
            rc = proc.wait()
            if rc != 0:
                failures.append((shard_idx, gpu_id, rc))
    except BaseException:
        for _, _, proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for _, _, proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        raise
    finally:
        try:
            merge_shard_artifacts(output_dir, shard_dirs, expected_ids=expected_ids)
        finally:
            shutil.rmtree(shards_root, ignore_errors=True)

    total_elapsed = round(time.perf_counter() - started, 2)
    summary: dict[str, Any] = {
        "phase": "multi_gpu",
        "num_gpus": num_shards,
        "gpu_ids": gpu_list,
        "grounding_engine": grounding_engine,
        "total_questions": len(all_questions),
        "total_elapsed_seconds": total_elapsed,
        "output_dir": str(output_dir),
    }
    eval_summary = _evaluate_if_answers_exist(
        split_dir=split_dir,
        output_dir=output_dir,
        questions=all_questions,
    )
    if eval_summary is not None:
        summary["evaluation"] = eval_summary
    if failures:
        summary["failures"] = [
            {"shard_index": idx, "gpu_id": gid, "returncode": rc} for idx, gid, rc in failures
        ]
        raise RuntimeError(f"Multi-GPU workers failed (partial results saved with abstain fallback): {failures}")
    return summary


def _run_two_phase_subprocesses(
    *,
    split_dir: Path,
    bundles_dir: Path,
    output_dir: Path,
    config_path: Path,
    cache_path: Path,
    grounding_engine: str,
    grounding_config_path: Path | None,
    grounding_model_path: Path | None,
    enable_grounding: bool,
    enable_grounding_llm: bool,
    num_shards: int,
    shard_index: int,
    merge_target_dir: Path | None,
    model_path: Path | None,
    lora_path: Path | None,
    no_lora: bool,
    prompt_format: str | None,
    grounded_hint_mode: str | None,
    enable_thinking: bool | None,
    api_base: str | None,
    api_model: str | None,
    business_ids: list[str] | None,
    question_ids: list[str] | None,
    limit: int | None,
    batch_size: int,
    timeout_sec: float,
    max_rows: int,
    voting: bool | None,
    voting_rounds: int | None,
    voting_candidates: int | None,
    voting_threshold: float | None,
    voting_temperature: float | None,
    voting_top_p: float | None,
    voting_top_k: int | None,
    voting_thinking_mode: str | None,
) -> dict[str, Any]:
    """Run Phase 1 (3B grounding) and Phase 2 (9B planner) as isolated OS subprocesses."""
    script_path = str(Path(__file__).resolve())
    common = [
        sys.executable,
        script_path,
        "--split-dir", str(split_dir),
        "--bundles-dir", str(bundles_dir),
        "--output-dir", str(output_dir),
        "--config", str(config_path),
        "--grounding-engine", grounding_engine,
        "--grounding-cache", str(cache_path),
        "--batch-size", str(batch_size),
        "--num-gpus", "1",
        "--num-shards", str(num_shards),
        "--shard-index", str(shard_index),
        "--no-init-abstain",
        "--no-two-phase",
    ]
    if merge_target_dir is not None:
        common.extend(["--merge-target-dir", str(merge_target_dir)])
    _append_filter_flags(common, "--business-id", business_ids)
    _append_filter_flags(common, "--question-id", question_ids)
    if limit is not None:
        common.extend(["--limit", str(limit)])

    cmd_phase1 = [
        *common,
        "--phase", "grounding",
        *_build_grounding_flags(
            enable_grounding=enable_grounding,
            enable_grounding_llm=enable_grounding_llm,
            grounding_config_path=grounding_config_path,
            grounding_model_path=grounding_model_path,
        ),
    ]

    print("\n=== CHẾ ĐỘ 2 PHA: BƯỚC 1/2 (3B GROUNDING + SEMANTIC DISCOVERY) ===", flush=True)
    subprocess.run(cmd_phase1, check=True)

    cmd_phase2 = [
        *common,
        "--phase", "planner",
        *_build_planner_flags(
            enable_grounding=enable_grounding,
            model_path=model_path,
            lora_path=lora_path,
            no_lora=no_lora,
            prompt_format=prompt_format,
            grounded_hint_mode=grounded_hint_mode,
            enable_thinking=enable_thinking,
            api_base=api_base,
            api_model=api_model,
            timeout_sec=timeout_sec,
            max_rows=max_rows,
            voting=voting,
            voting_rounds=voting_rounds,
            voting_candidates=voting_candidates,
            voting_threshold=voting_threshold,
            voting_temperature=voting_temperature,
            voting_top_p=voting_top_p,
            voting_top_k=voting_top_k,
            voting_thinking_mode=voting_thinking_mode,
        ),
    ]

    print("\n=== CHẾ ĐỘ 2 PHA: BƯỚC 2/2 (9B PLANNER v1.2 + VOTING + GATE) ===", flush=True)
    subprocess.run(cmd_phase2, check=True)

    sub_path = output_dir / "submission.jsonl"
    total_sub = (
        sum(1 for line in sub_path.read_text(encoding="utf-8").splitlines() if line.strip())
        if sub_path.is_file()
        else 0
    )
    summary: dict[str, Any] = {
        "phase": "two_phase",
        "grounding_engine": grounding_engine,
        "grounding_cache": str(cache_path),
        "total_questions": total_sub,
        "output_dir": str(output_dir),
    }
    eval_path = output_dir / "eval_report.json"
    if eval_path.is_file():
        eval_report = json.loads(eval_path.read_text(encoding="utf-8"))
        summary["evaluation"] = {
            "total_evaluated": eval_report["total_evaluated"],
            "correct": eval_report["correct"],
            "wrong": eval_report["wrong"],
            "abstained": eval_report["abstained"],
            "accuracy_percent": eval_report["accuracy_percent"],
            "pa_points": eval_report["pa_points"],
            "pa_score": eval_report["pa_score"],
            "pa_percent": eval_report["pa_percent"],
            "eval_report_file": str(eval_path),
        }
    return summary


def run_pipeline_cli(
    *,
    split_dir: Path,
    bundles_dir: Path,
    output_dir: Path,
    config_path: Path,
    model_path: Path | None = None,
    lora_path: Path | None = None,
    no_lora: bool = False,
    prompt_format: str | None = None,
    grounded_hint_mode: str | None = None,
    grounding_engine: str = "rules",
    grounding_config_path: Path | None = None,
    grounding_model_path: Path | None = None,
    grounding_cache_path: Path | None = None,
    phase: str = "all",
    two_phase: bool = False,
    num_gpus: int | None = 1,
    gpu_ids: str | None = None,
    num_shards: int = 1,
    shard_index: int = 0,
    merge_target_dir: Path | None = None,
    init_abstain: bool = True,
    enable_thinking: bool | None = None,
    api_base: str | None = None,
    api_model: str | None = None,
    business_ids: list[str] | None = None,
    question_ids: list[str] | None = None,
    limit: int | None = None,
    batch_size: int = 1,
    timeout_sec: float = 10.0,
    max_rows: int = 10000,
    enable_grounding: bool = True,
    enable_grounding_llm: bool = False,
    verbose: bool = True,
    voting: bool | None = None,
    voting_rounds: int | None = None,
    voting_candidates: int | None = None,
    voting_threshold: float | None = None,
    voting_temperature: float | None = None,
    voting_top_p: float | None = None,
    voting_top_k: int | None = None,
    voting_thinking_mode: str | None = None,
) -> dict[str, Any]:
    """Hàm lõi thực thi pipeline end-to-end có thể gọi từ code Python hoặc CLI."""
    split_dir = split_dir.resolve()
    bundles_dir = bundles_dir.resolve()
    output_dir = output_dir.resolve()
    config_path = config_path.resolve()
    if grounding_config_path is not None:
        grounding_config_path = grounding_config_path.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    effective_engine = "off" if not enable_grounding else grounding_engine
    resolved_cache_path = (
        grounding_cache_path.resolve()
        if grounding_cache_path is not None
        else (output_dir / "grounding_cache.jsonl")
    )

    all_questions = _load_and_filter_questions(
        split_dir,
        business_ids=business_ids,
        question_ids=question_ids,
        limit=limit,
    )
    if not all_questions:
        print("CẢNH BÁO: Không có câu hỏi nào khớp với bộ lọc!")
        return {}

    all_expected_ids = [str(q["id"]) for q in all_questions]

    if (
        num_shards == 1
        and shard_index == 0
        and merge_target_dir is None
        and phase == "all"
        and api_base is None
    ):
        gpu_list = _resolve_gpu_ids(num_gpus=num_gpus, gpu_ids=gpu_ids)
        if len(gpu_list) > 1:
            return _run_multi_gpu_subprocesses(
                gpu_list=gpu_list,
                all_questions=all_questions,
                split_dir=split_dir,
                bundles_dir=bundles_dir,
                output_dir=output_dir,
                config_path=config_path,
                grounding_engine=effective_engine,
                grounding_config_path=grounding_config_path,
                grounding_model_path=grounding_model_path,
                enable_grounding=enable_grounding,
                enable_grounding_llm=(enable_grounding_llm or effective_engine == "neo"),
                grounding_cache_path=grounding_cache_path.resolve() if grounding_cache_path is not None else None,
                two_phase=two_phase,
                model_path=model_path,
                lora_path=lora_path,
                no_lora=no_lora,
                prompt_format=prompt_format,
                grounded_hint_mode=grounded_hint_mode,
                enable_thinking=enable_thinking,
                api_base=api_base,
                api_model=api_model,
                business_ids=business_ids,
                question_ids=question_ids,
                limit=limit,
                batch_size=batch_size,
                timeout_sec=timeout_sec,
                max_rows=max_rows,
                voting=voting,
                voting_rounds=voting_rounds,
                voting_candidates=voting_candidates,
                voting_threshold=voting_threshold,
                voting_temperature=voting_temperature,
                voting_top_p=voting_top_p,
                voting_top_k=voting_top_k,
                voting_thinking_mode=voting_thinking_mode,
            )

    if init_abstain and merge_target_dir is None and (
        phase != "planner" or not (output_dir / "submission.jsonl").is_file()
    ):
        _clean_stale_outputs(output_dir, keep_submission=True, keep_shards=True)
        seed_abstain_submission(output_dir, all_questions)
        print(
            f"  - Đã khởi tạo sẵn {len(all_expected_ids)} dòng 'abstain' tại: {output_dir / 'submission.jsonl'}",
            flush=True,
        )

    if two_phase and phase == "all" and effective_engine != "off" and api_base is None:
        return _run_two_phase_subprocesses(
            split_dir=split_dir,
            bundles_dir=bundles_dir,
            output_dir=output_dir,
            config_path=config_path,
            cache_path=resolved_cache_path,
            grounding_engine=effective_engine,
            grounding_config_path=grounding_config_path,
            grounding_model_path=grounding_model_path,
            enable_grounding=enable_grounding,
            enable_grounding_llm=(enable_grounding_llm or effective_engine == "neo"),
            num_shards=num_shards,
            shard_index=shard_index,
            merge_target_dir=merge_target_dir,
            model_path=model_path,
            lora_path=lora_path,
            no_lora=no_lora,
            prompt_format=prompt_format,
            grounded_hint_mode=grounded_hint_mode,
            enable_thinking=enable_thinking,
            api_base=api_base,
            api_model=api_model,
            business_ids=business_ids,
            question_ids=question_ids,
            limit=limit,
            batch_size=batch_size,
            timeout_sec=timeout_sec,
            max_rows=max_rows,
            voting=voting,
            voting_rounds=voting_rounds,
            voting_candidates=voting_candidates,
            voting_threshold=voting_threshold,
            voting_temperature=voting_temperature,
            voting_top_p=voting_top_p,
            voting_top_k=voting_top_k,
            voting_thinking_mode=voting_thinking_mode,
        )

    questions, shard_businesses = partition_questions_by_business(
        all_questions,
        num_shards=num_shards,
        shard_index=shard_index,
    )

    print(f"=== KHỞI ĐỘNG DATAMATE PIPELINE ===")
    print(f"  - Thư mục dữ liệu : {split_dir}")
    print(f"  - Thư mục bundles  : {bundles_dir}")
    print(f"  - Thư mục kết quả : {output_dir}")
    print(f"  - Shard           : {shard_index + 1}/{num_shards} (businesses={len(shard_businesses)})")
    print(f"  - Phase           : {phase}")
    print(f"  - Grounding Engine: {effective_engine}")
    print(f"  - Batch size      : {batch_size}")
    print(f"  - Enable Grounding: {enable_grounding}")
    print(f"  - Grounding 3B LLM: {enable_grounding_llm or effective_engine == 'neo'}")

    if not questions:
        print(f"CẢNH BÁO: Shard {shard_index}/{num_shards} không có câu hỏi nào; kết thúc sớm.")
        return {
            "total_questions": 0,
            "shard_index": shard_index,
            "num_shards": num_shards,
            "output_dir": str(output_dir),
        }

    needed_businesses = sorted({q["business_id"] for q in questions if q.get("business_id")})
    print(f"  - Tổng số câu hỏi : {len(questions)} (thuộc {len(needed_businesses)} doanh nghiệp)")

    rulebook_path, calendar_path, relationships_path = _resolve_split_knowledge_files(split_dir)

    # [1/4] Chuẩn bị Data Foundation & Semantic Knowledge bundles
    print(f"\n[1/4] Đang kiểm tra/chuẩn bị {len(needed_businesses)} bundles...")
    bundles: dict[str, Path] = {}
    for biz_id in needed_businesses:
        biz_dir = split_dir / biz_id
        if not biz_dir.is_dir():
            biz_dir = split_dir / "data" / biz_id
        if not biz_dir.is_dir():
            print(f"  CẢNH BÁO: Thư mục doanh nghiệp không tồn tại: {biz_dir}")
            continue
        out_b = bundles_dir / biz_id

        # Kiểm tra nếu đã có bundle hoàn chỉnh (enriched) được tạo trước đó (hỗ trợ cả nested <biz>/<hash>)
        ready_bundle = _find_ready_bundle(out_b, biz_id)
        if ready_bundle is not None:
            bundles[biz_id] = ready_bundle
            print(f"  -> Tái sử dụng bundle đã sẵn sàng cho {biz_id}: {ready_bundle.name[:8]}...")
            continue

        res = DataMatePipeline.prepare_bundle(
            business_dir=biz_dir,
            output_dir=out_b,
            rulebook=rulebook_path,
            calendar=calendar_path,
            relationships=relationships_path,
        )
        bundles[biz_id] = res.bundle_dir
    print(f"  => Đã sẵn sàng {len(bundles)} bundles.")

    if phase == "planner":
        if effective_engine == "neo" and not resolved_cache_path.is_file():
            raise FileNotFoundError(
                f"Không tìm thấy grounding cache cho Pha 2 (--phase planner): {resolved_cache_path}"
            )
        grounding_runtime, indexes = _init_grounding_runtime(
            grounding_engine=effective_engine,
            enable_grounding=enable_grounding,
            enable_grounding_llm=False,
            grounding_config_path=grounding_config_path,
            grounding_model_path=grounding_model_path,
            bundles=bundles,
            rulebook_path=rulebook_path,
            calendar_path=calendar_path,
            grounding_cache_path=resolved_cache_path if resolved_cache_path.is_file() else None,
        )
    else:
        cache_input = (
            grounding_cache_path.resolve()
            if (phase == "all" and grounding_cache_path is not None and grounding_cache_path.is_file())
            else None
        )
        grounding_runtime, indexes = _init_grounding_runtime(
            grounding_engine=effective_engine,
            enable_grounding=enable_grounding,
            enable_grounding_llm=enable_grounding_llm,
            grounding_config_path=grounding_config_path,
            grounding_model_path=grounding_model_path,
            bundles=bundles,
            rulebook_path=rulebook_path,
            calendar_path=calendar_path,
            grounding_cache_path=cache_input,
        )

    if phase == "grounding":
        return _execute_grounding_phase(
            questions=questions,
            bundles=bundles,
            grounding_runtime=grounding_runtime,
            indexes=indexes,
            cache_path=resolved_cache_path,
            output_dir=output_dir,
        )

    print(f"\n[2.2/4] Đang khởi tạo mô hình Generator (9B)...")
    model_cfg, gen_opts, voting_config = load_pipeline_config(
        config_path, default_voting=_DEFAULT_VOTING_FALLBACK
    )
    voting_overrides: dict[str, Any] = {}
    if voting is not None:
        voting_overrides["enabled"] = voting
    if voting_rounds is not None:
        voting_overrides["rounds"] = voting_rounds
    if voting_candidates is not None:
        voting_overrides["initial_candidates"] = voting_candidates
    if voting_threshold is not None:
        voting_overrides["threshold"] = voting_threshold
    if voting_temperature is not None:
        voting_overrides["temperature"] = voting_temperature
    if voting_top_p is not None:
        voting_overrides["top_p"] = voting_top_p
    if voting_top_k is not None:
        voting_overrides["top_k"] = voting_top_k
    if voting_thinking_mode is not None:
        voting_overrides["thinking_mode"] = voting_thinking_mode
    if voting_overrides:
        voting_config = replace(voting_config, **voting_overrides)

    if model_path is not None:
        model_cfg = replace(model_cfg, model_path=Path(model_path).expanduser().resolve())
    if no_lora:
        model_cfg = replace(model_cfg, lora_path=None)
    elif lora_path is not None:
        model_cfg = replace(model_cfg, lora_path=Path(lora_path).expanduser().resolve())
    if prompt_format is not None:
        model_cfg = replace(model_cfg, prompt_format=prompt_format)
    if grounded_hint_mode is not None:
        model_cfg = replace(model_cfg, grounded_hint_mode=grounded_hint_mode)
    if enable_thinking is not None:
        new_kwargs = dict(model_cfg.chat_template_kwargs)
        new_kwargs["enable_thinking"] = bool(enable_thinking)
        model_cfg = replace(model_cfg, chat_template_kwargs=new_kwargs)
        gen_opts = replace(
            gen_opts,
            enable_thinking=bool(enable_thinking),
            thinking_token_budget=None if not enable_thinking else gen_opts.thinking_token_budget,
        )

    print(
        f"  - Voting: enabled={voting_config.enabled}, rounds={voting_config.rounds}, "
        f"k={voting_config.initial_candidates}, threshold={voting_config.threshold}, "
        f"temp={voting_config.temperature}, thinking_mode={voting_config.thinking_mode}, "
        f"grounded_hint_mode={model_cfg.grounded_hint_mode}"
    )

    if api_base:
        print(f"  - Kết nối vLLM server từ xa: {api_base} (model={api_model or model_cfg.model_name})")
        llm = OpenAICompatibleLLM(
            base_url=api_base,
            model_name=api_model or model_cfg.model_name,
            default_options=gen_opts,
            chat_template_kwargs=model_cfg.chat_template_kwargs,
        )
    else:
        print(
            f"  - Nạp offline vLLM model từ: {model_cfg.model_path} "
            f"(enable_thinking={model_cfg.chat_template_kwargs.get('enable_thinking')}, "
            f"prompt_format={model_cfg.prompt_format}, "
            f"lora_path={model_cfg.lora_path})"
        )
        vllm_engine = VLLMModel(model_cfg, default_options=gen_opts)
        vllm_engine.load()
        llm = vllm_engine

    pipeline = DataMatePipeline(
        generator=Text2SQLGenerator(
            llm,
            prompt_format=model_cfg.prompt_format,
            grounded_hint_mode=model_cfg.grounded_hint_mode,
        ),
        timeout_sec=timeout_sec,
        max_rows=max_rows,
        options=gen_opts,
        voting=voting_config,
        enable_grounding=enable_grounding,
        grounding_runtime=grounding_runtime,
        grounded_hint_mode=model_cfg.grounded_hint_mode,
    )

    live_target_dir = merge_target_dir.resolve() if merge_target_dir is not None else output_dir
    use_staging_dir = merge_target_dir is None
    if use_staging_dir:
        shards_base = Path(os.environ.get("DATAMATE_SHARDS_DIR", tempfile.gettempdir()))
        writer_dir = shards_base / f"datamate_work_{output_dir.name}_{os.getpid()}"
    else:
        writer_dir = output_dir
    if use_staging_dir:
        writer_dir.mkdir(parents=True, exist_ok=True)
        _clean_stale_outputs(writer_dir, keep_submission=False, keep_shards=True)
        _clean_stale_outputs(output_dir, keep_submission=True, keep_shards=True)
    else:
        _clean_stale_outputs(writer_dir, keep_submission=False, keep_shards=True)

    def _flush_outcomes_to_target(flushed_outcomes: Any) -> None:
        updates = {
            str(o.question_id): o.final_answer.to_submission_dict()
            for o in flushed_outcomes
            if o.final_answer is not None
        }
        if updates:
            upsert_submission_records(live_target_dir, updates, expected_ids=all_expected_ids)

    print(f"[3/4] Đang chạy {len(questions)} câu hỏi qua luồng DataMate Pipeline...", flush=True)
    started = time.perf_counter()
    try:
        outcomes = pipeline.run_questions(
            questions=questions,
            bundles=bundles,
            output_dir=writer_dir,
            batch_size=batch_size,
            verbose=verbose,
            on_outcomes_flushed=_flush_outcomes_to_target,
        )
    finally:
        if use_staging_dir:
            try:
                merge_shard_artifacts(output_dir, [writer_dir], expected_ids=all_expected_ids)
            finally:
                shutil.rmtree(writer_dir, ignore_errors=True)
    total_elapsed = round(time.perf_counter() - started, 2)
    print(f"  => Đã hoàn thành {len(outcomes)} câu hỏi trong {total_elapsed} giây.")

    summary: dict[str, Any] = {
        "total_questions": len(questions),
        "shard_index": shard_index,
        "num_shards": num_shards,
        "total_elapsed_seconds": total_elapsed,
        "output_dir": str(output_dir),
    }

    if merge_target_dir is None:
        eval_summary = _evaluate_if_answers_exist(
            split_dir=split_dir,
            output_dir=output_dir,
            questions=questions,
        )
        if eval_summary is not None:
            summary["evaluation"] = eval_summary

    print(f"\nToàn bộ kết quả và log đã được lưu tại: {output_dir}")
    print(f"  - File nộp bài        : {output_dir / 'submission.jsonl'}")
    print(f"  - Log suy nghĩ & SQL  : {output_dir / 'detailed_logs.jsonl'}")
    print(f"  - Log Grounding trace : {output_dir / 'grounding_trace.jsonl'}")
    print(f"  - Log từng câu hỏi    : {output_dir / 'logs'}")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chạy End-to-End DataMate Pipeline trên data/train hoặc data/public_test")
    parser.add_argument(
        "--split-dir",
        type=Path,
        default=Path("data/train"),
        help="Đường dẫn tới thư mục dữ liệu (data/train hoặc data/public_test)",
    )
    parser.add_argument(
        "--bundles-dir",
        type=Path,
        default=Path("artifacts/bundles"),
        help="Thư mục lưu cache DuckDB bundles của B0.1 + B0.2",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/runs/train_sample"),
        help="Thư mục lưu submission.jsonl, detailed_logs.jsonl, logs/ và eval_report.json",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/qwen3_5_9b_ft_v1_2.toml"),
        help="File cấu hình TOML cho model B0.3 (mặc định: configs/qwen3_5_9b_ft_v1_2.toml)",
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=None,
        help="Ghi đè đường dẫn tới thư mục chứa weights model trên đĩa",
    )
    parser.add_argument(
        "--lora-path",
        type=Path,
        default=None,
        help="Ghi đè đường dẫn tới thư mục chứa LoRA adapter",
    )
    parser.add_argument(
        "--no-lora",
        action="store_true",
        help="Tắt LoRA adapter trong config (dùng khi chạy base model hoặc merged checkpoint)",
    )
    parser.add_argument(
        "--prompt-format",
        type=str,
        choices=("legacy", "v1_2"),
        default=None,
        help="Ghi đè prompt format ('legacy' hoặc 'v1_2')",
    )
    parser.add_argument(
        "--grounded-hint-mode",
        type=str,
        choices=("auto", "markdown", "compact_json", "off"),
        default=None,
        help="Ghi đè cách truyền grounded_hint ('auto', 'markdown', 'compact_json', 'off'); mặc định đọc từ config",
    )
    parser.add_argument(
        "--enable-thinking",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Bật (--enable-thinking) hoặc tắt (--no-enable-thinking) suy luận <think>...</think>; mặc định lấy theo config",
    )
    parser.add_argument(
        "--grounding-engine",
        type=str,
        choices=("neo", "rules", "off"),
        default="neo",
        help="Chọn Grounding engine: 'neo' (Grounding v3 3B), 'rules' (QuestionGroundingEngine cũ), hoặc 'off'",
    )
    parser.add_argument(
        "--phase",
        type=str,
        choices=("all", "grounding", "planner"),
        default="all",
        help="Chạy riêng Pha 1 ('grounding'), Pha 2 ('planner'), hoặc toàn bộ ('all')",
    )
    parser.add_argument(
        "--two-phase",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Chạy Pha 1 (3B) và Pha 2 (9B) ở 2 subprocess tách biệt để giải phóng 100%% VRAM (mặc định: bật)",
    )
    parser.add_argument(
        "--grounding-cache",
        type=Path,
        default=None,
        help="Đường dẫn file JSONL lưu/đọc cache Grounding giữa Pha 1 và Pha 2",
    )
    parser.add_argument(
        "--enable-grounding",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Bật/tắt Grounding Engine (mặc định: bật)",
    )
    parser.add_argument(
        "--enable-grounding-llm",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Bật khởi tạo model LLM 3B (Qwen2.5-3B) cho engine 'rules' fallback (engine 'neo' luôn dùng 3B)",
    )
    parser.add_argument(
        "--grounding-config",
        type=Path,
        default=None,
        help="File cấu hình TOML cho model Grounding 3B (mặc định tự chọn theo --grounding-engine)",
    )
    parser.add_argument(
        "--grounding-model-path",
        type=Path,
        default=None,
        help="Ghi đè đường dẫn tới thư mục chứa weights của model Grounding 3B",
    )
    parser.add_argument(
        "--api-base",
        type=str,
        default=None,
        help="Tùy chọn: URL của vLLM OpenAI server từ xa (ví dụ http://localhost:8000/v1)",
    )
    parser.add_argument(
        "--api-model",
        type=str,
        default="Qwen/Qwen3.5-9B",
        help="Tên model khi dùng --api-base",
    )
    parser.add_argument(
        "--business-id",
        action="append",
        dest="business_ids",
        default=None,
        help="Chỉ chạy câu hỏi của business_id chỉ định (có thể truyền nhiều lần, vd: --business-id biz_105)",
    )
    parser.add_argument(
        "--question-id",
        action="append",
        dest="question_ids",
        default=None,
        help="Chỉ chạy question_id chỉ định (có thể truyền nhiều lần)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Giới hạn số lượng câu hỏi chạy thử (ví dụ: --limit 10)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Số lượng câu hỏi chạy suy luận song song (batch) trên GPU (mặc định 1, gợi ý 8 trên A100)",
    )
    parser.add_argument(
        "--voting",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Ghi đè bật (--voting) hoặc tắt (--no-voting) execution-result voting; mặc định đọc từ section [voting] của config",
    )
    parser.add_argument("--voting-rounds", type=int, choices=(1, 2), default=None)
    parser.add_argument("--voting-candidates", type=int, choices=(4, 8), default=None)
    parser.add_argument("--voting-threshold", type=float, default=None)
    parser.add_argument("--voting-temperature", type=float, default=None)
    parser.add_argument("--voting-top-p", type=float, default=None)
    parser.add_argument("--voting-top-k", type=int, default=None)
    parser.add_argument(
        "--voting-thinking-mode",
        type=str,
        choices=("two_round", "always_off", "always_on", "inherit"),
        default=None,
    )
    parser.add_argument(
        "--num-gpus",
        type=int,
        default=None,
        help="Số GPU chạy song song theo từng shard business_id (mặc định: tự phát hiện từ nvidia-smi/CUDA_VISIBLE_DEVICES)",
    )
    parser.add_argument(
        "--gpu-ids",
        type=str,
        default=None,
        help="Danh sách GPU ID chạy song song (vd: '0,1')",
    )
    parser.add_argument(
        "--num-shards",
        type=int,
        default=1,
        help="Tổng số shard khi chạy phân tán",
    )
    parser.add_argument(
        "--shard-index",
        type=int,
        default=0,
        help="Chỉ số shard (0 .. num_shards-1)",
    )
    parser.add_argument(
        "--merge-target-dir",
        type=Path,
        default=None,
        help="Thư mục output chung để shard ghi cập nhật trực tiếp submission.jsonl theo thời gian thực",
    )
    parser.add_argument(
        "--init-abstain",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Tạo trước submission.jsonl với toàn bộ câu hỏi ở trạng thái abstain trước khi chạy GPU (mặc định: bật)",
    )
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    parser.add_argument("--max-rows", type=int, default=10000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_pipeline_cli(
        split_dir=args.split_dir,
        bundles_dir=args.bundles_dir,
        output_dir=args.output_dir,
        config_path=args.config,
        voting=args.voting,
        voting_rounds=args.voting_rounds,
        voting_candidates=args.voting_candidates,
        voting_threshold=args.voting_threshold,
        voting_temperature=args.voting_temperature,
        voting_top_p=args.voting_top_p,
        voting_top_k=args.voting_top_k,
        voting_thinking_mode=args.voting_thinking_mode,
        model_path=args.model_path,
        lora_path=args.lora_path,
        no_lora=args.no_lora,
        prompt_format=args.prompt_format,
        grounded_hint_mode=args.grounded_hint_mode,
        grounding_engine=args.grounding_engine,
        grounding_config_path=args.grounding_config,
        grounding_model_path=args.grounding_model_path,
        grounding_cache_path=args.grounding_cache,
        phase=args.phase,
        two_phase=args.two_phase,
        num_gpus=args.num_gpus,
        gpu_ids=args.gpu_ids,
        num_shards=args.num_shards,
        shard_index=args.shard_index,
        merge_target_dir=args.merge_target_dir,
        init_abstain=args.init_abstain,
        enable_thinking=args.enable_thinking,
        enable_grounding=args.enable_grounding,
        enable_grounding_llm=args.enable_grounding_llm,
        api_base=args.api_base,
        api_model=args.api_model,
        business_ids=args.business_ids,
        question_ids=args.question_ids,
        limit=args.limit,
        batch_size=args.batch_size,
        timeout_sec=args.timeout_sec,
        max_rows=args.max_rows,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
