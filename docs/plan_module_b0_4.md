# KẾ HOẠCH TRIỂN KHAI MODULE B0.4: DUCKDB READ-ONLY EXECUTION ENGINE

## 1. Tổng Quan & Mục Tiêu (Overview & Objectives)
Module **B0.4 · Execute (DuckDB read-only)** nằm ở trung tâm của pipeline **Baseline B0 (Direct Text-to-SQL)**. Module có nhiệm vụ:
1. Tiếp nhận câu lệnh SQL từ `B0.3 · One LLM (SQL + answer type)` hoặc từ vòng lặp sửa lỗi `One bounded retry (LLM + error message)`.
2. Kiểm tra tính an toàn và thực thi truy vấn trên DuckDB ở chế độ **chỉ đọc (read-only)** dựa trên dữ liệu đã nạp/cache từ `B0.1 · Loader (Read / type / cache)`.
3. Đánh giá tính hợp lệ của câu truy vấn và kết quả (`SQL / result valid?`):
   - **Nếu hợp lệ (`yes`):** Xuất dữ liệu thô chuẩn hóa sang `B0.5 · Format / Gate (9 types + fallback)`.
   - **Nếu lỗi nhưng có thể khắc phục (`recoverable`):** Trích xuất thông báo lỗi sạch gửi sang `One bounded retry (LLM + error message)` để chạy lại (`rerun corrected SQL`).
   - **Nếu lỗi không thể khắc phục hoặc đã dùng hết lượt thử lại (`failed / used retry`):** Chuyển trạng thái sang `Abstain if unresolved`.

---

## 2. Công Nghệ & Thư Viện Sử Dụng (Tech Stack)
* **Ngôn ngữ:** Python 3.10+
* **Core Database Engine:** `duckdb` (>= 1.0.0) - Hỗ trợ truy vấn OLAP tốc độ cao, chế độ `read_only=True`, giới hạn tài nguyên và ngắt truy vấn (`con.interrupt()`).
* **Xử lý & Phân tích cú pháp SQL (Static Guardrail):** `sqlglot` - Kiểm tra AST (Abstract Syntax Tree) của câu SQL trước khi chạy, chặn các lệnh phá hoại (DDL/DML) và chuẩn hóa dialect sang DuckDB.
* **Định dạng dữ liệu trung gian:** `pandas` / `pyarrow` - Chuyển đổi kết quả truy vấn sang danh sách bản ghi Python nguyên thủy chuẩn hóa cho `B0.5`.
* **Quản lý Timeout:** `threading.Timer` kết hợp `con.interrupt()` của DuckDB để hủy các truy vấn bị treo (`CROSS JOIN` lớn, đệ quy vô hạn) đúng số giây quy định.
* **Kiểm thử & Logging:** `pytest` (Unit Test & Stress Test), `pydantic` (Chuẩn hóa Input/Output Contract), `logging` (Xuất `error logs`).

---

## 3. Cấu Trúc Thư Mục Đề Xuất (Directory Structure)
```text
src/
└── b0_4_executor/
    ├── __init__.py
    ├── schemas.py          # Định nghĩa Input/Output Contract (Pydantic Models)
    ├── sanitizer.py        # Lọc markdown, kiểm tra AST SQL bằng sqlglot
    ├── engine.py           # Khởi tạo DuckDB read-only, cấu hình sandbox, timeout & thực thi
    └── error_handler.py    # Phân loại lỗi (recoverable vs abstain) và rút gọn error_message
tests/
├── mock_data/              # Chứa script tạo file .duckdb giả lập từ tập train/public_test
│   └── build_mock_db.py
└── test_b0_4_executor.py   # Bộ unit test đầy đủ các kịch bản
```

---

## 4. Đặc Tả Giao Diện (Interface Contract)

### 4.1. Đầu vào (`ExecutionRequest`)
```python
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

class ExecutionRequest(BaseModel):
    question_id: str = Field(..., description="ID của câu hỏi để ghi nhận vào JSONL và error logs")
    db_path: str = Field(..., description="Đường dẫn tới file .duckdb hoặc thư mục dữ liệu đã cache từ B0.1")
    sql_query: str = Field(..., description="Câu truy vấn SQL sinh ra từ B0.3 hoặc từ vòng retry")
    answer_type: Optional[str] = Field(default=None, description="Loại câu trả lời kỳ vọng từ B0.3 (1 trong 9 types)")
    retry_count: int = Field(default=0, ge=0, description="0 cho lần chạy đầu, >=1 cho lần rerun corrected SQL")
    max_retries: int = Field(default=1, ge=0, description="Giới hạn số lần thử lại (mặc định: 1 cho One bounded retry)")
    timeout_sec: float = Field(default=10.0, gt=0, description="Thời gian thực thi tối đa (giây)")
    max_rows: int = Field(default=10000, gt=0, description="Giới hạn số dòng trả về để bảo vệ bộ nhớ")
```

### 4.2. Đầu ra (`ExecutionResponse`)
```python
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel

class ExecutionResponse(BaseModel):
    question_id: str
    is_valid: bool                                      # True nếu đi nhánh 'yes', False nếu có lỗi
    route: Literal["yes", "recoverable", "abstain"]     # Nhánh điều hướng tiếp theo trên sơ đồ B0
    cleaned_sql: Optional[str] = None                   # Câu SQL sau khi đã bóc tách markdown
    columns: Optional[List[str]] = None                 # Danh sách tên cột trả về
    rows: Optional[List[Dict[str, Any]]] = None         # Dữ liệu kết quả đã chuẩn hóa kiểu Python (phục vụ B0.5)
    row_count: int = 0                                  # Số lượng dòng trả về
    error_type: Optional[str] = None                    # SyntaxError, CatalogError, BinderError, TimeoutError, SecurityViolation...
    error_message: Optional[str] = None                 # Thông báo lỗi tinh gọn để truyền vào LLM ở bước One bounded retry
    execution_time_ms: float = 0.0                      # Thời gian thực thi (mili-giây)
```

---

## 5. Quy Trình Triển Khai Code Chi Tiết (Step-by-Step Implementation Plan)

### Bước 1: Xây dựng Data Contract & Chuẩn hóa kiểu dữ liệu (`schemas.py`)
* Cài đặt `ExecutionRequest` và `ExecutionResponse`.
* Viết hàm `normalize_value(val)` để chuyển đổi các kiểu dữ liệu đặc thù của DuckDB/Pandas sang kiểu JSON-safe cho `B0.5` và `JSONL`:
  * `pd.isna(val)` / `np.nan` / `math.isnan` / `math.isinf` $\rightarrow$ `None`.
  * `datetime.date` / `datetime.datetime` / `pd.Timestamp` $\rightarrow$ chuỗi ISO `YYYY-MM-DD` hoặc `YYYY-MM-DDTHH:MM:SS`.
  * `decimal.Decimal` $\rightarrow$ `float` (hoặc `int` nếu không có phần thập phân).
  * `bytes` / `bytearray` $\rightarrow$ chuỗi UTF-8 hoặc hex.

### Bước 2: Xây dựng Bộ lọc Tiền thực thi (`sanitizer.py`)
1. **Trích xuất & Làm sạch SQL (`extract_clean_sql`):**
   * Nếu chuỗi chứa block ` ```sql ... ``` ` hoặc ` ``` ... ``` `, trích xuất phần bên trong.
   * Loại bỏ khoảng trắng thừa, bình luận rỗng và dấu `;` dư thừa ở cuối.
   * Nếu chuỗi rỗng sau khi làm sạch $\rightarrow$ trả lỗi `EmptyQueryError`.
2. **Kiểm tra an toàn tĩnh (`validate_read_only_sql`):**
   * Dùng `sqlglot.parse(sql, read="duckdb")`.
   * Chặn trường hợp multi-statement (nhiều câu lệnh ngăn cách bởi dấu `;` có nguy cơ SQL Injection).
   * Kiểm tra cây cú pháp (AST): Câu lệnh gốc bắt buộc phải thuộc nhóm `exp.Select`, `exp.Union`, `exp.Intersect`, `exp.Except` (bao gồm cả `WITH ... SELECT`).
   * Từ chối ngay lập tức (`SecurityViolation`) nếu phát hiện các node: `Drop`, `Delete`, `Update`, `Insert`, `Create`, `Alter`, `Copy`, `Attach`, `Detach`, `Install`, `Load`, `Pragma`, `Set` hoặc các hàm đọc file trực tiếp như `read_csv`, `read_parquet`, `read_json`.

### Bước 3: Xây dựng Lõi Thực Thi DuckDB Read-Only (`engine.py`)
1. **Hỗ trợ linh hoạt định dạng Cache từ `B0.1`:**
   * **Trường hợp 1 (`db_path` là file `.duckdb`):**
     * Mở kết nối trực tiếp ở chế độ chỉ đọc: `con = duckdb.connect(database=db_path, read_only=True)`.
   * **Trường hợp 2 (`db_path` là thư mục chứa các file `.parquet` / `.csv`):**
     * Mở kết nối in-memory, tự động tạo các `VIEW` tương ứng với tên file trong thư mục, sau đó khóa quyền truy cập ngoài.
2. **Thiết lập Sandbox & Giới hạn tài nguyên:**
   ```sql
   SET max_memory = '2GB';
   SET threads = 2;
   SET enable_external_access = false;
   SET lock_configuration = true;
   ```
3. **Thực thi với Timeout (`threading.Timer` + `con.interrupt()`):**
   * Khởi tạo cờ `timed_out = False`.
   * Đặt `timer = threading.Timer(request.timeout_sec, on_timeout)` trong đó `on_timeout` đánh dấu `timed_out = True` và gọi `con.interrupt()`.
   * Thực thi `cursor = con.execute(cleaned_sql)`, lấy tên cột từ `cursor.description` và lấy dữ liệu qua `cursor.fetchmany(request.max_rows)`.
   * Hủy `timer.cancel()` trong khối `finally` và đóng kết nối `con.close()` để đảm bảo hoàn toàn **stateless** và không rò rỉ RAM.

### Bước 4: Phân loại lỗi & Điều hướng (`error_handler.py`)
Bắt toàn bộ ngoại lệ từ Sanitizer và DuckDB để ánh xạ sang nhánh `route` của khối `SQL / result valid?`:

1. **Làm sạch thông báo lỗi (`format_duckdb_error`):**
   * Loại bỏ đường dẫn file hệ thống nội bộ hoặc stack trace của Python.
   * Giữ nguyên thông báo lỗi gốc của DuckDB (ví dụ: `Catalog Error: Table with name "..." does not exist! Did you mean "..."?` kèm dòng `LINE 1: ... ^`) vì gợi ý `Did you mean` của DuckDB cực kỳ hữu ích cho LLM ở bước `One bounded retry`.
2. **Quy tắc điều hướng (`determine_route`):**
   * **Nếu thực thi không có lỗi:** `is_valid = True`, `route = "yes"`.
   * **Nếu có lỗi và `retry_count >= max_retries`:** Đã dùng hết lượt thử lại (`failed / used retry`) $\rightarrow$ `is_valid = False`, `route = "abstain"`.
   * **Nếu có lỗi và `retry_count < max_retries` (Lần chạy đầu `retry_count == 0`):**
     * **Nhóm lỗi có thể khắc phục (`route = "recoverable"`):**
       * `duckdb.ParserException` (`SyntaxError`)
       * `duckdb.CatalogException` (`CatalogError` - sai tên bảng/cột/hàm)
       * `duckdb.BinderException` (`BinderError` - sai kiểu dữ liệu phép toán, lỗi `GROUP BY`)
       * `duckdb.ConversionException` (`ConversionError` - lỗi `CAST`, định dạng ngày tháng)
       * `duckdb.DataError` / `duckdb.OutOfRangeException` (`DataError` - chia cho 0, tràn số)
       * `TimeoutError` / `duckdb.InterruptException` (Báo cho LLM tối ưu lại `JOIN` / điều kiện lọc)
       * `EmptyQueryError` / `SecurityViolation` (Yêu cầu LLM chỉ sinh duy nhất 1 câu lệnh `SELECT`)
     * **Nhóm lỗi hệ thống nghiêm trọng (`route = "abstain"`):**
       * `FileNotFoundError` / `duckdb.IOException` (Không tìm thấy file database từ `B0.1`)
       * `duckdb.OutOfMemoryException` / `duckdb.InternalException`

### Bước 5: Xây dựng Script Mock Data & Bộ Unit Test (`tests/`)
1. **Tạo Mock DB (`tests/mock_data/build_mock_db.py`):**
   * Tự động quét thư mục dữ liệu thật của dự án (nếu có) hoặc tạo một file `sample_cache.duckdb` chứa 2 bảng mẫu (`transactions`, `customers`) để phục vụ kiểm thử độc lập.
2. **Viết 7 kịch bản kiểm thử trong `tests/test_b0_4_executor.py`:**
   * `test_01_valid_sql_execution`: Câu lệnh `SELECT` hợp lệ (có kèm markdown ` ```sql `) $\rightarrow$ `is_valid=True`, `route="yes"`, dữ liệu trả về sạch.
   * `test_02_syntax_error_recoverable`: Câu lệnh sai cú pháp ở `retry_count=0` $\rightarrow$ `is_valid=False`, `route="recoverable"`, `error_type="SyntaxError"`.
   * `test_03_catalog_error_recoverable`: Truy vấn cột không tồn tại ở `retry_count=0` $\rightarrow$ `is_valid=False`, `route="recoverable"`, `error_type="CatalogError"`.
   * `test_04_rerun_corrected_sql_success`: Giả lập luồng `One bounded retry` gửi lại câu SQL đã sửa ở `retry_count=1` $\rightarrow$ `is_valid=True`, `route="yes"`.
   * `test_05_failed_after_retry_abstain`: Câu lệnh vẫn lỗi khi `retry_count=1` $\rightarrow$ `is_valid=False`, `route="abstain"`.
   * `test_06_security_guardrail_read_only`: Thử chạy `DROP TABLE`, `INSERT`, `COPY`, `read_csv` $\rightarrow$ Bị chặn ngay lập tức, `error_type="SecurityViolation"`, bảng gốc nguyên vẹn 100%.
   * `test_07_infinite_query_timeout`: Chạy CTE đệ quy vô hạn với `timeout_sec=1.0` $\rightarrow$ Tự động ngắt đúng sau ~1 giây, `error_type="TimeoutError"`, không làm treo pytest.

---

## 6. Hướng Dẫn Giao Việc Cho Antigravity (Prompt Mẫu)
Sau khi tải file `B0_4_EXECUTION_PLAN.md` này vào thư mục gốc của project, bạn có thể gửi prompt sau cho Antigravity:

> "Hãy đọc kỹ file `@B0_4_EXECUTION_PLAN.md` và triển khai toàn bộ module `src/b0_4_executor/` cùng bộ kiểm thử `tests/` theo đúng đặc tả trong kế hoạch. Nếu trong project đã có sẵn thư mục dữ liệu `train` hoặc `public_test`, hãy khảo sát 1 mẫu dữ liệu để nạp vào `tests/mock_data/build_mock_db.py`. Sau khi viết code xong, hãy chạy `pytest -v` và đảm bảo pass 100% các bài test."
