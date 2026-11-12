"""Sample inference script for B0.3 Text-to-SQL LLM layer."""

from __future__ import annotations

from pathlib import Path

from datamate.planner import (
    ChatMessage,
    Text2SQLGenerator,
    VLLMModel,
    load_config,
)


def run_sample_inference(config_path: str | Path = "configs/qwen3_5_9b.toml") -> None:
    config, options = load_config(config_path)
    model = VLLMModel(config, options)
    model.load()

    # 1. Test direct chat
    chat_result = model.chat([
        ChatMessage(role="system", content="Bạn là trợ lý AI trả lời bằng tiếng Việt."),
        ChatMessage(role="user", content="Giải thích khái niệm Text-to-SQL trong phân tích dữ liệu."),
    ])
    print("[Sample Chat Completion]:")
    print(chat_result.text)

    # 2. Test Text-to-SQL Generator
    generator = Text2SQLGenerator(model)
    dummy_context = {
        "schema_catalog": {
            "tables": [
                {
                    "name": "orders",
                    "grain": "Mỗi dòng là một đơn hàng",
                    "columns": [
                        {"name": "order_id", "data_type": "VARCHAR", "nullable": False},
                        {"name": "order_date", "data_type": "DATE", "nullable": False},
                        {"name": "amount", "data_type": "DECIMAL", "nullable": False},
                    ],
                    "primary_key_candidates": ["order_id"],
                }
            ]
        }
    }
    sql_result = generator.generate(
        context=dummy_context,
        question="Tổng doanh thu năm 2025 là bao nhiêu?",
        as_of_date="2026-01-01",
    )
    print("\n[Sample Text-to-SQL Result]:")
    print(f"Status: {sql_result.status}")
    print(f"Answer Type: {sql_result.answer_type}")
    print(f"SQL: {sql_result.sql}")


if __name__ == "__main__":
    run_sample_inference()
