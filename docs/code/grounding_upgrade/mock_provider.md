# mock_provider.py

Mock BusinessContext provider for independent development and testing of Component C.

Source: [`mock_provider.py`](../../../../src/datamate/grounding/mock_provider.py)

## Trách nhiệm và luồng dữ liệu

Module C1–C5 legacy, giữ cho modes rules/hybrid và các caller hiện hữu. NeoGroundingEngine không gọi module này trực tiếp; không dùng kết quả heuristic để nâng trust của contract v2.

## Interface

- `InMemoryBusinessContext`: Concrete in-memory implementation of BusinessContextProtocol.
- `MockBusinessContextProvider`: Factory producing realistic mock BusinessContext objects for testing Component C.

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.
