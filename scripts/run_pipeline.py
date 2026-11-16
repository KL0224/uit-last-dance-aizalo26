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
import sys
import time
from typing import Any

os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR / "src") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "src"))

from datamate.context.contracts import BusinessRule
from datamate.context.runtime import sync_unit_conversions_to_bundle
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
    grounding_config_path: Path | None = None,
    grounding_model_path: Path | None = None,
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
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== KHỞI ĐỘNG DATAMATE PIPELINE ===")
    print(f"  - Thư mục dữ liệu : {split_dir}")
    print(f"  - Thư mục bundles  : {bundles_dir}")
    print(f"  - Thư mục kết quả : {output_dir}")
    print(f"  - Batch size      : {batch_size}")
    print(f"  - Enable Grounding: {enable_grounding}")
    print(f"  - Grounding 3B LLM: {enable_grounding_llm}")

    questions_path = split_dir / "questions.jsonl"
    if not questions_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file câu hỏi: {questions_path}")

    all_questions: list[dict[str, Any]] = []
    with questions_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                all_questions.append(json.loads(line))

    # Lọc câu hỏi theo business_ids hoặc question_ids nếu được chỉ định
    questions = all_questions
    if business_ids:
        b_set = set(business_ids)
        questions = [q for q in questions if q.get("business_id") in b_set]
    if question_ids:
        q_set = set(question_ids)
        questions = [q for q in questions if str(q.get("id")) in q_set]
    if limit and limit > 0:
        questions = questions[:limit]

    if not questions:
        print("CẢNH BÁO: Không có câu hỏi nào khớp với bộ lọc!")
        return {}

    needed_businesses = sorted({q["business_id"] for q in questions if q.get("business_id")})
    print(f"  - Tổng số câu hỏi : {len(questions)} (thuộc {len(needed_businesses)} doanh nghiệp)")

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

        # Kiểm tra nếu đã có bundle hoàn chỉnh (enriched) được tạo trước đó
        if out_b.is_dir():
            ready_subdirs = [
                p for p in out_b.iterdir()
                if p.is_dir() and (p / "business_context.json").is_file() and (p / "data.duckdb").is_file()
            ]
            if ready_subdirs:
                bundles[biz_id] = ready_subdirs[0]
                print(f"  -> Tái sử dụng bundle đã sẵn sàng cho {biz_id}: {ready_subdirs[0].name[:8]}...")
                continue

        rulebook = split_dir / "rulebook.txt"
        if not rulebook.is_file():
            rulebook = split_dir / "rulebook.md"
        calendar = split_dir / "calendar.csv"
        if not calendar.is_file():
            calendar = split_dir / "data" / "calendar.csv"
        relationships = split_dir / "relationships.json"
        if not relationships.is_file():
            relationships = split_dir / "data" / "relationships.json"
        res = DataMatePipeline.prepare_bundle(
            business_dir=biz_dir,
            output_dir=out_b,
            rulebook=rulebook if rulebook.is_file() else None,
            calendar=calendar if calendar.is_file() else None,
            relationships=relationships if relationships.is_file() else None,
        )
        bundles[biz_id] = res.bundle_dir
    print(f"  => Đã sẵn sàng {len(bundles)} bundles.")

    # [2/4] Nạp mô hình LLM (Grounding Fallback 3B và Generator 9B)
    grounding_runtime = None
    if enable_grounding:
        if enable_grounding_llm:
            g_cfg_path = (grounding_config_path or (ROOT_DIR / "configs" / "qwen2_5_3b_grounding.toml")).resolve()
            print(f"\n[2.1/4] Đang khởi tạo mô hình Grounding C1 Fallback (3B) từ {g_cfg_path}...")
            from datamate.grounding import QuestionGroundingEngine, QuestionGroundingRuntime

            g_engine = QuestionGroundingEngine.from_qwen3b_vllm(
                config_path=g_cfg_path,
                model_path_override=grounding_model_path,
            )
            grounding_runtime = QuestionGroundingRuntime(engine=g_engine)
            print("  => Đã nạp thành công mô hình Grounding 3B vào VRAM.")

            # [2.1b/4] Chạy Semantic Discovery bằng mô hình 3B cho các doanh nghiệp
            if g_engine.chat_fn is not None:
                print("\n[2.1b/4] Đang kích hoạt mô hình 3B phân tích toàn diện ngữ nghĩa (Semantic Discovery)...")
                from datamate.context.semantic_extractor import create_semantic_extractor
                from datamate.ingestion.contracts import ColumnMetadata, SchemaCatalog, TableMetadata

                extractor = create_semantic_extractor(chat_fn=g_engine.chat_fn)
                for b_id, b_path in bundles.items():
                    b_ctx_file = Path(b_path) / "business_context.json"
                    if b_ctx_file.is_file():
                        try:
                            ctx_data = json.loads(b_ctx_file.read_text())
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
                            
                            # Nếu trích xuất được bảng quy đổi đơn vị (unit_conversions), ghi nhận 2 chiều vào DuckDB và schema_catalog
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

                            b_ctx_file.write_text(json.dumps(ctx_data, ensure_ascii=False, indent=2))
                            print(f"  => Doanh nghiệp {b_id}: 3B đã phát hiện {len(sem_cat.metrics)} chỉ số và {len(sem_cat.suggested_joins)} liên kết bảng.")
                        except Exception as exc:
                            print(f"  ! Cảnh báo khi 3B phân tích ngữ nghĩa cho {b_id}: {exc}")
        else:
            print("\n[2.1/4] Grounding Engine sử dụng chế độ Pure Rule-Based (Deterministic Fast-Path).")

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

    # Xóa các file kết quả cũ trong cùng output_dir nếu chạy lại để tránh trùng lặp
    for stale in (
        "submission.jsonl",
        "submission.manifest.json",
        "gate_trace.jsonl",
        "detailed_logs.jsonl",
        "eval_report.json",
        "grounding_trace.jsonl",
    ):
        stale_path = output_dir / stale
        if stale_path.exists():
            stale_path.unlink()

    stale_logs_dir = output_dir / "logs"
    if stale_logs_dir.is_dir():
        shutil.rmtree(stale_logs_dir)

    print(f"[3/4] Đang chạy {len(questions)} câu hỏi qua luồng DataMate Pipeline...", flush=True)
    started = time.perf_counter()
    outcomes = pipeline.run_questions(
        questions=questions,
        bundles=bundles,
        output_dir=output_dir,
        batch_size=batch_size,
        verbose=verbose,
    )
    total_elapsed = round(time.perf_counter() - started, 2)
    print(f"  => Đã hoàn thành {len(outcomes)} câu hỏi trong {total_elapsed} giây.")

    # [4/4] Đánh giá nếu có answers.jsonl
    answers_path = split_dir / "answers.jsonl"
    summary: dict[str, Any] = {
        "total_questions": len(questions),
        "total_elapsed_seconds": total_elapsed,
        "output_dir": str(output_dir),
    }

    if answers_path.is_file():
        print(f"\n[4/4] Đang đối chiếu với đáp án chuẩn: {answers_path}...")
        eval_report = evaluate_predictions(
            submission_path=output_dir / "submission.jsonl",
            answers_path=answers_path,
            questions=questions,
        )
        eval_path = output_dir / "eval_report.json"
        eval_path.write_text(json.dumps(eval_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
        print(
            f"  => KẾT QUẢ ĐÁNH GIÁ (N={eval_report['total_evaluated']}):\n"
            f"     - Đúng (+1)   : {eval_report['correct']} ({eval_report['accuracy_percent']}%)\n"
            f"     - Sai (-1)    : {eval_report['wrong']}\n"
            f"     - Abstain (0) : {eval_report['abstained']}\n"
            f"     - ĐIỂM PA     : {eval_report['pa_score']} ({eval_report['pa_percent']}%) [PA Points = {eval_report['pa_points']}/{eval_report['total_evaluated']}]",
            flush=True,
        )
    else:
        print("[4/4] Hoàn tất (không có answers.jsonl trong thư mục này — chế độ public_test/submission).")

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
        "--enable-grounding",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Bật/tắt Grounding Engine C1-C5 (mặc định: bật)",
    )
    parser.add_argument(
        "--enable-grounding-llm",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Bật khởi tạo model LLM 3B (Qwen2.5-3B) phục vụ Fallback cho Grounding C1",
    )
    parser.add_argument(
        "--grounding-config",
        type=Path,
        default=Path("configs/qwen2_5_3b_grounding.toml"),
        help="File cấu hình TOML cho model Grounding 3B fallback",
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
        grounding_config_path=args.grounding_config,
        grounding_model_path=args.grounding_model_path,
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
