# Giải Thích Mã Nguồn: `adapters.py`
**Đường dẫn file:** `src/datamate/b05/adapters.py`  
**Thuộc module:** B0.5 Basic Output Gate  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

File `adapters.py` đóng vai trò là **Lớp bảo vệ cửa ngõ (Input Guard & Adapter Layer)** của B0.5. 

Nhiệm vụ chính: Tiếp nhận dữ liệu thô (raw JSON dictionary) từ Orchestrator hoặc từ các module khác (B0.3, B0.4), sau đó:
1. Thẩm định tính hợp lệ của từng trường dữ liệu.
2. Ép kiểu và chuẩn hóa thành đối tượng `GateRequest` an toàn.
3. Chặn đứng các dữ liệu rác, sai quy cách hợp đồng ngay từ vòng gửi xe bằng `ContractError`.

---

## 2. Chi Tiết Các Hàm

### 2.1. `_validate_iso_date(date_str: str) -> str`
* **Mục đích**: Kiểm tra ngày tham chiếu `as_of_date` có hợp lệ theo chuẩn ISO và dương lịch hay không.
* **Logic xử lý**:
  * Kiểm tra kiểu chuỗi và định dạng regex `^\d{4}-\d{2}-\d{2}$`.
  * Dùng `datetime.date.fromisoformat(s)` để kiểm tra ngày thực tế trên lịch.
  * Nếu gặp ngày ảo như `2026-02-30` (tháng 2 không có ngày 30), hàm lập tức ném ra `ContractError` thay vì đoán bừa ngày khác.
* **Tại sao code như vậy?** Trong bài toán Track 2, nhiều câu hỏi tính toán doanh thu/đơn hàng "tính đến ngày X". Nếu ngày `as_of_date` bị sai lệch, toàn bộ logic lọc SQL sẽ sai theo.

---

### 2.2. `adapt_generation(raw: Optional[Dict[str, Any]]) -> Optional[GenerationResult]`
* **Mục đích**: Chuẩn hóa dữ liệu sinh ra từ module Text-to-SQL (B0.3).
* **Logic xử lý**:
  * Kiểm tra `answer_type`: Bắt buộc phải nằm trong 9 kiểu hợp lệ của `AnswerType`. Nếu nhận được kiểu lạ (ví dụ `"unknown"` hay `"integer"`), lập tức raise `ContractError`.
  * Bóc tách `answer_semantics`: Trích xuất `numeric_kind`, `percent_unit`, `list_ordered`, `empty_set_policy`.
  * Trả về dataclass `GenerationResult`.

---

### 2.3. `adapt_execution(raw: Optional[Dict[str, Any]]) -> ExecutionResult`
* **Mục đích**: Chuẩn hóa kết quả thực thi SQL từ module DuckDB Executor (B0.4).
* **Logic xử lý**:
  * Kiểm tra `status`: Bắt buộc là `success`, `error`, hoặc `not_executed`.
  * Kiểm tra ma trận: `rows` phải là list các dòng; `columns` phải là list tên cột.
  * Chuẩn hóa chi tiết lỗi: Nếu có `error` (dạng dict hoặc string), đóng gói thành `ExecutionErrorDetail(type, message, code)`.
  * Lưu giữ cờ `truncated`: Đánh dấu kết quả có bị cắt ngắn do giới hạn preview hay không.

---

### 2.4. `adapt_evidence(raw: Optional[Dict[str, Any]]) -> EvidenceProof`
* **Mục đích**: Chuẩn hóa thông tin bằng chứng kiểm tra catalog để phục vụ việc xác định câu hỏi không thể trả lời (`unanswerable`).
* **Logic xử lý**:
  * Đọc `capability_status`, `source_kind`, `checked_all_sources`, `missing_fields`, `proof`.
  * Mặc định `source_kind = "unverified"` nếu không có bằng chứng, ngăn chặn việc LLM tự bịa lý do thiếu dữ liệu.

---

### 2.5. `adapt_gate_request(raw: Dict[str, Any]) -> GateRequest`
* **Mục đích**: Hàm điều phối chính lắp ghép toàn bộ các thành phần trên thành một `GateRequest` hoàn chỉnh.
* **Logic xử lý**:
  * Kiểm tra `contract_version`: Phải là `"b05.v1"`.
  * Kiểm tra `question.id`: Không được rỗng.
  * Kiểm tra `attempt`: Chỉ chấp nhận giá trị nguyên `0` (lần đầu) hoặc `1` (lần sửa).
  * Gọi các hàm adapter con: `adapt_generation`, `adapt_execution`, `adapt_evidence`.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Nguyên tắc "Fail-Fast" (Thất bại sớm)**:
   * Nếu dữ liệu đầu vào bị sai cấu trúc (ví dụ thiếu ID, sai định dạng ngày, status lạ), việc phát hiện và ném `ContractError` ngay tại adapter giúp hệ thống lập tức chuyển thành câu trả lời `abstain` an toàn, tránh để lỗi lan truyền sâu vào các tầng tính toán bên trong gây crash chương trình.
2. **Không sửa đổi dữ liệu một cách mù quáng (Defensive Programming)**:
   * Nếu ngày `as_of_date` sai, adapter tuyệt đối không tự sửa thành ngày hiện tại của máy tính (`datetime.now()`) vì làm vậy sẽ gây sai lệch nghiêm trọng ngữ cảnh câu hỏi của đề thi.
3. **Chịu lỗi cho B0.3 và B0.4**:
   * Khi các thành viên khác viết B0.3 hoặc B0.4 trả về dictionary có thể thiếu một vài trường tùy chọn, adapter gán giá trị mặc định an toàn (`rows=[]`, `warnings=[]`) để code không bị dính `KeyError`.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các File Khác

* **Đầu vào cho `gate.py` và `cli.py`**: Bất kỳ raw JSON hay dòng dữ liệu nào từ file test đều phải đi qua `adapt_gate_request()` trước khi đưa vào hàm `evaluate_gate()`.
* **Bảo vệ `validators.py`**: Giúp `validators.py` luôn an tâm rằng dữ liệu bên trong `GateRequest` đã có cấu trúc đúng chuẩn, không cần phải lặp lại các bước kiểm tra `isinstance(rows, list)` quá nhiều lần.

---

## 5. Nếu Không Có File Này Thì Sao?

* B0.5 sẽ nhận trực tiếp raw dictionary từ bên ngoài. Chỉ cần B0.3 đổi tên trường từ `"sql"` sang `"query"`, hoặc B0.4 trả về `rows: null` thay vì `[]`, toàn bộ hệ thống Gate sẽ bị crash với hàng loạt lỗi `KeyError` và `TypeError` trên server GPU.

