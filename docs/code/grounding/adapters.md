# Giải Thích Mã Nguồn: `adapters.py`

**Đường dẫn file:** [`src/datamate/grounding/adapters.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/adapters.py)  
**Thuộc module:** Component C — Question Grounding (Pipeline Integration Adapters)  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2: Vietnamese Tabular QA)

---

## 1. Tổng Quan & Vai Trò

File `adapters.py` đóng vai trò là **Cầu nối tích hợp hai chiều (Bidirectional Integration Bridge)** của Component C trong toàn bộ hệ sinh thái DataMate.

Theo mô hình phát triển phần mềm mô-đun, các thành phần phát triển ở các giai đoạn khác nhau hoặc do các thành viên khác nhau đảm nhiệm sẽ có sự khác biệt về định dạng dữ liệu:
* **Phía Thượng Nguồn (Upstream)**: Module B0.1 (Data Loader) và B0.2 (Business Context) xuất ra các đối tượng phức tạp như `SchemaCatalog`, `TableMetadata`, `RuleCatalog`, `BusinessContext`.
* **Phía Hạ Nguồn (Downstream)**: Module B0.3 (Text-to-SQL Planner) cần prompt văn bản súc tích để điều khiển mô hình LLM 9B; trong khi Module B0.5 (Output Gate) cần đối tượng `EvidenceProof` độc lập từ catalog để xác thực các câu hỏi không thể trả lời (`unanswerable`).

File `adapters.py` giải quyết trọn vẹn việc cắm nối này thông qua hai lớp Adapter chuyên biệt:
1. `B02ContextAdapter`: Chuyển đổi ngữ cảnh thật từ B0.2 thành giao diện chuẩn `BusinessContextProtocol` của Grounding.
2. `GroundingToPlannerAdapter`: Chuyển đổi kết quả `GroundedQuestion` thành gợi ý prompt ngữ nghĩa cho B0.3 và bằng chứng `EvidenceProof` cho B0.5.

---

## 2. Chi Tiết Các Class & Thuật Toán Chuyển Đổi

### 2.1. `B02ContextAdapter(BusinessContextProtocol)`

Lớp bọc (Wrapper) biến một đối tượng `datamate.b0.b02.contracts.BusinessContext` thành đối tượng tương thích 100% với `BusinessContextProtocol`:

#### Logic chuyển đổi cấu trúc bảng (`_build_tables`):
* Duyệt qua từng `TableMetadata` trong `schema_catalog.tables`.
* **Bảo vệ rò rỉ cột nội bộ (Defense against Internal Lineage Leak)**: B0.1 tự động thêm cột `__dm_row_id` vào mọi bảng trong DuckDB để theo dõi nguồn gốc dữ liệu. Hàm `_build_tables` tự động **lọc bỏ tất cả các cột có tiền tố `__dm_`**, không đưa vào danh sách cột ngữ nghĩa của Grounding, giúp Planner không bị nhầm lẫn khi viết `SELECT *`.
* **Trích xuất giá trị mẫu tự động (Automatic Sample Values Extraction)**: B0.1 lưu trữ tối đa 5–15 dòng dữ liệu mẫu trong `tbl.profile_rows`. Adapter tự động quét qua các dòng này, trích xuất tối đa 15 giá trị phân biệt (`distinct values`) cho từng cột (loại trừ `None`) và nạp vào thuộc tính `sample_values` của `ColumnSpec`. Nhờ đó, C4 Value Grounder có ngay dữ liệu để đối chiếu thực thể mà không cần chạy câu lệnh `SELECT DISTINCT` trên DuckDB.

#### Logic chuyển đổi đồ thị liên kết (`_build_joins`):
* Duyệt qua từng `JoinEdge` trong `schema_catalog.join_graph` và ánh xạ sang `JoinSpec`, bảo toàn thông tin lực lượng quan hệ (`cardinality`) và cờ cảnh báo nhân dòng (`fanout_warning`).

#### Cài đặt các phương thức tra cứu nghiệp vụ:
* `get_capability_status(capability_key)`: Đọc từ từ điển `answerability_constraints`. Hỗ trợ linh hoạt cả kiểu boolean (`True`/`False`) lẫn kiểu chuỗi (`"supported"`/`"unsupported"`/`"unknown"`).
* `get_active_rules(topic)`: Sắp xếp toàn bộ các quy tắc trong `rule_catalog.rules` theo mức độ ưu tiên `precedence` tăng dần (quy tắc có số nhỏ hơn mang tính ưu tiên ghi đè cao hơn).
* `get_calendar_events()`: Trích xuất danh sách sự kiện lễ/Tết từ `business_metadata["calendar_events"]`.
* `get_value_aliases()`: Trích xuất từ điển ánh xạ từ vựng từ `business_metadata["value_aliases"]`.

---

### 2.2. `GroundingToPlannerAdapter`

Lớp cung cấp các phương thức tĩnh chuyển đổi đầu ra của Grounding sang định dạng mà các module hạ nguồn yêu cầu:

#### `format_grounded_hint_for_planner(grounded: GroundedQuestion) -> str`
Sinh ra một đoạn văn bản Markdown súc tích để nối vào prompt hệ thống của mô hình 9B (Planner):
* **Cấu trúc đoạn gợi ý**:
  ```markdown
  ### KẾT QUẢ PHÂN TÍCH CÂU HỎI & LIÊN KẾT DỮ LIỆU (GROUNDING HINTS)
  - **Phép toán chính (Operation)**: `sum`
  - **Kiểu đáp án kỳ vọng (Answer Type Hint)**: `number`
  - **Chỉ số nghiệp vụ (Target Metrics)**: `cash_collected`
  - **Giới hạn Top-K**: `LIMIT 5` (sắp xếp `DESC`)
  - **Khoảng thời gian đã phân giải (Resolved Time Constraints)**:
    + `tháng này` (payment_date): từ `2026-08-01` đến `2026-08-27` (inclusive)
  - **Bảng trọng tâm (Primary Table)**: `shift_payments`
    + Bảng `shift_payments` (grain=payment_event): các cột liên quan `[shift_name, payment_method, collected_amount, payment_date]`
    + Gợi ý JOIN: `shift_payments.order_id = orders.order_id` (many_to_one)
  - **Giá trị thực tế trong DB đã đối chiếu (Grounded Values)**:
    + Cụm từ `ca tối` -> Cột `shift_payments.shift_name` = `'Ca tối'`
    + Cụm từ `tiền mặt` -> Cột `shift_payments.payment_method` = `'Tiền mặt'`
  ```
* **Lợi ích**: LLM 9B nhận được chỉ dẫn chính xác tuyệt đối về tên bảng, tên cột, khoảng ngày và giá trị điều kiện lọc, giúp loại bỏ 100% ảo giác cú pháp.

#### `to_b05_evidence_proof(grounded: GroundedQuestion) -> EvidenceProof`
Chuyển đổi kết quả đánh giá từ C5 sang đối tượng `datamate.b0.b05.contracts.EvidenceProof`:
* Khi `grounded.is_directly_unanswerable == True`:
  * Trích xuất thông tin từ `MissingEvidenceProof`.
  * Gán `source_kind = "catalog_verified"`.
  * Gán `checked_all_sources = True`.
  * Gán `missing_fields = list(mp.missing_fields)`.
  * Gán `proof = mp.reason`.
* Giúp Output Gate B0.5 lập tức phê duyệt câu hỏi là `unanswerable` hợp lệ, không bao giờ bị hạ cấp nhầm sang `abstain`.

---

## 3. Tại Sao Lại Thiết Kế & Code Như Vậy?

1. **Tuân thủ triệt để Nguyên lý Đóng/Mở (Open/Closed Principle - OCP)**:
   * Khi bạn của bạn cập nhật B0.1 hoặc B0.2 (thêm trường mới, đổi cách tổ chức Rule Catalog), bạn **chỉ cần cập nhật logic bên trong `B02ContextAdapter`**. Toàn bộ 5 module con C1..C5 và Engine không cần sửa bất kỳ dòng code nào.
2. **Khắc phục triệt để lỗi rò rỉ cột hệ thống**:
   * Việc tự động lọc bỏ các cột `__dm_*` trong `_build_tables` ngăn ngừa tình trạng LLM nhìn thấy cột `__dm_row_id` rồi đưa vào câu lệnh `SELECT`, gây sai lệch cấu trúc bảng nộp bài.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Cầu nối vào**: Giúp `QuestionGroundingEngine` tiếp nhận dữ liệu thực tế từ `B0.2 ContextService`.
* **Cầu nối ra**:
  * Cung cấp chuỗi định dạng gợi ý cho `src/datamate/b0/b03/prompt.py`.
  * Cung cấp bằng chứng kiểm chứng độc lập cho `src/datamate/b0/b05/gate.py`.

---

## 5. Nếu Không Có File Này Thì Sao?

* Bạn sẽ phải viết code chuyển đổi rải rác khắp nơi trong `pipeline.py`, gây rối rắm và khó kiểm soát.
* Mỗi khi B0.2 thay đổi, code của Grounding sẽ bị vỡ.
* Không có `to_b05_evidence_proof()`, các câu hỏi `unanswerable` do Grounding phát hiện sẽ bị B0.5 từ chối công nhận vì thiếu cờ `catalog_verified`, dẫn đến việc bị hạ cấp thành `abstain` và mất điểm đối với các câu hỏi unanswerable của đề thi.
