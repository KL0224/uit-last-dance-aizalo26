# parser.py

C1: Hybrid Question Parser & Intent Extractor (Rule Fast-Path + 3B LLM Fallback).

Source: [`parser.py`](../../../../src/datamate/grounding/parser.py)

## Trách nhiệm và luồng dữ liệu

Module C1–C5 legacy, giữ cho modes rules/hybrid và các caller hiện hữu. NeoGroundingEngine không gọi module này trực tiếp; không dùng kết quả heuristic để nâng trust của contract v2.

## Interface

- `FallbackDecision`: Evidence-backed decision for routing C1 from rules to the 3B parser.
- `QuestionIntentParser`: Hybrid C1 parser combining deterministic Vietnamese rules with 3B LLM fallback.

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.
