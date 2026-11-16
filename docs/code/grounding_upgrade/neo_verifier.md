# neo_verifier.py

Kiểm proposal và dựng tám nhóm PlannerGroundingInput.

Source: [`neo_verifier.py`](../../../../src/datamate/grounding/neo_verifier.py)

## Trách nhiệm và luồng dữ liệu

Kiểm refs, cycle, aggregate numeric types, predicate tree, filter scope, JOIN key ownership, UNION layout, unit factor và temporal scope. Value lookup exact nếu provider được cấp. Không chứng minh ngữ nghĩa bằng cột tồn tại; assessment giữ partial/unknown.

## Interface

- `verify_proposal`: Xem implementation để biết chi tiết interface.

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.

## Temporal completeness

Verifier gọi temporal_validation sau khi tính window. Thiếu kỳ so sánh giữ các nhóm hữu ích nhưng thêm lỗi cụ thể vào assessment.unresolved và temporal_plan.completeness_status=incomplete. Unknown comparison giữ primary đã tính; unknown extent không phát hành window. Không gọi sửa model và không tự đoán ngày từ raw_expression.

Constraint reference_valid + calculation_status=calculated chỉ xác nhận tham chiếu và phép tính; semantic_status=semantic_unreviewed giữ rõ giới hạn. Xem temporal_validation.md.

## Partial recovery v6

Verifier loại claim lỗi riêng cho measures, filters, dimensions, order_by, combinations, entity keys, cohort, unit plan và time. Derived measure phụ thuộc operand bị loại cũng bị loại; mọi tham chiếu trong active plan phải còn tồn tại. Measure trùng ID bị loại toàn bộ các bản trùng, không chọn bản đầu. Không giữ một phần cây OR/NOT vì sẽ đổi nghĩa.

Assessment bổ sung:

- `rejected_claims`: group/ref/code/reason/raw claim/affects; chỉ là chẩn đoán, không phải constraint hoạt động.
- `unresolved` và `warnings`: mô tả rõ phần bị loại, giữ yêu cầu gốc cho Planner sửa.
- `blocked_refs`: measure còn binding hữu ích nhưng mất filter/time/unit/JOIN hoặc dependency cần thiết.
- `group_status`: accepted/rejected và trạng thái theo nhóm; temporal có thêm số unbound.

Measure có dependency thiếu mang `usage_status=requires_repair`; measure khác vẫn là candidate với semantic_unreviewed. Block được truyền tiếp qua derived operands. Không biến kết quả partial thành query không lọc/thời gian hoặc thành unsupported.

Nếu cột ngày và phép tính đúng nhưng applies_to chưa resolve, biên ngày được giữ ở `temporal_plan.unbound_constraints`, applies_to=[], requested_applies_to ghi scope gốc và usage_status=requires_repair. Không đưa chúng vào active constraints hoặc tính là temporal complete trước khi bind scope.

Planner hint nhắc rõ phải sửa blocked refs, không áp raw rejected claims và phải bind unbound dates. Partial chỉ xác nhận phần kiểm được bằng code; không nâng binding giá lẻ thành doanh thu vì cột là numeric. Business mismatch, không có nguồn hợp lệ và lỗi runtime ngoài các validation dự kiến vẫn dừng để pipeline fallback.

Kiểm thử bổ sung: [test_partial_grounding.py](../../../../tests/grounding/test_partial_grounding.py). Có kiểm schema/alias lỗi riêng, cycle/dependencies, predicate atomicity, lookup failure và đưa partial hint qua Planner generation/repair.
