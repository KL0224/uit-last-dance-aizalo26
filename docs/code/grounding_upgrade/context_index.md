# context_index.py

Nạp bundle read-only và biên dịch metadata/evidence dùng lại theo business.

Source: [`context_index.py`](../../../../src/datamate/grounding/context_index.py)

## Trách nhiệm và luồng dữ liệu

Constructor kiểm schema thật trong DuckDB. Fingerprint gồm context, rulebook, calendar, manifest và DB stat identity; yêu cầu source immutable. prompt_context sắp xếp evidence lexical; planner_context tạo bản copy có global rules/calendar, không ghi bundle.

## Interface

- `normalized`: Xem implementation để biết chi tiết interface.
- `GroundingContextIndex`: Xem implementation để biết chi tiết interface.

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.

Sau lexical retrieval, engine hiện dùng [context_budget.py](context_budget.md) để xếp hạng lại theo capability và bảo vệ nguồn/cột. Vì vậy thứ tự lexical trong prompt_context không quyết định bảng cuối cùng được giữ khi cắt budget. planner_context vẫn trả context đầy đủ, không dùng bản đã cắt cho Qwen grounding.
