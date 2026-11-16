# __init__.py

Exports của package grounding.

Source: [`__init__.py`](../../../../src/datamate/grounding/__init__.py)

## Trách nhiệm và luồng dữ liệu

Exports legacy giữ tương thích. Module mới import trực tiếp từ datamate.grounding.neo_engine, context_index, neo_contracts và calendar_resolver. Import package không nạp vLLM/GPU.

## Interface

Module exports; không có callable public khai báo trực tiếp.

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.
