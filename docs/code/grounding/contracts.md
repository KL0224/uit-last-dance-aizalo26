# Giải Thích Mã Nguồn: `contracts.py`

**Đường dẫn file:** [`src/datamate/grounding/contracts.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/contracts.py)  
**Thuộc module:** Component C — Question Grounding (Core Contracts)  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2: Vietnamese Tabular QA)

---

## 1. Tổng Quan & Vai Trò

File `contracts.py` là **Hợp đồng dữ liệu trung tâm (Single Source of Truth for Data Contracts)** của toàn bộ module Question Grounding (Component C). 

Trong kiến trúc tổng thể của DataMate, Component C đóng vai trò cầu nối ngữ nghĩa: tiếp nhận câu hỏi tự nhiên tiếng Việt từ người dùng kèm ngày tham chiếu `as_of_date`, phân tích thành các cấu trúc trừu tượng và chuyển giao kết quả đã tinh gọn (`GroundedQuestion`) cho Agent Planner (Component D) và Decision Gate (Component G / B0.5).

File `contracts.py` có nhiệm vụ:
1. Định nghĩa chuẩn hóa các phép toán phân tích (`OperationKind`), gợi ý kiểu đáp án (`AnswerTypeHint`), trạng thái độ phủ dữ liệu (`CoverageStatus`) và vai trò ngữ nghĩa của cột ngày (`DateRole`).
2. Thiết lập các cấu trúc dữ liệu bất biến (`@dataclass(frozen=True)`) đại diện cho từng bước xử lý trung gian: từ câu hỏi đầu vào (`QuestionRequest`), ý định (`QuestionIntent`), ràng buộc thời gian (`ResolvedTimeRange`), lược đồ chọn lọc (`SelectedSchema`), giá trị đối chiếu (`MatchedValue`), đến chứng minh thiếu bằng chứng (`MissingEvidenceProof`).
3. Cung cấp đối tượng bàn giao tối cao `GroundedQuestion` đóng gói trọn vẹn tri thức ngữ nghĩa trước khi bước vào khâu sinh câu lệnh truy vấn SQL.

---

## 2. Chi Tiết Các Class, Enum & Thuộc Tính

### 2.1. Các Enum Định Danh (System Enumerations)

#### `OperationKind(str, Enum)`
Định nghĩa 13 phép toán giải tích chủ đạo của bài toán Vietnamese Tabular QA:
* `SUM`: Tính tổng giá trị (ví dụ: *"Tổng doanh thu..."*, *"Ca tối thu được bao nhiêu tiền mặt"*).
* `COUNT`: Đếm số dòng / sự kiện thông thường (ví dụ: *"Có bao nhiêu hóa đơn..."*).
* `COUNT_DISTINCT`: Đếm số lượng thực thể phân biệt (ví dụ: *"Bao nhiêu khách hàng mua hàng..."*, *"Bao nhiêu mặt hàng khác nhau..."*).
* `AVG`: Tính giá trị trung bình (ví dụ: *"Doanh thu trung bình mỗi ngày..."*, *"Giá bán bình quân..."*).
* `ARGMAX` / `ARGMIN`: Tìm thực thể có giá trị lớn nhất hoặc nhỏ nhất (ví dụ: *"Khách hàng nào mua nhiều tiền nhất"*, *"Ngày nào có doanh thu thấp nhất"*). Khác với `TOP_K`, kết quả của `ARGMAX`/`ARGMIN` là một giá trị đơn lẻ (`scalar`), có kiểu là `string` hoặc `date`.
* `TOP_K`: Xếp hạng và lấy danh sách $K$ thực thể đứng đầu/cuối (ví dụ: *"Năm sản phẩm được ưa chuộng nhất"*). Kết quả trả về là một danh sách (`list`).
* `PERCENT_CHANGE`: Tính tỷ lệ tăng trưởng phần trăm giữa 2 kỳ theo công thức $\frac{V_2 - V_1}{V_1} \times 100$ (ví dụ: *"Tăng hay giảm bao nhiêu phần trăm so với tháng trước"*).
* `RATIO`: Tính tỷ trọng đóng góp $\frac{V_{\text{part}}}{V_{\text{total}}} \times 100$ (ví dụ: *"Chiếm tỷ lệ bao nhiêu..."*).
* `COMPARISON`: So sánh độ chênh lệch tuyệt đối hoặc nhị phân giữa các kỳ/nhóm.
* `LOOKUP`: Tra cứu một thuộc tính cụ thể của thực thể (ví dụ: *"Trạng thái đơn hàng DH01 là gì"*).
* `EXISTENCE`: Kiểm tra sự tồn tại nhị phân Có/Không (ví dụ: *"Tháng này có đơn nào bị hủy không"* $\rightarrow$ `boolean`).
* `TABLE_REPORT`: Yêu cầu xuất báo cáo bảng tổng hợp đa chiều (`table`).

#### `AnswerTypeHint(str, Enum)`
Định nghĩa 9 kiểu đầu ra chính thức của cuộc thi:
`NUMBER`, `PERCENT`, `STRING`, `DATE`, `BOOLEAN`, `LIST`, `TABLE`, `UNANSWERABLE`, `ABSTAIN`.  
Việc định hướng trước kiểu đáp án ngay từ Grounding giúp Planner và Executor không bị nhầm lẫn giữa `scalar` (1 ô) và `list` (1 cột nhiều dòng).

#### `CoverageStatus(str, Enum)`
Trạng thái bằng chứng do C5 Answerability Precheck đánh giá:
* `SUPPORTED`: Doanh nghiệp có đầy đủ bảng, cột và độ phủ thời gian.
* `UNSUPPORTED`: Đã kiểm tra toàn bộ catalog và xác nhận thiếu thành phần bắt buộc.
* `UNKNOWN`: Thiếu dữ liệu trực tiếp nhưng có thể suy luận gián tiếp; cần Planner thử giải kèm cờ rủi ro.

#### `DateRole(str, Enum)`
Xác định ngữ nghĩa nghiệp vụ của cột thời gian:
* `ORDER_DATE`: Ngày tạo/đặt đơn hàng.
* `PAYMENT_DATE`: Ngày thực tế thu tiền/thanh toán (rất quan trọng trong các câu hỏi thu tiền theo ca).
* `STOCK_EVENT_DATE`: Ngày xuất/nhập kho hàng.
* `EXPIRY_DATE`: Hạn sử dụng của sản phẩm.
* `GENERIC_DATE`: Ngày thông thường khác.

---

### 2.2. Các Dataclass Truyền Dữ Liệu (Immutable DTOs)

#### `QuestionRequest`
Biểu diễn yêu cầu câu hỏi đầu vào:
* `question_id: str`: Định danh duy nhất của câu hỏi.
* `business_id: str`: Mã doanh nghiệp đang xét.
* `question: str`: Nội dung câu hỏi nguyên bản tiếng Việt.
* `as_of_date: str`: Ngày tham chiếu mốc thời gian (chuẩn ISO `YYYY-MM-DD`).
* **Logic phòng thủ (`__post_init__`)**: Tự động `.strip()` khoảng trắng thừa, kiểm tra chuỗi không được rỗng, và gọi `date.fromisoformat(as_of_date)` để thẩm định ngày thực tế trên lịch. Ném `ValueError` ngay lập tức nếu ngày bị lỗi (ví dụ `2026-02-30`).

#### `FilterCondition`
Biểu diễn một điều kiện lọc trích xuất từ câu hỏi:
* `field_hint: str`: Gợi ý tên trường (ví dụ: `"shift_name"`, `"payment_method"`).
* `operator: str`: Toán tử điều kiện (`"="`, `">="`, `"<="`, `"LIKE"`).
* `raw_value: Any`: Giá trị thô trong câu hỏi (ví dụ: `"ca tối"`, `3`).
* `grounded_column: str | None`: Tên cột thực tế trong DB sau khi chạy C4 (ví dụ: `"shift_payments.shift_name"`).
* `grounded_value: Any | None`: Giá trị thực tế trong DB sau khi chạy C4 (ví dụ: `"Ca tối"`).
* `is_having: bool`: Đánh dấu điều kiện thuộc mệnh đề `HAVING` của SQL (ví dụ: `"ít nhất 3 đơn"` $\rightarrow$ `is_having=True`).

#### `QuestionIntent` (Đầu ra của C1)
Biểu diễn ý định phân tích của câu hỏi:
* `operation: OperationKind`: Phép toán chủ đạo.
* `target_metrics: tuple[str, ...]`: Các chỉ số cần tính (ví dụ: `("cash_collected",)`).
* `entities: tuple[str, ...]`: Các thực thể được nhắc đến trong câu hỏi.
* `filters: tuple[FilterCondition, ...]`: Bộ điều kiện lọc.
* `group_by: tuple[str, ...]`: Chiều gom nhóm (`"customer"`, `"product"`, `"date"`, `"shift"`).
* `top_k: int | None`: Số lượng thực thể cần lấy (nếu có).
* `sort_order: str`: Chiều sắp xếp (`"desc"` hoặc `"asc"`).
* `tie_break_rule: str`: Quy tắc xử lý bằng điểm (mặc định `"entity_asc"` để đảm bảo tính tất định).
* `answer_type_hint: AnswerTypeHint`: Kiểu dữ liệu đầu ra kỳ vọng.
* `confidence: float`: Điểm tự tin của bộ phân tích (0.0 đến 1.0).
* `used_llm_fallback: bool`: Cờ đánh dấu có phải dùng đến mô hình 3B LLM hay không.
* `fallback_reasons: tuple[str, ...]`: Các bằng chứng khiến fast-path chuyển sang LLM hoặc lý do fallback thất bại.
* `normalized_question: str | None`: Câu hỏi đầy đủ do LLM chuẩn hóa; optional để không phá consumer cũ và chỉ được engine dùng cho các bước C2–C5.

#### `ResolvedTimeRange` (Đầu ra của C2)
Khoảng thời gian đã được phân giải xác định:
* `raw_expression: str`: Biểu thức thời gian gốc (ví dụ: `"tháng này"`).
* `start_date: str`: Ngày bắt đầu chuẩn ISO (ví dụ: `"2026-08-01"`).
* `end_date: str`: Ngày kết thúc chuẩn ISO (ví dụ: `"2026-08-27"`).
* `date_role: DateRole`: Vai trò cột ngày cần lọc.
* `inclusive: bool`: Đánh dấu khoảng ngày đóng `[start, end]`.
* `comparison_start_date: str | None` & `comparison_end_date: str | None`: Khoảng thời gian kỳ đối chiếu (cho câu hỏi tăng trưởng cùng kỳ).
* `interpretation: str`: Diễn giải ngữ nghĩa dễ đọc phục vụ log kiểm toán.
* **Logic phòng thủ (`__post_init__`)**: Xác thực bất biến `start_date <= end_date` và `comparison_start_date <= comparison_end_date`.

#### `SchemaCandidate`, `CandidateJoinPath` & `SelectedSchema` (Đầu ra của C3)
* `SchemaCandidate`: Bảng ứng viên gồm `table_name`, `relevant_columns` (danh sách cột đã chọn lọc), `grain` (hạt dữ liệu), `score` (điểm liên quan), `rationale` (lý do chọn).
* `CandidateJoinPath`: Đường nối giữa 2 bảng gồm `left_table`, `left_column`, `right_table`, `right_column`, `cardinality`, `fanout_warning`, `confidence`.
* `SelectedSchema`: Gồm `primary_table` (bảng Fact trọng tâm), `tables`, `join_paths`, cờ `fanout_warning` và danh sách cảnh báo `warnings`.

#### `MatchedValue` (Đầu ra của C4)
Liên kết cụm từ với dữ liệu thực tế:
* `raw_text`: Cụm từ thô trong câu hỏi.
* `table_name` & `column_name`: Vị trí lưu trữ trong DB.
* `matched_db_value`: Giá trị thực tế đã chuẩn hóa.
* `match_type`: Phương thức khớp (`"exact_alias"`, `"exact_sample"`, `"unaccented_sample"`, `"substring_sample"`).
* `confidence`: Độ tin cậy của phép so khớp.

#### `MissingEvidenceProof` (Đầu ra của C5)
Bằng chứng chứng minh thiếu dữ liệu:
* `capability_key`: Năng lực nghiệp vụ bị thiếu (ví dụ: `"customers"`, `"cost"`).
* `missing_fields`: Danh sách trường bị thiếu.
* `checked_tables`: Danh sách toàn bộ các bảng trong doanh nghiệp đã được rà soát.
* `checked_all_sources: bool`: Khẳng định đã kiểm tra 100% nguồn dữ liệu.
* `reason`: Giải thích chi tiết bằng ngôn ngữ tự nhiên.

#### `GroundedQuestion` (Đầu ra tối cao của Component C)
Gói dữ liệu hoàn chỉnh bàn giao cho các tầng sau:
* Chứa đầy đủ: `question_id`, `business_id`, `question`, `as_of_date`, `intent`, `resolved_time_ranges`, `selected_schema`, `matched_values`, `answer_type_hint`, `evidence_requirements`, `coverage_status`, `missing_evidence_proof`, `applicable_rules`, `risk_flags`.
* **Thuộc tính `@property def is_directly_unanswerable(self) -> bool`**:
  * Trả về `True` khi và chỉ khi: `coverage_status == CoverageStatus.UNSUPPORTED` VÀ `missing_evidence_proof is not None` VÀ `missing_evidence_proof.checked_all_sources == True`.
* **Phương thức `to_dict() -> dict[str, Any]`**:
  * Chuyển đổi toàn bộ cấu trúc phân cấp phức tạp thành dictionary chuẩn JSON thuần túy, an toàn cho việc serialize và ghi log `audit.jsonl`.

---

## 3. Tại Sao Lại Thiết Kế & Code Như Vậy?

1. **Bất biến tuyệt đối (`frozen=True`) và cấu trúc dữ liệu `tuple`**:
   * Khi dữ liệu đi qua nhiều module con (C1 $\rightarrow$ C2 $\rightarrow$ C3 $\rightarrow$ C4 $\rightarrow$ C5), việc dùng `tuple` và `frozen=True` ngăn chặn hoàn toàn lỗi lập trình do vô tình sửa đổi dữ liệu (side-effects). Điều này bảo đảm tính tái lập (Determinism) đạt 100%.
2. **Kế thừa `(str, Enum)` cho toàn bộ Enum**:
   * Giúp việc so sánh với chuỗi string literal hoạt động trực tiếp (ví dụ: `if intent.operation == "sum"`), đồng thời khi `asdict()` xuất ra JSON sẽ tự động là string thuần, không bị lỗi `TypeError: Object of type OperationKind is not JSON serializable`.
3. **Phòng thủ ngay từ biên dữ liệu (`__post_init__`)**:
   * Phát hiện ngày ảo (`2026-02-30`), định dạng sai hoặc khoảng ngày bị đảo ngược (`start > end`) ngay từ lúc tạo object, giúp hệ thống thất bại sớm (Fail-Fast) trước khi gửi prompt xuống LLM hay chạy SQL.

---

## 4. Ý Nghĩa & Ảnh Hưởng Liên Đới Đến Các Module Khác

* **Cung cấp cho Agent Planner (B0.3 / Component D)**: Planner không còn phải đọc hàng chục bảng thô. Nó nhận `SelectedSchema` chỉ gồm 1–3 bảng trọng tâm và các cột liên quan, nhận `ResolvedTimeRange` với ngày cụ thể, và nhận `MatchedValue` để viết mệnh đề `WHERE` chính xác.
* **Cung cấp cho Output Gate (B0.5 / Component G)**: Khi `is_directly_unanswerable == True`, Gate nhận được `MissingEvidenceProof` độc lập từ catalog để xuất thẳng kết quả `unanswerable` hợp lệ, bỏ qua 100% thời gian chạy của Planner và Executor.

---

## 5. Nếu Không Có File Này Thì Sao?

* Nếu không có các contract chặt chẽ, các module con sẽ trao đổi dữ liệu qua dictionary tùy ý (`dict[str, Any]`). Chỉ cần B0.3 gõ `"metrics"` thay vì `"target_metrics"`, hoặc C4 gõ nhầm `"col"` thay vì `"column_name"`, chương trình sẽ bị `KeyError` và crash giữa chừng khi đang chạy đánh giá hàng ngàn câu hỏi.
* Không có contract chuẩn, việc kiểm thử độc lập (Unit Test) cho từng module C1, C2, C3, C4, C5 sẽ trở nên bất khả thi.
