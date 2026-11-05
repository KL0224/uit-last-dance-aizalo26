"""Sample inference script for B0.3 Text-to-SQL LLM layer."""

from __future__ import annotations

from pathlib import Path

from datamate.b0.b03 import ChatMessage, GenerationOptions, VLLMModel, load_config


def run_sample_inference(config_path: str | Path = "configs/qwen3_5_9b.toml") -> None:
    config, options = load_config(config_path)
    model = VLLMModel(config, options)
    model.load()

    result = model.chat([
        ChatMessage(role="system", content="Bạn là trợ lý trả lời bằng tiếng Việt."),
        ChatMessage(role="user", content="Giải thích self-attention."),
    ])
    print(result.text)


if __name__ == "__main__":
    run_sample_inference()
