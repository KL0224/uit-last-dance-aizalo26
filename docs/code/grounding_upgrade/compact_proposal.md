# compact_proposal.py

Source: [compact_proposal.py](../../../../src/datamate/grounding/compact_proposal.py).

Luồng production dùng `WireProposal` cho output Qwen, `Proposal` cho đầu vào verifier và tám nhóm contract Planner như trước. Namespace wire gồm T0..Tn (bảng), C0..Cn (cột), M1..M8 (measure). Mapping sắp theo tên vật lý để ổn định trong cùng index. Model không cần lặp tên bảng dài trong từng column/grain/filter.

`ReferenceMap.context` tạo bản copy evidence có ID ngắn, giữ tên cột nguồn và kiểu dữ liệu. Metric candidates chuyển preferred_table/required_columns thành source/column_refs; trust vẫn là candidate, không chuyển thành binding đã xác minh.

`decoding_schema` tạo JSON Schema Pydantic rồi giới hạn refs theo đúng schema cards đã gửi. Có tối đa 8 measures và 8 time specs. Aggregate enum không chứa percent_change; phép tính đó thuộc operator hoặc operation. Predicate value giới hạn scalar hoặc mảng scalar, không cho object JSON tùy ý. Danh sách conversion refs bắt buộc rỗng khi không gửi unit candidates.

`materialize` chỉ thay reference fields, không thay raw_expression, literal value, tên sản phẩm hay policy text. ID không tồn tại bị từ chối, không fuzzy match hay suy tên bảng. Model không dùng được bare column hoặc tên vật lý trực tiếp ở wire. Sau map, Pydantic kiểm Proposal và neo_verifier kiểm schema/semantics như cũ.

Ví dụ cột `C7` có thể map thành `sales.order_date`; literal sản phẩm có giá trị `C7` vẫn giữ đúng chuỗi `C7`. Debug reference_map cho phép kiểm tra các ID cụ thể của từng business.

Cohort có group_by, measure, operator, threshold và result=count_groups/list_groups để giữ hai cấp tổng hợp. Không đồng nhất số đơn và số khách. Verifier đòi group_by khớp grain của measure tham chiếu.

Giới hạn 8 measures nhằm chặn kiểu lặp dài quan sát trong smoke run; yêu cầu vượt khả năng biểu diễn phải unresolved hoặc fallback. Constrained decoding không tự bảo đảm measure ID duy nhất, đồ thị không chu trình hay binding đúng nghiệp vụ; các bước đó vẫn thuộc verifier.

Kiểm thử: `tests/grounding/test_compact_grounding.py`.

## Wire temporal v4

WireProposal bắt buộc có temporal_intent và time (có thể [] cho none/unknown). Mỗi WireTimeSpec bắt buộc period_extent, comparison, role, applies_to ngoài raw_expression/kind/column. JSON Schema trong sampler cũng giữ các field này required; model không thể bỏ comparison rồi ngầm nhận null.

comparison ở wire là none/previous_equal_days/previous_year/previous_month_matched/unknown. materialize chỉ map none thành null, không suy relation. period_extent full_period/to_as_of/snapshot/unknown được giữ nguyên đến calculator. role primary/comparison/series hỗ trợ hai kỳ explicit và chuỗi nhiều kỳ.

Field mới nằm trong temporal_plan/materialized spec và intent nội bộ; tám nhóm cấp cao Planner vẫn giữ nguyên. Proposal cũ thiếu trường wire required phải bị từ chối; không tự biến output cũ thành output mới.

## Decoding và recovery v6

`time.column` chỉ cho phép DATE/TIMESTAMP columns thực sự gửi trong table cards. Nếu không có cột temporal phù hợp, time.maxItems=0; model phải giữ yêu cầu thời gian trong unresolved. Không cho mã đơn hay giá lẻ làm cột ngày chỉ vì alias tồn tại.

Production parse từng optional item qua proposal_recovery, thay vì để một alias lỗi làm mất cả proposal. Predicate field M1..M8 được giữ nguyên để verifier đối chiếu với measures đã khai báo; không diễn giải nhầm M* thành column khi materialize item độc lập. Strict materialize vẫn từ chối alias/cột trần không hợp lệ.
