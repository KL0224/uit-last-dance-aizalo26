# context_budget.py

Source: [context_budget.py](../../../../src/datamate/grounding/context_budget.py).

`rank_evidence` dùng tên cột, header gốc, kiểu dữ liệu và từ trong câu hỏi để xếp hạng capability: thời gian, tiền hàng, thu tiền, khóa đơn/khách, số lượng, giá vốn, tồn kho. Đây chỉ là retrieval; không quyết định đáp án hoặc tin registry preferred_table như binding đúng.

Bảo vệ bảng đứng đầu và nguồn bổ sung cho các vai trò bảng đầu chưa có. Với câu có thời gian, các bảng có tên cùng family và layout giống nhau cũng được giữ để tránh mất phân mảnh năm. Không tự tạo UNION. Trong các nguồn được bảo vệ, giữ cột ngày/giờ, khóa, trạng thái/ghi chú, cột khớp vai trò/câu hỏi và cột số khi câu hỏi cần số đo. Capability matching là heuristic; chưa chứng minh source coverage đầy đủ hoặc routing theo min/max ngày.

`fit_context` nhận token counter thật của backend. Khi vượt budget: bỏ JOIN stats, extra policies, business policies ngoài hai dòng ưu tiên, unit/metric candidates, directory đầy đủ; sau đó bỏ nguồn phụ và cột không được bảo vệ. Giữ core policies. Nếu ngay cả schema/policies được bảo vệ vẫn không vừa, dừng trước inference với lỗi rõ; không âm thầm bỏ bằng chứng bắt buộc. Không thay đổi bundle hoặc input evidence.

`diagnostics.context_budget` ghi initial_tokens, trimmed, protected_tables/columns, removed_tables/columns và uncovered_retrieval_roles. Context bị cắt có cảnh báo omission không chứng minh dữ liệu không tồn tại. Token budget không dùng ước lượng ký tự trong production; counter giả chỉ phục vụ kiểm thử.

Kiểm thử: [test_context_budget.py](../../../../tests/grounding/test_context_budget.py), bao gồm catalog lấn nguồn bán hàng, nguồn bổ sung, phân mảnh năm, cột số lạ, budget bất khả thi và DATE-only decoding.
