# Giải Thích Mã Nguồn: `error_handler.py` (B0.4)

**Đường dẫn file:** [`src/datamate/b0/b04/error_handler.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/error_handler.py)  
**Thuộc module:** B0.4 DuckDB Read-Only Execution Engine  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `error_handler.py` là **Bộ xử lý lỗi và điều hướng thông minh (Error Classification & Routing)** của module B0.4. Khi một truy vấn SQL gặp sự cố (lỗi cú pháp, sai tên cột/bảng, tràn thời gian timeout, lỗi IO), file này chịu trách nhiệm:
1. Phân loại chính xác loại lỗi (`error_type`).
2. Xác định xem lỗi đó có thể sửa chữa được bằng LLM hay không (`is_recoverable`).
3. Điều hướng luồng thực thi: chuyển sang **One Bounded Retry** (`route = "recoverable"`) hay chuyển sang cổng từ bỏ an toàn của B0.5 (`route = "abstain"`).
4. Làm sạch thông báo lỗi, loại bỏ đường dẫn file nội bộ của máy chủ để đưa ra gợi ý sửa lỗi tối ưu nhất cho LLM.

---

## 2. Chi Tiết Các Hàm Chức Năng

### 2.1. Tập Hợp Lỗi Có Thể Tự Phục Hồi (`RECOVERABLE_ERROR_TYPES`)
```python
RECOVERABLE_ERROR_TYPES = {
    "SyntaxError", "CatalogError", "BinderError", "ConversionError",
    "DataError", "TimeoutError", "SecurityViolation", "EmptyQueryError",
}
```
* Đây là các lỗi mà nguyên nhân xuất phát từ việc mô hình LLM viết sai cú pháp SQL, gọi sai tên cột/bảng hoặc đặt điều kiện join chưa tối ưu. Việc cung cấp lại thông báo lỗi cho LLM ở lần retry tiếp theo có xác suất sửa chữa thành công rất cao.

### 2.2. Hàm `classify_error(exc: Exception) -> Tuple[str, bool]`
* Ánh xạ các ngoại lệ của DuckDB và Python thành định danh chuẩn:
  * `EmptyQueryError` $\rightarrow$ `("EmptyQueryError", True)`
  * `SecurityViolation`, `duckdb.PermissionException` $\rightarrow$ `("SecurityViolation", True)`
  * `QueryTimeoutError`, `duckdb.InterruptException` $\rightarrow$ `("TimeoutError", True)`
  * `duckdb.ParserException`, `SyntaxError` $\rightarrow$ `("SyntaxError", True)`
  * `duckdb.CatalogException` (bảng/hàm không tồn tại) $\rightarrow$ `("CatalogError", True)`
  * `duckdb.BinderException` (cột không tồn tại, kiểu không khớp) $\rightarrow$ `("BinderError", True)`
  * `duckdb.ConversionException` $\rightarrow$ `("ConversionError", True)`
  * `duckdb.DataError`, `duckdb.OutOfRangeException` $\rightarrow$ `("DataError", True)`
  * `FileNotFoundError`, `duckdb.IOException` $\rightarrow$ `("DatabaseIOError", False)` (Lỗi hệ thống, không thể sửa bằng SQL retry).
  * `duckdb.OutOfMemoryException` $\rightarrow$ `("OutOfMemoryError", False)`.
  * Các ngoại lệ khác $\rightarrow$ `("ExecutionError", False)`.

### 2.3. Hàm `determine_route(...) -> Literal["recoverable", "abstain"]`
* **Thuật toán điều hướng:**
  1. Nếu đã cạn số lượt thử lại (`retry_count >= max_retries`), lập tức trả về `"abstain"` để tránh lặp vô tận.
  2. Nếu lỗi được đánh giá là `is_recoverable` và nằm trong `RECOVERABLE_ERROR_TYPES`, trả về `"recoverable"`.
  3. Tất cả các trường hợp còn lại (lỗi IO, lỗi hệ thống) đều trả về `"abstain"`.

### 2.4. Hàm `format_error_message(exc, error_type, timeout_sec) -> str`
* Tinh chỉnh thông báo lỗi để đưa vào prompt cho LLM:
  * Nếu là `TimeoutError`: Đưa ra hướng dẫn cụ thể *"Query execution timed out after Xs. Please check for Cartesian joins, missing WHERE clauses..."*.
  * Nếu là `EmptyQueryError`: Hướng dẫn *"SQL query is empty. Please provide a valid, single SELECT query."*.
  * Nếu là `SecurityViolation`: Ghi rõ *"Security Violation: ... Only single read-only SELECT queries are permitted."*.
  * Với các lỗi DuckDB: Dùng Regex xóa bỏ các đường dẫn file Python máy chủ (ví dụ: `File "...", line 123...` hoặc `C:\foo\bar.py`), bảo tồn nguyên vẹn vị trí dòng lỗi của DuckDB và gợi ý *"Did you mean column X?"*.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Bảo vệ quyền riêng tư & Bảo mật máy chủ:**
   Việc xóa bỏ đường dẫn file nội bộ máy chủ (`/home/kiet97/...`) khỏi thông báo lỗi ngăn chặn rò rỉ cấu trúc thư mục máy chủ ra bên ngoài và tránh làm rối token ngữ cảnh của LLM.
2. **Ngăn chặn vòng lặp vô hạn (Infinite Retry Loop):**
   Hàm `determine_route` kiểm tra `retry_count >= max_retries`, đảm bảo hệ thống chỉ thử lại đúng 1 lần (One Bounded Retry) rồi chuyển sang trạng thái dừng an toàn `abstain`.

---

## 4. Tương Thích & Mối Liên Hệ

* Được gọi trong khối `except` của [`engine.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/engine.md).
* Cung cấp thông điệp lỗi cho hàm `build_repair_messages` của [`prompt.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/prompt.md).

---

## 5. Nếu Không Có File Này Thì Sao?

* Mọi ngoại lệ của DuckDB sẽ làm crash toàn bộ tiến trình nạp bài.
* LLM ở bước retry sẽ không nhận được thông báo lỗi có cấu trúc, khiến khả năng tự sửa lỗi gần như bằng không.

