# Giải Thích Mã Nguồn: `gate.py`
**Đường dẫn file:** `src/datamate/b05/gate.py`  
**Thuộc module:** B0.5 Basic Output Gate  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

File `gate.py` là **Trái tim và Nhạc trưởng điều phối (Main Evaluation Engine)** của toàn bộ module B0.5.

Hàm `evaluate_gate(request: GateRequest) -> GateOutcome` tại file này chính là điểm truy cập công khai (Public API) mà Orchestrator toàn hệ thống sẽ gọi đến. Nó kết nối tuần tự tất cả các module con (`answerability`, `validators`, `retry`, `formatter`) thành một cỗ máy đưa ra quyết định tối hậu:
- **`action == "RETRY"`**: Yêu cầu Orchestrator quay lại B0.3 để sửa SQL.
- **`action == "FINAL"`**: Đã có kết quả chốt nộp bài (`answer`, `unanswerable`, hoặc `abstain`).

---

## 2. Chi Tiết Luồng Xử Lý Của Hàm `evaluate_gate`

```text
               ┌───────────────────────────────┐
               │    GateRequest (attempt 0/1)  │
               └───────────────┬───────────────┘
                               │
            (1) Kiểm tra Unanswerable có bằng chứng?
                    ├── [CÓ] ──► FINAL (unanswerable)
                    └── [KHÔNG]
                               │
            (2) LLM tự nhận unanswerable nhưng thiếu bằng chứng?
                    ├── [CÓ] ──► FINAL (abstain, MISSING_EVIDENCE)
                    └── [KHÔNG]
                               │
            (3) Validate Execution & Ma trận Shape
                    ├── [FAIL] ──► Phân loại lỗi & Hỏi Bounded Retry
                    │                   ├── [Được retry (attempt=0)] ──► RETRY (repair_request)
                    │                   └── [Hết lượt (attempt=1)]   ──► FINAL (abstain)
                    └── [PASS]
                               │
            (4) Format Answer sang 1 trong 9 Types
                    ├── [Lỗi Format] ──► Thử Bounded Retry hoặc FINAL (abstain)
                    └── [Thành công] ──► FINAL (answer)
```

### Các bước cụ thể:

1. **Bước 1: Ưu tiên thẩm định `unanswerable` có bằng chứng**:
   * Gọi `evaluate_answerability(request)`.
   * Nếu có bằng chứng xác thực (`catalog_verified`): Lập tức trả về `GateOutcome(action="FINAL", decision="unanswerable")`.
   * *Ý nghĩa*: Tiết kiệm thời gian, nếu dữ liệu đã chắc chắn thiếu thì không cần kiểm tra kết quả SQL nữa.
2. **Bước 2: Xử lý trường hợp LLM tự nhận `unanswerable` mà không có bằng chứng**:
   * Nếu `generation.answer_type == "unanswerable"` nhưng Bước 1 không xác nhận:
   * Chuyển thành `GateOutcome(action="FINAL", decision="abstain", reason_code="MISSING_EVIDENCE")`.
   * *Ý nghĩa*: Bảo vệ đội thi không bị trừ 1 điểm PA.
3. **Bước 3: Kiểm tra tính hợp lệ của câu truy vấn (`validate_execution`)**:
   * Gọi `validate_execution(request)`.
   * Nếu không đạt (`val_res.passed == False`):
     * Phân loại lỗi bằng `classify_error()`.
     * Kiểm tra khả năng sửa lỗi bằng `decide_retry()`.
     * Nếu còn lượt (`attempt == 0`) và lỗi sửa được ➔ Trả về `GateOutcome(action="RETRY", repair_request=repair)`.
     * Nếu hết lượt (`attempt == 1`) hoặc lỗi nghiêm trọng ➔ Trả về `GateOutcome(action="FINAL", decision="abstain")`.
4. **Bước 4: Định dạng kết quả (`format_answer`)**:
   * Nếu dữ liệu vượt qua bước 3, chuyển giá trị ứng viên vào `format_answer()`.
   * Bắt ngoại lệ `FormattingError`: Nếu format thất bại (ví dụ số float bị lỗi), kiểm tra xem có thể retry không; nếu không thể, chuyển sang `abstain`.
   * Nếu format thành công: Đóng gói vào `FinalAnswer` và trả về `GateOutcome(action="FINAL", decision="answer")`.
   * Phân biệt mã lý do: `VALID_RESULT` (nếu đúng ngay lần đầu) hoặc `VALID_RESULT_AFTER_RETRY` (nếu đúng sau khi retry).

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Thiết kế dạng "Pure Function" (Hàm thuần túy, không side-effect)**:
   * `evaluate_gate` chỉ nhận `GateRequest` và trả về `GateOutcome`. Nó **không tự ý gọi LLM**, **không tự ý kết nối DuckDB**, và **không tự ý ghi file vào ổ cứng**.
   * Việc tách biệt hoàn toàn logic quyết định khỏi I/O giúp module chạy cực nhanh (0.14 ms / câu) và cực kỳ dễ viết Unit Test giả lập.
2. **Bảo toàn tính bất biến (Contract Invariant)**:
   * Quy định sắt đá:
     * Nếu `action == "RETRY"` ➔ `final_answer` bắt buộc là `None`.
     * Nếu `action == "FINAL"` ➔ `final_answer` bắt buộc phải là một đối tượng `FinalAnswer` hợp lệ.
   * Không bao giờ có trạng thái nửa vời làm Orchestrator bối rối.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các File Khác

* **Đầu não của package `b05`**: Là nơi tích hợp các module `adapters`, `validators`, `retry`, `answerability`, `formatter`.
* **Giao diện làm việc với Orchestrator**: Script chạy chính của toàn đội (`cli.py` hoặc `pipeline.py`) chỉ cần gọi đúng hàm `evaluate_gate(request)` này.

---

## 5. Nếu Không Có File Này Thì Sao?

* Toàn bộ các module con sẽ là những mảnh ghép rời rạc không thể tự vận hành. Orchestrator bên ngoài sẽ phải tự viết lại hàng trăm dòng code if/else phức tạp để nối validator với retry và formatter, dễ dẫn đến sai sót và không kiểm soát được quy tắc chấm thi.

