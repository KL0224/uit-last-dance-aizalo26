# engine.py

Coordinator C1–C5 cũ dùng cho rules/hybrid rollback.

Source: [`engine.py`](../../../../src/datamate/grounding/engine.py)

## Trách nhiệm và luồng dữ liệu

Chạy normalizer, intent parser, temporal resolver, schema/value grounder và answerability precheck. Luồng llm_verified mới dùng NeoGroundingEngine, không chạy coordinator này.

## Interface

- `QuestionGroundingEngine`: Central orchestrator for Component C (Question Grounding).

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.
