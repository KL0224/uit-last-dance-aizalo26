# Giải Thích Mã Nguồn: `contracts.py`
**Đường dẫn file:** `src/datamate/b05/contracts.py`  
**Thuộc module:** B0.5 Basic Output Gate  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

File `contracts.py` đóng vai trò là **Hợp đồng dữ liệu trung tâm (Data Contracts & Type Definitions)** của toàn bộ module B0.5. Nó định nghĩa toàn bộ cấu trúc dữ liệu đầu vào, trạng thái trung gian, cấu trúc yêu cầu sửa lỗi và dữ liệu đầu ra nộp bài.

Mọi module khác trong B0.5 (`adapters.py`, `validators.py`, `formatter.py`, `retry.py`, `answerability.py`, `gate.py`, `writer.py`, `cli.py`) đều phụ thuộc trực tiếp vào file này.

---

## 2. Chi Tiết Các Class & Hàm

### 2.1. Các Enum Định Danh (Enumerations)

* **`AnswerType(str, Enum)`**:
  * Định nghĩa đúng 9 loại câu trả lời chính thức của cuộc thi:
    `NUMBER`, `PERCENT`, `STRING`, `DATE`, `BOOLEAN`, `LIST`, `TABLE`, `UNANSWERABLE`, `ABSTAIN`.
  * *Tại sao lại kế thừa `(str, Enum)`?* Giúp việc so sánh trực tiếp với chuỗi (string literal) hoạt động mượt mà (ví dụ: `res.type == "number"`), đồng thời tự động tuần tự hóa sang chuỗi khi dump ra JSON mà không bị lỗi serialize.
* **`NumericKind(str, Enum)`**:
  * Phân loại mục đích của số: `count` (số đếm nguyên), `money_vnd` (tiền đồng VND), `average_money_vnd` (AOV tiền VND), `average_nonmoney` (trung bình phi tiền tệ), `quantity` (số lượng), `generic` (số thông thường).
  * Giúp Formatter biết chính xác quy tắc làm tròn (làm tròn nguyên đơn vị hay lấy 2 chữ số thập phân).
* **`PercentUnit(str, Enum)`**:
  * Xác định đơn vị tỷ lệ: `percent_points` (điểm phần trăm, ví dụ `-12.45`) hoặc `fraction` (tỷ lệ thập phân, ví dụ `0.125`).
* **`ExecutionStatus(str, Enum)`**:
  * Trạng thái thực thi từ B0.4: `SUCCESS`, `ERROR`, `NOT_EXECUTED`.
* **`GateAction(str, Enum)`**:
  * Hành động chỉ đạo của Gate gửi về cho Orchestrator:
    * `FINAL`: Đã có kết quả cuối cùng (Answer, Unanswerable, hoặc Abstain), ghi nhận nộp bài.
    * `RETRY`: Yêu cầu gửi lại cho B0.3 sinh lại SQL để sửa lỗi.
* **`Decision(str, Enum)`**:
  * Quyết định nội bộ: `answer`, `unanswerable`, `abstain`, `retry`.

---

### 2.2. Các Dataclass Truyền Dữ Liệu (DTOs)

* **`QuestionMeta`**:
  * Chứa thông tin câu hỏi: `id`, `business_id`, `question`, `as_of_date`.
* **`AnswerSemantics`**:
  * Siêu dữ liệu ngữ nghĩa do B0.3 hoặc Loader cung cấp: `numeric_kind`, `percent_unit`, `list_ordered`, `time_role`, `empty_set_policy`.
* **`GenerationResult`**:
  * Đóng gói toàn bộ kết quả sinh mã từ B0.3: `answer_type`, `sql`, `tables_used`, `assumptions`, `answer_semantics`.
* **`ExecutionErrorDetail` & `ExecutionResult`**:
  * Đóng gói kết quả chạy SQL từ B0.4 trên DuckDB: `status`, `columns`, `rows`, `row_count`, `truncated`, `elapsed_ms`, `error`, `warnings`.
* **`EvidenceProof`**:
  * Bằng chứng kiểm tra độc lập từ catalog dữ liệu: `capability_status`, `coverage_status`, `checked_all_sources`, `missing_fields`, `source_kind`, `proof`.
* **`GateRequest`**:
  * Đối tượng đầu vào duy nhất và tối cao của B0.5, gom tất cả các thành phần trên kèm `attempt` (lượt thử: 0 hoặc 1) và `trace`.
* **`RepairRequest`**:
  * Gói thông tin phản hồi khi `GateAction == RETRY`, chỉ dẫn cho B0.3 biết SQL đã sai ở đâu (`error_code`, `error_type`, `error_message`, `schema_hint`) để sinh lại câu lệnh chuẩn xác mà không đổi nghĩa câu hỏi.
* **`ValidationResult`**:
  * Kết quả kiểm tra hình học/kiểu dữ liệu từ `validators.py`: `passed`, `error_code`, `details`, `normalized_candidate`, `warnings`.
* **`FinalAnswer`**:
  * Chứa câu trả lời cuối cùng: `id`, `type`, `answer`, `reason`.
  * **Hàm `to_submission_dict()`**:
    * Chuyển đổi đối tượng sang định dạng dictionary chuẩn JSON nộp bài cho BTC.
    * **Đặc biệt xử lý nghiêm ngặt**:
      * Nếu `type == "abstain"`: Chỉ xuất `{"id": id, "type": "abstain"}`. Tuyệt đối **không có** trường `"answer"`, kể cả `null`.
      * Nếu `type == "unanswerable"`: Chỉ xuất `{"id": id, "type": "unanswerable"}` kèm `"reason"` (nếu có), không có trường `"answer"`.
      * Các type khác: Xuất `{"id": id, "type": type, "answer": answer}`.
* **`GateOutcome`**:
  * Kết quả trả về của hàm `evaluate_gate()` gồm: `action`, `question_id`, `decision`, `final_answer`, `reason_code`, `validation`, `retry_count`, `repair_request`.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Sử dụng `@dataclass` thay vì `dict` tự do**:
   * Nếu dùng dictionary `req["execution"]["rows"]`, chỉ cần gõ sai 1 chữ cái là chương trình crash lúc đang chạy máy chủ GPU. Dataclass cung cấp autocompletion, type safety và kiểm tra lỗi ngay khi viết code.
2. **Quy định bất biến (Invariants) cho Submission BTC**:
   * Ban tổ chức chấm điểm tự động bằng code JSON parser. Nếu câu hỏi `abstain` mà bạn xuất `{"id": "q1", "type": "abstain", "answer": null}`, hệ thống chấm thi có thể báo lỗi schema fail. Hàm `to_submission_dict()` đóng gói logic này một nơi duy nhất để bảo đảm 100% tuân thủ.
3. **Phân tách `GateAction` và `Decision`**:
   * `action` chỉ có 2 giá trị (`FINAL` hoặc `RETRY`) giúp Orchestrator điều hướng luồng đơn giản: hoặc dừng lại ghi bài, hoặc quay lại B0.3.
   * `decision` (`answer`, `unanswerable`, `abstain`) giúp hệ thống logging và thống kê Local CV phân tích sâu tỷ lệ thành công của từng nhánh.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các File Khác

* **Cung cấp Schema cho `adapters.py`**: File adapter chuyển đổi JSON thô từ bên ngoài thành các instance của `GateRequest`.
* **Quy định đầu vào/đầu ra cho `gate.py`**: Hàm `evaluate_gate(request: GateRequest) -> GateOutcome`.
* **Chỉ dẫn cho `writer.py`**: Writer chỉ gọi `outcome.final_answer.to_submission_dict()` để lấy JSON chuẩn ghi vào `submission.jsonl`.
* **Cung cấp định dạng cho `retry.py`**: Tạo ra `RepairRequest` đồng nhất để gửi lại cho B0.3.

---

## 5. Nếu Không Có File Này Thì Sao?

* **Gãy toàn bộ hệ thống Type Hints**: Không có hợp đồng chung giữa các thành viên và các module.
* **Xung đột định dạng với BTC**: Mỗi người code một kiểu (người thì viết `"ans"`, người viết `"answer"`, người để `answer: null` khi abstain) dẫn đến file `submission.jsonl` bị từ chối hợp lệ khi nộp bài.
* **Khó debug**: Không thể tái hiện trạng thái lỗi có cấu trúc khi truy vết sự cố trên GPU server.

