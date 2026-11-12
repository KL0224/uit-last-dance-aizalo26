# Giải Thích Mã Nguồn: `schemas.py` (B0.4)

**Đường dẫn file:** [`src/datamate/b0/b04/schemas.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/schemas.py)  
**Thuộc module:** B0.4 DuckDB Read-Only Execution Engine  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `schemas.py` định nghĩa các bản hợp đồng dữ liệu đầu vào và đầu ra cho Tầng thực thi cơ sở dữ liệu DuckDB bằng thư viện `pydantic`. Đồng thời, tệp cung cấp hàm chuẩn hóa dữ liệu `normalize_value` và các phương thức Adapter chuyển đổi tương thích hai chiều giữa **B0.3 (Text-to-SQL)** và **B0.5 (Output Gatekeeper)**.

---

## 2. Chi Tiết Các Lớp & Hàm Chức Năng

### 2.1. Các Lớp Ngoại Lệ Nghiệp Vụ
* **`EmptyQueryError(Exception)`**: Kích hoạt khi câu SQL rỗng hoặc chỉ có khoảng trắng/comment.
* **`SecurityViolation(Exception)`**: Kích hoạt khi phát hiện lệnh phá hoại DDL/DML, đọc file trái phép, hoặc tấn công Multi-statement Injection.
* **`QueryTimeoutError(Exception)`**: Kích hoạt khi thời gian thực thi vượt quá ngưỡng `timeout_sec`.

### 2.2. Lớp `ExecutionRequest(BaseModel)`
* **Các trường:**
  * `question_id`: Mã định danh câu hỏi để log và audit.
  * `db_path`: Đường dẫn tới file `.duckdb`, thư mục dữ liệu, hoặc `":memory:"`.
  * `sql_query`: Câu truy vấn SQL cần thực thi.
  * `answer_type`: Loại câu trả lời kỳ vọng từ B0.3 (1 trong 9 types).
  * `retry_count`: Số lần đã thử lại (0 cho lần đầu, 1 cho retry).
  * `max_retries`: Giới hạn thử lại (mặc định 1 cho One Bounded Retry).
  * `timeout_sec`: Thời gian tối đa cho phép chạy (mặc định 10.0 giây).
  * `max_rows`: Giới hạn số dòng nạp vào RAM (mặc định 10,000 dòng).
* **Phương thức Factory `from_b03(cls, b03_result, question_id, db_path, ...)`:**
  * Tiếp nhận trực tiếp đối tượng [`Text2SQLResult`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/types.md) từ B0.3, tự động trích xuất `sql` và chuẩn hóa `answer_type` qua `normalize_answer_type` (ví dụ chuyển các alias `"money"`, `"int"`, `"float"` về `"number"`), tạo thành `ExecutionRequest` chuẩn chỉnh để kích hoạt chính xác kiểm tra `EmptyResultWarning`.

### 2.3. Lớp `ExecutionResponse(BaseModel)`
* **Các trường:**
  * `question_id`: Mã định danh câu hỏi.
  * `is_valid`: `True` nếu thực thi thành công, `False` nếu có lỗi.
  * `route`: Hướng đi tiếp theo (`"yes"`, `"recoverable"`, hoặc `"abstain"`).
  * `cleaned_sql`: Câu lệnh SQL đã được làm sạch và bóc tách khỏi markdown.
  * `columns`: Danh sách tên các cột trả về.
  * `rows`: Danh sách các dictionary chứa từng dòng kết quả đã chuẩn hóa.
  * `row_count`: Số lượng dòng trả về.
  * `error_type`: Phân loại lỗi (`SyntaxError`, `BinderError`, `CatalogError`, `ConversionError`, `EmptyResultWarning`, `TimeoutError`...).
  * `error_message`: Thông điệp lỗi tinh gọn (kèm `[Gợi ý Schema thực tế trong DB]` khi gặp lỗi schema/cast) truyền vào prompt của B0.3 khi retry.
  * `execution_time_ms`: Thời gian thực thi (mili-giây).
  * `truncated`: `True` nếu số dòng thực tế vượt quá `max_rows` và đã bị cắt bớt.
* **Phương thức Adapter `to_b05_execution_result(self) -> Any`:**
  * Tự động chuyển đổi sang đối tượng `ExecutionResult` của B0.5:
    * Nếu thành công: biến đổi danh sách dict thành ma trận giá trị `rows: List[List[Any]]` khớp thứ tự `columns`, gán `status = "success"`.
    * Nếu thất bại: gán `status = "error"` và đóng gói `ExecutionErrorDetail(type, message)`.

### 2.4. Hàm `normalize_value(val: Any) -> Any`
* Đảm bảo mọi giá trị từ DuckDB, Pandas, NumPy được chuyển đổi thành các kiểu nguyên thủy của Python an toàn với JSON:
  * `NaN`, `+inf`, `-inf`, `pd.NA` $\rightarrow$ `None`.
  * `datetime.date`, `datetime.datetime` $\rightarrow$ chuỗi chuẩn ISO 8601 (`YYYY-MM-DD` / `YYYY-MM-DDTHH:MM:SS`).
  * `decimal.Decimal` $\rightarrow$ `int` nếu là số nguyên, `float` nếu có phần thập phân.
  * `bytes`, `bytearray` $\rightarrow$ giải mã UTF-8 hoặc hex.
  * Đệ quy chuẩn hóa toàn bộ phần tử trong `list`, `tuple`, `dict`.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Phòng chống lỗi JSON Serialization ở B0.5:**
   DuckDB và Pandas thường trả về các đối tượng đặc thù như `numpy.int64`, `numpy.nan`, `decimal.Decimal`, `Timestamp`. Nếu không đưa qua `normalize_value`, khi B0.5 ghi kết quả vào file `submission.jsonl`, thư viện `json.dumps()` sẽ crash ngay lập tức vì `TypeError: Object of type Decimal is not JSON serializable`.
2. **Cầu nối Adapter 2 chiều hoàn hảo:**
   Nhờ có `from_b03` và `to_b05_execution_result`, ba module B0.3 $\rightarrow$ B0.4 $\rightarrow$ B0.5 có thể giao tiếp với nhau mà không cần bất kỳ hàm trung gian nào bên ngoài.

---

## 4. Tương Thích & Mối Liên Hệ

* Kết nối trực tiếp với [`Text2SQLResult`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/types.md) của B0.3.
* Cung cấp dữ liệu cho [`ExecutionResult`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/contracts.py) của B0.5.

---

## 5. Nếu Không Có File Này Thì Sao?

* Dữ liệu trả về từ DuckDB sẽ không đồng nhất về kiểu.
* Pipeline sẽ phải đối mặt với nguy cơ sập khi ghi file JSONL vì các kiểu dữ liệu NaN, Infinity và Decimal.

