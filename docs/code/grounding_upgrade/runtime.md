# runtime.py

Boundary kiểm request, protocol và business identity rồi gọi engine.

Source: [`runtime.py`](../../../../src/datamate/grounding/runtime.py)

## Trách nhiệm và luồng dữ liệu

Có thể inject QuestionGroundingEngine hoặc NeoGroundingEngine (cùng ground(request, context)). Lỗi được phân loại GROUNDING_FAILED; pipeline hiện có fallback không hint. Không nạp GPU khi import.

## Interface

- `QuestionGroundingRuntimeError`: Expose a stable grounding error without leaking question/context data.
- `QuestionGroundingRuntime`: Validate the runtime boundary and execute Grounding C1 through C5 once.

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.
