"""Ví dụ chủ động load model rồi gọi ba method; chỉ chạy trên server GPU."""

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path

from datamate.b0.b03 import BaseLLM, ChatMessage, GenerationResult, VLLMModel, load_config


def print_result(label: str, result: GenerationResult) -> None:
    """In object kết quả để quan sát cả token usage và finish_reason."""
    print(f"\n--- {label} ---")
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path,
        default=Path(__file__).resolve().parents[1] / "configs/qwen3_5_9b.toml",
    )
    args = parser.parse_args()
    config, defaults = load_config(args.config)
    # Chỉ thay config để đổi checkpoint tương thích vLLM. Caller sử dụng
    # BaseLLM nên backend mới có thể thay VLLMModel mà không đổi các lời gọi.
    model: BaseLLM = VLLMModel(config, default_options=defaults)
    model.load()  # Dòng đầu tiên khởi tạo GPU; không đặt ở cấp module.
    model.load()  # No-op vì engine đã load thành công.

    # Raw completion không áp dụng chat template. Với model instruct, chat()
    # thường là lựa chọn phù hợp hơn cho câu hỏi/instruction tự nhiên.
    short = replace(defaults, max_new_tokens=128)
    print_result("generate", model.generate("The capital of Vietnam is", options=short))
    print_result("chat", model.chat([
        ChatMessage(role="system", content="Bạn là trợ lý trả lời ngắn gọn bằng tiếng Việt."),
        ChatMessage(role="user", content="Giải thích ngắn gọn khóa chính trong cơ sở dữ liệu."),
    ], options=short))
    results = model.generate_batch([
        "SQL stands for",
        "A primary key is",
    ], options=short)
    for index, result in enumerate(results):
        print_result(f"batch[{index}]", result)
    # Không có unload() giả định rằng del object sẽ giải phóng hết GPU.
    # Kết thúc process là ranh giới lifecycle của engine ở bản đầu.


if __name__ == "__main__":
    # Main guard cần thiết khi inference engine tạo worker processes.
    main()
