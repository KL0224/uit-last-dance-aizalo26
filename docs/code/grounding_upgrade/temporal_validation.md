# temporal_validation.py

Source: [temporal_validation.py](../../../../src/datamate/grounding/temporal_validation.py).

`check_temporal_completeness(proposal, constraints, unresolved)` đối chiếu temporal intent với các khoảng code materialize. Trả temporal_plan gồm `intent`, `completeness_status`, `constraints` và danh sách lỗi cụ thể để merge vào assessment.unresolved/warnings. Không đọc câu hỏi bằng regex và không đoán kỳ thiếu.

`temporal_intent` gồm none/single_period/compare_periods/compare_measures/unknown. Percent_change/comparison cần đủ hai kỳ, trừ khi khai báo compare_measures và có hai measure operands khác ID được bind rõ. Relation trên time spec cũng kích hoạt kiểm comparison dù operation không phải percent_change.

Mỗi cặp kiểm cùng cột ngày, date_role và tập applies_to. Không lấy primary của M1 ghép với comparison của source/M2 không liên quan. Cho phép hai scope riêng khi chúng được nối rõ bằng operands của phép percent_change/subtract/divide: operand đầu nhận primary, operand sau nhận comparison. Hai khoảng explicit phải gắn role primary/comparison. Một spec có comparison=previous_year/previous_month_matched/previous_equal_days được calculator mở rộng thành cặp.

Các lỗi: MISSING_COMPARISON_WINDOW, MISSING_TEMPORAL_WINDOW, MISSING_COMPARISON_OPERANDS, TEMPORAL_INTENT_CONFLICT, TEMPORAL_INTENT_UNRESOLVED. Calculator có thể bổ sung TEMPORAL_UNRESOLVED hoặc COMPARISON_RELATION_UNRESOLVED.

Nếu thiếu kỳ so sánh, giữ primary đã tính cùng source/measure hữu ích, đánh dấu `completeness_status=incomplete`, trả partial với unresolved cụ thể. Không fail toàn bộ và không tự tính kỳ trước từ raw_expression. Nếu extent unknown thì bỏ khoảng có nguy cơ sai nhưng giữ nhóm contract khác.

`complete` chỉ nói cấu trúc đã đủ theo intent model khai báo và các kiểm tra được áp dụng. Không chứng minh model hiểu đúng câu gốc, date_role đúng nghiệp vụ hoặc source đúng. Nếu model khai sai cả operation lẫn temporal_intent, kiểm này không tự phát hiện bằng hiểu ngôn ngữ. Các constraint giữ semantic_unreviewed.

Tests: [test_temporal_completeness.py](../../../../tests/grounding/test_temporal_completeness.py).
