# Giải Thích Mã Nguồn: `errors.py`
**Đường dẫn file:** `src/datamate/b05/errors.py`  
**Thuộc module:** B0.5 Basic Output Gate  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

File `errors.py` thiết lập **Hệ thống phân loại lỗi (Error Taxonomy)** và các **Custom Exception Classes** chuẩn hóa cho B0.5. 

Thay vì để code bắt các exception chung chung (`except Exception:`), file này định nghĩa mã lỗi rõ ràng để phân biệt:
- Lỗi nào **có thể sửa được (Retryable)**: Ví dụ sai tên cột, sai cú pháp SQL, sai số dòng kết quả.
- Lỗi nào **không thể sửa được (Non-retryable)**: Ví dụ vi phạm bảo mật, hết thời gian (timeout), kết quả bị cắt (truncated), hoặc tệp đầu vào sai định dạng hợp đồng.

---

## 2. Chi Tiết Các Class & Mã Lỗi

### 2.1. Lớp Hằng Số `ErrorCode`
Tập hợp các mã lỗi và mã lý do (reason codes) ổn định theo đặc tả kỹ thuật (§5, §11):

* **Nhóm Kết quả Hợp lệ**:
  * `VALID_RESULT`: Câu trả lời đạt chuẩn ngay từ lượt đầu (attempt 0).
  * `VALID_RESULT_AFTER_RETRY`: Câu trả lời đạt chuẩn sau lượt sửa lỗi (attempt 1).
  * `CONFIRMED_MISSING_EVIDENCE`: Câu hỏi được xác nhận là không thể trả lời được nhờ bằng chứng tin cậy.
* **Nhóm Lỗi Có Thể Sửa (Retryable - Cho phép retry ở attempt 0)**:
  * `SQL_SYNTAX`: Lỗi cú pháp SQL (ví dụ gõ nhầm `SELCT`).
  * `SCHEMA_ERROR`: Lỗi sai tên bảng, sai tên cột (`BinderException`).
  * `SQL_TYPE_ERROR`: Lỗi ép kiểu hoặc toán tử trong SQL.
  * `SCALAR_SHAPE_MISMATCH`: Câu hỏi dạng đơn trị (scalar) nhưng câu SQL trả về nhiều dòng/cột.
  * `OUTPUT_TYPE_ERROR`: Kiểu dữ liệu không khớp với mong đợi (ví dụ trả về chuỗi thay vì số).
* **Nhóm Lỗi Chấm Dứt Ngay (Non-retryable - Chuyển sang Abstain)**:
  * `EMPTY_RESULT`: Câu truy vấn trả về 0 dòng mà không có chính sách cho phép rỗng.
  * `NULL_RESULT`: Giá trị trả về là `NULL` (không ép về 0).
  * `QUERY_TIMEOUT`: Truy vấn vượt quá thời gian cho phép.
  * `TRUNCATED_RESULT`: Kết quả bị cắt ngắn do preview.
  * `SECURITY_VIOLATION`: Câu lệnh có hành vi ghi, xóa bảng (`DROP`, `DELETE`, `UPDATE`). Tuyệt đối không retry để bảo vệ an toàn.
  * `RETRY_EXHAUSTED`: Đã hết lượt retry (attempt 1 vẫn lỗi).
  * `CONTRACT_ERROR`: Đầu vào không tuân thủ cấu trúc hợp đồng `GateRequest`.
  * `TABLE_SHAPE_ERROR`: Số lượng cell trong dòng không khớp với số lượng cột.

---

### 2.2. Lớp DTO `ErrorClassification`
```python
@dataclass
class ErrorClassification:
    code: str             # Mã lỗi từ ErrorCode
    retryable: bool       # True nếu cho phép retry 1 lần, False nếu kết thúc ngay
    evidence: str         # Dữ liệu chứng cứ (raw error message hoặc mô tả lỗi)
    safe_feedback: str    # Lời nhắc an toàn, xúc tích để gửi lại cho LLM sửa SQL
```

---

### 2.3. Hệ Thống Phân Cấp Exception

* **`GateError(Exception)`**: Lớp cha cơ sở của mọi ngoại lệ trong B0.5. Chứa `message` và `code`.
* **`ContractError(GateError)`**: Ném ra khi JSON đầu vào vi phạm cấu trúc hợp đồng (ví dụ: ngày sai lịch `2026-02-30`, phiên bản không phải `b05.v1`).
* **`ValidationError(GateError)`**: Ném ra khi kết quả truy vấn vi phạm hình học (shape) hoặc chứa giá trị bất hợp lệ.
* **`FormattingError(GateError)`**: Ném ra khi không thể định dạng giá trị về 1 trong 9 types chuẩn (ví dụ count mà có phần thập phân).
* **`OutputWriteError(GateError)`**: Ném ra khi gặp lỗi I/O tệp tin lúc ghi `submission.jsonl` hoặc audit log.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Phân biệt rạch ròi giữa Retryable và Non-retryable**:
   * Thời gian thi đấu trên server GPU là có hạn. Nếu câu SQL bị lỗi cú pháp nhỏ, việc retry 1 lần có thể cứu được 1 điểm PA. Nhưng nếu câu SQL vi phạm bảo mật hoặc bị timeout do dữ liệu quá lớn, việc retry sẽ làm tốn thêm tài nguyên vô ích.
2. **Không để exception làm crash toàn bộ batch**:
   * Việc định nghĩa các lớp exception cụ thể giúp `gate.py` và `cli.py` bắt đúng loại lỗi, ghi nhận lý do vào audit log và chuyển thành câu trả lời `abstain` an toàn, thay vì để cả chương trình bị sập giữa chừng khi đang chạy 1,000 câu hỏi.
3. **Mã lỗi ổn định (Stable Reason Codes)**:
   * Các chuỗi thông báo lỗi của DuckDB (`error.message`) có thể thay đổi giữa các phiên bản (DuckDB 0.9 vs 1.1). Việc ánh xạ chúng thành các `ErrorCode` chuẩn giúp hệ thống thống kê Local CV hoạt động ổn định và nhất quán.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các File Khác

* **`adapters.py`**: Ném ra `ContractError` khi dữ liệu đầu vào không hợp lệ.
* **`validators.py`**: Sử dụng `ErrorCode` (`EMPTY_RESULT`, `NULL_RESULT`, `TRUNCATED_RESULT`, v.v.) để gán vào `ValidationResult`.
* **`retry.py`**: Dựa vào `ErrorCode` để quyết định xem có cấp quyền retry hay không.
* **`formatter.py`**: Ném ra `FormattingError` kèm `ErrorCode.OUTPUT_TYPE_ERROR` hoặc `ErrorCode.NULL_RESULT`.
* **`audit.py`**: Lưu `reason_code` vào tệp log JSON để đội thi kiểm tra sau khi chạy benchmark.

---

## 5. Nếu Không Có File Này Thì Sao?

* Hệ thống không thể phân loại lỗi tự động, dẫn đến việc: hoặc retry mù quáng cho mọi lỗi (kể cả lỗi bảo mật, timeout), hoặc không bao giờ retry và mất điểm oan.
* Mọi lỗi ngoại lệ sẽ chỉ là `Exception` chung chung, khiến việc debug và phân tích nguyên nhân thất bại trên tập test ẩn trở nên bất khả thi.

