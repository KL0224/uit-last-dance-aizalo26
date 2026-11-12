#!/usr/bin/env python3
"""Script kiểm chứng thinking token budget trên GPU với vLLM backend.

Usage:
    python scripts/check_thinking_budget.py --budgets 32 4096
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

# Ensure repository root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from datamate.planner import (
    ChatMessage,
    GenerationOptions,
    ModelConfig,
    VLLMModel,
    load_config,
)
from datamate.planner.parser import parse_text2sql_response


def main() -> int:
    parser = argparse.ArgumentParser(description="Kiểm tra thinking token budget với checkpoint Qwen3.5")
    parser.add_argument("--config", default="configs/qwen3_5_9b.toml", help="Đường dẫn file cấu hình TOML")
    parser.add_argument("--budgets", nargs="+", type=int, default=[32, 4096], help="Danh sách ngân sách thinking cần thử")
    parser.add_argument("--model-path", default=None, help="Đường dẫn ghi đè tới snapshot model trên đĩa")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_file():
        print(f"[LỖI] Không tìm thấy file cấu hình: {config_path}", file=sys.stderr)
        return 1

    model_cfg, base_opts = load_config(config_path)
    if args.model_path:
        model_cfg = replace(model_cfg, model_path=Path(args.model_path))

    print(f"=== Đang khởi tạo VLLMModel từ {model_cfg.model_path} ===")
    model = VLLMModel(model_cfg, default_options=base_opts)
    try:
        model.load()
    except Exception as exc:
        print(f"[LỖI] Không thể nạp model: {exc}", file=sys.stderr)
        return 1

    dummy_messages = [
        ChatMessage(
            role="system",
            content=(
                "Bạn là trợ lý phân tích dữ liệu chuyên nghiệp. "
                "Hãy suy nghĩ kỹ trong <think>...</think> và trả lời bằng JSON hợp lệ "
                'với cấu trúc {"status": "answerable", "answer_type": "number", "sql": "..."}.'
            ),
        ),
        ChatMessage(
            role="user",
            content="Tính tổng doanh thu của các đơn hàng có trạng thái thành công trong bảng don_hang.",
        ),
    ]

    all_passed = True
    for budget in args.budgets:
        print(f"\n--- Thử nghiệm với thinking_token_budget = {budget} ---")
        opts = replace(base_opts, thinking_token_budget=budget)
        try:
            res = model.chat(dummy_messages, options=opts)
            print(f"  Input tokens : {res.input_tokens}")
            print(f"  Output tokens: {res.output_tokens}")
            print(f"  Finish reason: {res.finish_reason}")
            print(f"  Raw response (preview): {res.text[:200]}...")

            if "</think>" not in res.text:
                print(f"[THẤT BẠI] Không tìm thấy thẻ đóng </think> trong response với budget={budget}!", file=sys.stderr)
                all_passed = False
                continue

            if res.finish_reason == "length":
                print(f"[THẤT BẠI] Generation kết thúc bằng 'length' (chạm giới hạn max_new_tokens)!", file=sys.stderr)
                all_passed = False
                continue

            parsed = parse_text2sql_response(res.text)
            print(f"[THÀNH CÔNG] Đã parse SQL: {parsed.sql}")

        except Exception as exc:
            print(f"[LỖI] Thất bại khi chạy với budget={budget}: {exc}", file=sys.stderr)
            all_passed = False

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

