# neo_contracts.py

Pydantic schema cho proposal Qwen chưa xác minh.

Source: [`neo_contracts.py`](../../../../src/datamate/grounding/neo_contracts.py)

## Trách nhiệm và luồng dữ liệu

extra=forbid; enum và list bounds. Measure biểu diễn aggregate hoặc derived operands, Predicate là cây logic, Combination giữ JOIN/UNION explicit, EntityKey và UnitPlan biểu diễn grain/unit scope. Không có field cho model tự khai verified.

## Interface

- `StrictModel`: Xem implementation để biết chi tiết interface.
- `Measure`: Xem implementation để biết chi tiết interface.
- `Predicate`: Xem implementation để biết chi tiết interface.
- `Filter`: Xem implementation để biết chi tiết interface.
- `Combination`: Xem implementation để biết chi tiết interface.
- `EntityKey`: Xem implementation để biết chi tiết interface.
- `UnitPlan`: Xem implementation để biết chi tiết interface.
- `Proposal`: Xem implementation để biết chi tiết interface.

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.
