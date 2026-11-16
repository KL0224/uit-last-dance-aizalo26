# normalizer.py

Deterministic normalization for common Vietnamese question shorthand.

Source: [`normalizer.py`](../../../../src/datamate/grounding/normalizer.py)

## Trách nhiệm và luồng dữ liệu

Module C1–C5 legacy, giữ cho modes rules/hybrid và các caller hiện hữu. NeoGroundingEngine không gọi module này trực tiếp; không dùng kết quả heuristic để nâng trust của contract v2.

## Interface

- `VietnameseQuestionNormalizer`: Expand a conservative allowlist of shorthand before all grounding stages.

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.
