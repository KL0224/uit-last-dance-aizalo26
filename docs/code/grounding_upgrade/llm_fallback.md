# llm_fallback.py

Parser Qwen intent legacy và factory nạp vLLM.

Source: [`llm_fallback.py`](../../../../src/datamate/grounding/llm_fallback.py)

## Trách nhiệm và luồng dữ liệu

Neo engine tái sử dụng factory model/chat/token counter; không dùng prompt closed-registry hay extract_intent của legacy. Config mới 8192 context / 2048 output ở qwen2_5_3b_neo_grounding.toml.

## Interface

- `StructuredLLMParser`: Invoke Qwen2.5-3B-Instruct for structured intent extraction.
- `create_qwen3b_vllm_parser`: Load a local Qwen 3B snapshot with vLLM and build the C1 fallback parser.

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.
