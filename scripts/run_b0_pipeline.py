#!/usr/bin/env python3
"""CLI chuẩn để chạy luồng End-to-End B0 (B0.1 -> B0.5) trên data/train hoặc data/public_test.

Các tệp đầu ra được lưu tại `--output-dir`:
  1. `submission.jsonl`   : Kết quả định dạng nộp bài chính thức (`{"id", "type", "answer"}`).
  2. `gate_trace.jsonl`   : Bản ghi tóm tắt quyết định của cổng B0.5 cho từng câu hỏi.
  3. `detailed_logs.jsonl`: Nhật ký đầy đủ gồm câu hỏi, từng lần thử (attempt 0/1), câu SQL,
                            suy nghĩ của LLM (`thinking`), giả định (`assumptions`) và lỗi DuckDB.
  4. `logs/<id>_<hash>.json`: File JSON kiểm toán riêng cho từng câu hỏi.
  5. `eval_report.json`   : Báo cáo đối chiếu độ chính xác (Exact Match) nếu có `answers.jsonl`.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")

# Cho phép chạy trực tiếp bằng `python scripts/run_b0_pipeline.py` mà không cần đặt PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR / "src") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "src"))

from datamate.b0 import B0Pipeline
from datamate.b0.b03 import (
    BaseLLM,
    ChatMessage,
    GenerationOptions,
    GenerationResult,
    Text2SQLGenerator,
    VLLMModel,
    load_config,
)
from datamate.b0.b03.errors import InferenceError


class OpenAICompatibleLLM(BaseLLM):
    """Client kết nối tới vLLM/OpenAI-compatible server từ xa (tùy chọn `--api-base`)."""

    def __init__(
        self,
        base_url: str,
        model_name: str,
        api_key: str = "EMPTY",
        timeout: float = 120.0,
        default_options: GenerationOptions | None = None,
    ) -> None:
        from openai import OpenAI

        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.model_name = model_name
        self.default_options = default_options or GenerationOptions()

    def chat(
        self,
        messages: list[ChatMessage],
        options: GenerationOptions | None = None,
    ) -> GenerationResult:
        opts = options or self.default_options
        payload = [{"role": m.role, "content": m.content} for m in messages]
        try:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=payload,
                temperature=opts.temperature,
                top_p=opts.top_p,
                max_tokens=opts.max_new_tokens,
                presence_penalty=opts.presence_penalty,
                stop=list(opts.stop) if opts.stop else None,
            )
        except Exception as exc:
            raise InferenceError(f"OpenAI API inference failed: {exc}") from exc

        choice = resp.choices[0]
        msg = choice.message
        content = msg.content or ""
        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning and "<think>" not in content:
            content = f"<think>{reasoning}</think>\n{content}"
        usage = resp.usage
        return GenerationResult(
            text=content,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            finish_reason=choice.finish_reason,
        )

    def chat_batch(
        self,
        messages_batch: list[list[ChatMessage]],
        options: GenerationOptions | None = None,
    ) -> list[GenerationResult]:
        if not messages_batch:
            return []
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(messages_batch), 16)) as executor:
            futures = [executor.submit(self.chat, msgs, options) for msgs in messages_batch]
            return [f.result() for f in futures]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


import re
import unicodedata


def _norm_str(val: str) -> str:
    """Chuẩn hóa chuỗi theo Mục 9 rulebook: không phân biệt hoa thường, khoảng trắng, dấu câu (giữ nguyên dấu tiếng Việt)."""
    cleaned = "".join(
        ch if unicodedata.category(ch)[0] in {"L", "M", "N"} else " "
        for ch in val.lower()
    )
    return " ".join(cleaned.split())


def _scalar_equal(pred_val: Any, gold_val: Any, aliases: list[Any] | None = None) -> bool:
    """So sánh 1 giá trị đơn lẻ (số, chuỗi, boolean, ngày) kèm danh sách alias."""
    candidates = [gold_val] + list(aliases or [])
    for cand in candidates:
        if pred_val == cand:
            return True
        if isinstance(pred_val, (int, float)) and not isinstance(pred_val, bool) and isinstance(cand, (int, float)) and not isinstance(cand, bool):
            if abs(float(pred_val) - float(cand)) <= 1e-6:
                return True
        if isinstance(pred_val, str) and isinstance(cand, str):
            if _norm_str(pred_val) == _norm_str(cand):
                return True
    return False


def AnswersMatch(pred: dict[str, Any], gold: dict[str, Any]) -> bool:
    """So sánh kết quả dự đoán với đáp án chuẩn trong `answers.jsonl` theo đúng Mục 9 của rulebook.md."""
    pred_type = pred.get("type")
    gold_type = gold.get("type")
    if pred_type != gold_type:
        return False
    if gold_type in {"unanswerable", "abstain"}:
        return True

    pred_ans = pred.get("answer")
    gold_ans = gold.get("answer")
    alias = list(gold.get("alias") or [])

    # 1. Kiểu vô hướng: number, percent, string, date, boolean
    if gold_type in {"number", "percent", "string", "date", "boolean"}:
        return _scalar_equal(pred_ans, gold_ans, alias)

    # 2. Kiểu danh sách (list): đúng cả tập và thứ tự; alias[i] là danh sách cách viết thay thế cho phần tử i
    if gold_type == "list":
        if not isinstance(pred_ans, list) or not isinstance(gold_ans, list):
            return False
        if len(pred_ans) != len(gold_ans):
            return False
        for idx, (p_item, g_item) in enumerate(zip(pred_ans, gold_ans)):
            item_aliases = alias[idx] if (idx < len(alias) and isinstance(alias[idx], list)) else []
            if not _scalar_equal(p_item, g_item, item_aliases):
                return False
        return True

    # 3. Kiểu bảng (table): cột so theo tên (nếu không khớp thì so theo vị trí); thứ tự dòng không ảnh hưởng;
    #    cột đầu của dòng thứ i có thể khớp với alias[i] (mã đối tượng hoặc cách viết khác)
    if gold_type == "table":
        if not isinstance(pred_ans, dict) or not isinstance(gold_ans, dict):
            return False
        pred_cols = list(pred_ans.get("columns") or [])
        gold_cols = list(gold_ans.get("columns") or [])
        pred_rows = list(pred_ans.get("rows") or [])
        gold_rows = list(gold_ans.get("rows") or [])
        if len(pred_cols) != len(gold_cols) or len(pred_rows) != len(gold_rows):
            return False

        # Nếu tập tên cột khớp nhau (không phân biệt hoa/thường), ánh xạ cột theo tên; ngược lại so theo vị trí
        pred_cols_lower = [str(c).strip().lower() for c in pred_cols]
        gold_cols_lower = [str(c).strip().lower() for c in gold_cols]
        if set(pred_cols_lower) == set(gold_cols_lower) and len(set(pred_cols_lower)) == len(gold_cols_lower):
            col_map = [pred_cols_lower.index(gc) for gc in gold_cols_lower]
        else:
            col_map = list(range(len(gold_cols)))

        reordered_pred_rows = []
        for r in pred_rows:
            if not isinstance(r, list) or len(r) != len(pred_cols):
                return False
            reordered_pred_rows.append([r[i] for i in col_map])

        # Ghép cặp từng dòng chuẩn với dòng dự đoán (thứ tự các dòng không ảnh hưởng kết quả chấm)
        used_pred: set[int] = set()
        for g_idx, g_row in enumerate(gold_rows):
            row_aliases = alias[g_idx] if (g_idx < len(alias) and isinstance(alias[g_idx], list)) else []
            matched_row = False
            for p_idx, p_row in enumerate(reordered_pred_rows):
                if p_idx in used_pred:
                    continue
                # Cột 0 là tên đối tượng (được phép khớp alias[g_idx]), các cột sau là số đo
                if not _scalar_equal(p_row[0], g_row[0], row_aliases):
                    continue
                if all(_scalar_equal(p_row[c], g_row[c]) for c in range(1, len(g_row))):
                    used_pred.add(p_idx)
                    matched_row = True
                    break
            if not matched_row:
                return False
        return True

    return pred_ans == gold_ans


def evaluate_predictions(
    submission_path: Path,
    answers_path: Path,
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Chấm điểm submission.jsonl so với answers.jsonl và trả về báo cáo chi tiết."""
    preds_by_id = {item["id"]: item for item in load_jsonl(submission_path)}
    golds_by_id = {item["id"]: item for item in load_jsonl(answers_path)}
    q_by_id = {item["id"]: item for item in questions}

    total = 0
    correct = 0
    wrong = 0
    abstained = 0
    details: list[dict[str, Any]] = []

    for q_id, q_item in q_by_id.items():
        if q_id not in golds_by_id:
            continue
        total += 1
        gold = golds_by_id[q_id]
        pred = preds_by_id.get(q_id, {"id": q_id, "type": "abstain"})
        is_abstain = pred.get("type") == "abstain"
        if is_abstain:
            abstained += 1
            matched = False
            score = 0
        else:
            matched = AnswersMatch(pred, gold)
            if matched:
                correct += 1
                score = 1
            else:
                wrong += 1
                score = -1
        details.append(
            {
                "id": q_id,
                "business_id": q_item.get("business_id"),
                "question": q_item.get("question"),
                "as_of_date": q_item.get("as_of_date"),
                "matched": matched,
                "pa_score": score,
                "predicted": pred,
                "expected": {
                    "type": gold.get("type"),
                    "answer": gold.get("answer"),
                    "alias": gold.get("alias", []),
                },
            }
        )

    accuracy = round((correct / total) * 100.0, 2) if total else 0.0
    pa_raw = correct - wrong
    pa_score = round(pa_raw / total, 4) if total else 0.0
    pa_percent = round((pa_raw / total) * 100.0, 2) if total else 0.0
    return {
        "total_evaluated": total,
        "correct": correct,
        "wrong": wrong,
        "abstained": abstained,
        "accuracy_percent": accuracy,
        "pa_points": pa_raw,
        "pa_score": pa_score,
        "pa_percent": pa_percent,
        "details": details,
    }


def run_pipeline_cli(
    *,
    split_dir: Path,
    bundles_dir: Path,
    output_dir: Path,
    config_path: Path,
    model_path: Path | None = None,
    enable_thinking: bool | None = None,
    api_base: str | None = None,
    api_model: str | None = None,
    business_ids: list[str] | None = None,
    question_ids: list[str] | None = None,
    limit: int | None = None,
    batch_size: int = 1,
    timeout_sec: float = 10.0,
    max_rows: int = 10000,
    on_bundle_ready: Any = None,
) -> dict[str, Any]:
    """Thực thi trọn vẹn pipeline B0.1 -> B0.5 và lưu đầy đủ kết quả + log."""
    split_dir = split_dir.resolve()
    bundles_dir = bundles_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    questions_path = split_dir / "questions.jsonl"
    if not questions_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy questions.jsonl tại: {questions_path}")

    questions = load_jsonl(questions_path)
    if business_ids:
        allowed_biz = set(business_ids)
        questions = [q for q in questions if q.get("business_id") in allowed_biz]
    if question_ids:
        allowed_q = set(question_ids)
        questions = [q for q in questions if q.get("id") in allowed_q]
    if limit is not None and limit > 0:
        questions = questions[:limit]

    if not questions:
        raise ValueError("Không có câu hỏi nào thỏa mãn bộ lọc (--business-id / --question-id / --limit).")

    target_businesses = sorted({str(q["business_id"]) for q in questions if q.get("business_id")})
    print(f"[1/4] Chuẩn bị dữ liệu B0.1 + B0.2 cho {len(target_businesses)} doanh nghiệp ({len(questions)} câu hỏi)...")

    rulebook = split_dir / "rulebook.md" if (split_dir / "rulebook.md").is_file() else None
    calendar = split_dir / "calendar.csv" if (split_dir / "calendar.csv").is_file() else None

    bundles: dict[str, Path] = {}
    for biz_id in target_businesses:
        biz_path = split_dir / "data" / biz_id
        if not biz_path.is_dir():
            print(f"  [CẢNH BÁO] Không tìm thấy thư mục dữ liệu cho {biz_id} tại {biz_path}")
            continue
        t0 = time.perf_counter()
        biz_relationships = None
        for cand in (
            split_dir / "relationships" / f"{biz_id}.json",
            ROOT_DIR / "examples" / "relationships" / f"{biz_id}.json",
        ):
            if cand.is_file():
                biz_relationships = cand
                break

        artifacts = B0Pipeline.prepare_bundle(
            business_dir=biz_path,
            output_dir=bundles_dir,
            rulebook=rulebook,
            calendar=calendar,
            relationships=biz_relationships,
        )
        elapsed = time.perf_counter() - t0
        cache_tag = "CACHE HIT" if artifacts.cache_hit else "BUILT"
        print(f"  - {biz_id}: {cache_tag} ({elapsed:.2f}s) -> {artifacts.bundle_dir}")
        bundles[biz_id] = artifacts.bundle_dir
        if on_bundle_ready is not None:
            try:
                on_bundle_ready(biz_id, artifacts.bundle_dir)
            except Exception:
                pass

    print("[2/4] Khởi tạo mô hình LLM (B0.3)...")
    model_cfg, gen_opts = load_config(config_path)
    if model_path is not None:
        model_cfg = replace(model_cfg, model_path=Path(model_path).expanduser().resolve())
    if enable_thinking is not None:
        kw = dict(model_cfg.chat_template_kwargs)
        kw["enable_thinking"] = bool(enable_thinking)
        model_cfg = replace(model_cfg, chat_template_kwargs=kw)

    llm: BaseLLM
    if api_base:
        resolved_name = api_model or "Qwen/Qwen3.5-9B"
        print(f"  - Kết nối tới OpenAI-compatible server: {api_base} (model={resolved_name})")
        llm = OpenAICompatibleLLM(
            base_url=api_base,
            model_name=resolved_name,
            default_options=gen_opts,
        )
    else:
        print(
            f"  - Nạp offline vLLM model từ: {model_cfg.model_path} "
            f"(enable_thinking={model_cfg.chat_template_kwargs.get('enable_thinking')})"
        )
        vllm_engine = VLLMModel(model_cfg, default_options=gen_opts)
        vllm_engine.load()
        llm = vllm_engine

    pipeline = B0Pipeline(
        generator=Text2SQLGenerator(llm),
        timeout_sec=timeout_sec,
        max_rows=max_rows,
        options=gen_opts,
    )

    # Xóa các file kết quả cũ trong cùng output_dir nếu chạy lại để tránh trùng lặp
    for stale in ("submission.jsonl", "gate_trace.jsonl", "detailed_logs.jsonl", "eval_report.json"):
        stale_path = output_dir / stale
        if stale_path.exists():
            stale_path.unlink()

    print(f"[3/4] Đang chạy {len(questions)} câu hỏi qua luồng B0.3 -> B0.4 -> B0.5...", flush=True)
    started = time.perf_counter()
    outcomes = pipeline.run_questions(
        questions=questions,
        bundles=bundles,
        output_dir=output_dir,
        batch_size=batch_size,
        verbose=True,
    )
    total_elapsed = time.perf_counter() - started

    # Ghi thêm gate_trace.jsonl tổng hợp để dễ tra cứu nhanh
    gate_trace_path = output_dir / "gate_trace.jsonl"
    with gate_trace_path.open("w", encoding="utf-8") as gf:
        for outcome in outcomes:
            trace_line = {
                "question_id": outcome.question_id,
                "action": outcome.action,
                "decision": outcome.decision,
                "reason_code": outcome.reason_code,
                "retry_count": outcome.retry_count,
                "validation": outcome.validation,
                "final_answer": outcome.final_answer.to_submission_dict() if outcome.final_answer else None,
            }
            gf.write(json.dumps(trace_line, ensure_ascii=False) + "\n")

    summary: dict[str, Any] = {
        "split_dir": str(split_dir),
        "output_dir": str(output_dir),
        "questions_count": len(questions),
        "elapsed_seconds": round(total_elapsed, 2),
        "submission_file": str(output_dir / "submission.jsonl"),
        "gate_trace_file": str(gate_trace_path),
        "detailed_logs_file": str(output_dir / "detailed_logs.jsonl"),
        "per_question_logs_dir": str(output_dir / "logs"),
    }

    answers_path = split_dir / "answers.jsonl"
    if answers_path.is_file():
        print("[4/4] Đang chấm điểm kết quả với answers.jsonl...")
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
    print(f"  - File nộp bài       : {output_dir / 'submission.jsonl'}")
    print(f"  - Log suy nghĩ & SQL : {output_dir / 'detailed_logs.jsonl'}")
    print(f"  - Log từng câu hỏi   : {output_dir / 'logs'}")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chạy End-to-End B0 Pipeline trên data/train hoặc data/public_test")
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
        default=Path("configs/qwen3_5_9b.toml"),
        help="File cấu hình TOML cho model B0.3",
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=None,
        help="Ghi đè đường dẫn tới thư mục chứa weights model trên đĩa",
    )
    parser.add_argument(
        "--enable-thinking",
        action="store_true",
        help="Bật chế độ sinh khối suy luận <think>...</think> của Qwen3 và lưu vào log",
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
        model_path=args.model_path,
        enable_thinking=True if args.enable_thinking else None,
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

