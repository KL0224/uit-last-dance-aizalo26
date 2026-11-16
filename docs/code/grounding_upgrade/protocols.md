# protocols.py

Protocols decoupling Component C (Question Grounding) from B0.1/B0.2 and LLM backends.

Source: [`protocols.py`](../../../../src/datamate/grounding/protocols.py)

## Trách nhiệm và luồng dữ liệu

Module C1–C5 legacy, giữ cho modes rules/hybrid và các caller hiện hữu. NeoGroundingEngine không gọi module này trực tiếp; không dùng kết quả heuristic để nâng trust của contract v2.

## Interface

- `ColumnSpec`: Lightweight column metadata descriptor for grounding.
- `TableSpec`: Lightweight table metadata descriptor for grounding.
- `JoinSpec`: Join edge specification between two tables.
- `MetricSpec`: Semantic metric contract from B3 Metric Registry.
- `CalendarEventSpec`: Named temporal period or holiday (e.g., Lunar New Year / Tết).
- `BusinessContextProtocol`: Protocol that any BusinessContext (mock or B0.2 adapter) must satisfy.
- `LLMParserProtocol`: Protocol for the 3B Semantic Extractor fallback (e.g., Qwen2.5-3B-Instruct).

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.
