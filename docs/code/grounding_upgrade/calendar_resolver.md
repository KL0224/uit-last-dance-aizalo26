# calendar_resolver.py

Chuyển TemporalSpec thành biên ngày dương từ calendar CSV.

Source: [`calendar_resolver.py`](../../../../src/datamate/grounding/calendar_resolver.py)

## Trách nhiệm và luồng dữ liệu

Input: CSV + TemporalSpec + as_of_date. Output: danh sách constraint event/snapshot. CalendarResolutionError được verifier chuyển thành unresolved. Xem test_neo_grounding.py cho Tết, tháng nhuận, recurrence và missing coverage.

## Interface

- `LunarEndpoint`: Xem implementation để biết chi tiết interface.
- `TemporalSpec`: Xem implementation để biết chi tiết interface.
- `CalendarResolutionError`: Xem implementation để biết chi tiết interface.
- `CalendarResolver`: Xem implementation để biết chi tiết interface.

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.

## Period extent và comparison

TemporalSpec thêm period_extent và role. Luồng wire mới bắt buộc model khai rõ extent, comparison và role; API legacy vẫn cho default để tương thích.

- full_period: cả kỳ, không tự cắt theo as_of. Mâu thuẫn với relative=this bị unresolved.
- to_as_of: đến hết as_of; code kiểm anchor nằm trong kỳ trước khi cắt biên. Áp dụng month/quarter/year/week/range.
- snapshot: dùng snapshot cutoff, không áp event window.
- unknown: không phát hành khoảng ngày đoán.

relative=this vẫn resolve kỳ theo anchor; period_extent=to_as_of quyết định clipping trong wire mới. comparison=previous_month_matched dùng cùng số ngày, clamp cuối tháng trước. Previous_year trên YTD tính ngày cuối tương ứng rồi +1 ngày, tránh tính thừa Feb 29 khi năm trước nhuận.

Một spec role=primary với comparison hợp lệ tạo t0 primary và t1 comparison. Hai spec explicit dùng role=primary/comparison và comparison=none ở wire. Verifier map none thành null cho calculator; unknown relation được giữ unresolved.

Calculator không xác minh ý nghĩa raw_expression. Constraint output dùng verification_status=reference_valid, calculation_status=calculated, semantic_status=semantic_unreviewed thay cho nhãn verified bao trùm.
