# ĐẶC TẢ GIAO DIỆN ĐẦU VÀO & ĐẦU RA (I/O SPECIFICATION)
## Module B0.4 · DuckDB Read-Only Execution Engine
### Dự án: DataMate – Zalo AI Challenge 2026 (Track 2) | Team: UIT Last Dance

---

## 1. Tổng Quan & Vị Trí Trong Pipeline Baseline B0

Module **B0.4 · Execute (DuckDB read-only)** là trái tim thực thi truy vấn của pipeline **Baseline B0 (Direct Text-to-SQL)**:

```text
┌──────────────────────────────────────┐       ┌──────────────────────────────────────┐
│  B0.1 · Loader (Read / type / cache) │       │ B0.3 · One LLM (SQL + answer type)   │
│  (Tạo file .duckdb cache từ data)    │       │ (Sinh câu lệnh SQL & loại câu TL)    │
└──────────────────┬───────────────────┘       └──────────────────┬───────────────────┘
                   │                                              │
                   │ db_path                                      │ sql_query, answer_type
                   ▼                                              ▼
       ══════════════════════════════════════════════════════════════════════
       ║             B0.4 · Execute (DuckDB Read-Only Engine)               ║
       ══════════════════════════════════════════════════════════════════════
                                         │
                                         ▼
                             [ SQL / result valid? ]
                            /           │           \
                  "yes"    /   "recoverable"         \  "abstain"
                          /             │             \
                         ▼              ▼              ▼
           ┌──────────────────┐  ┌─────────────┐  ┌────────────────────────┐
           │   B0.5 · Gate    │  │ One bounded │  │  Abstain if            │
           │ (9 types + fall) │  │ retry (LLM) │  │  unresolved (0 điểm)   │
           └──────────────────┘  └─────────────┘  └────────────────────────┘
```

### Nhiệm vụ cốt lõi:
1. **Tiếp nhận:** File cache database từ `B0.1` cùng câu lệnh SQL từ `B0.3` (hoặc từ vòng lặp `One bounded retry`).
2. **Kiểm tra an toàn tĩnh (Static AST Guardrail):** Bóc tách markdown, chặn đứng multi-statement injection và các lệnh phá hoại (DDL/DML/truy cập file ngoài) bằng `sqlglot`.
3. **Thực thi trong Sandbox:** Chạy trên DuckDB ở chế độ `read_only=True`, ngắt cứng truy vấn treo bằng `con.interrupt()` khi quá `timeout_sec`.
4. **Chuẩn hóa dữ liệu:** Chuyển đổi toàn bộ kết quả DuckDB/Pandas sang kiểu nguyên thủy Python (`JSON-safe`) phục vụ cho `B0.5`.
5. **Điều hướng chính xác:** Phân loại lỗi và điều hướng luồng sang `yes`, `recoverable` hoặc `abstain`.

---

## 2. Đặc Tả Chi Tiết Đầu Vào (`ExecutionRequest`)

Lớp `ExecutionRequest` được định nghĩa bằng **Pydantic Model** (tại `src/b0_4_executor/schemas.py`).

### 2.1. Bảng thuộc tính tham số

| Tên trường | Kiểu dữ liệu | Mặc định | Ràng buộc | Mô tả & Ý nghĩa thực tế |
| :--- | :--- | :---: | :---: | :--- |
| `question_id` | `str` | *Bắt buộc* | Không rỗng | Mã ID định danh của câu hỏi (ví dụ: `"q_00eadfc5c599"` trong `questions.jsonl`). Dùng để đối soát log lỗi và ghi nhận kết quả. |
| `db_path` | `str` | *Bắt buộc* | Đường dẫn hợp lệ | Đường dẫn tới tệp database `.duckdb` đã nạp sẵn bởi `B0.1`, hoặc đường dẫn tới thư mục chứa các bảng dữ liệu (`.parquet`, `.csv`, `.xlsx`). Hỗ trợ cả `":memory:"`. |
| `sql_query` | `str` | *Bắt buộc* | Không rỗng | Chuỗi câu lệnh SQL do LLM sinh ra. Chấp nhận chuỗi SQL thuần hoặc được bọc trong khối markdown ` ```sql ... ``` ` / ` ``` ... ``` `. |
| `answer_type` | `Optional[str]` | `None` | 1 trong 9 types | Loại câu trả lời dự kiến do `B0.3` suy đoán (`number`, `string`, `percent`, `list`, `table`, `boolean`, `date`, `unanswerable`). |
| `retry_count` | `int` | `0` | $\ge 0$ | Số lần đã thử lại câu hỏi này. Giá trị `0` cho lần thực thi đầu tiên; giá trị `1` cho lần chạy lại câu SQL đã sửa (`rerun corrected SQL`). |
| `max_retries` | `int` | `1` | $\ge 0$ | Giới hạn số lần thử lại tối đa cho quy trình `One bounded retry` (mặc định: `1`). |
| `timeout_sec` | `float` | `10.0` | $> 0$ | Thời gian tối đa cho phép thực thi truy vấn (giây). Khi vượt quá, engine tự động ngắt kết nối và trả về lỗi `TimeoutError`. |
| `max_rows` | `int` | `10000` | $> 0$ | Số dòng tối đa được phép fetch về bộ nhớ nhằm bảo vệ RAM trước các truy vấn Cartesian product không giới hạn. |

### 2.2. Ví dụ tạo `ExecutionRequest` (Python Code)

```python
from src.b0_4_executor import ExecutionRequest

# Lần chạy đầu tiên từ B0.3:
request = ExecutionRequest(
    question_id="q_00eadfc5c599",
    db_path="cache/biz_104.duckdb",
    sql_query="""
    ```sql
    SELECT COUNT(DISTINCT "Mã đơn hàng") AS canceled_orders_count
    FROM donhang
    WHERE "Trạng thái đơn hàng" = 'Đã hủy'
      AND strptime("Ngày đặt hàng", '%d/%m/%Y') >= '2025-12-01'
      AND strptime("Ngày đặt hàng", '%d/%m/%Y') <= '2025-12-31';
    ```
    """,
    answer_type="number",
    retry_count=0,
    max_retries=1,
    timeout_sec=10.0,
    max_rows=10000
)
```

---

## 3. Đặc Tả Chi Tiết Đầu Ra (`ExecutionResponse`)

Lớp `ExecutionResponse` được định nghĩa bằng **Pydantic Model** (tại `src/b0_4_executor/schemas.py`).

### 3.1. Bảng thuộc tính kết quả

| Tên trường | Kiểu dữ liệu | Giá trị có thể nhận | Mô tả chi tiết |
| :--- | :--- | :---: | :--- |
| `question_id` | `str` | - | ID câu hỏi tương ứng truyền vào từ request. |
| `is_valid` | `bool` | `True` / `False` | Trạng thái tổng quát: `True` nếu câu truy vấn an toàn và thực thi thành công; `False` nếu có lỗi hoặc vi phạm an toàn. |
| `route` | `Literal` | `"yes"`<br>`"recoverable"`<br>`"abstain"` | **Nhánh điều hướng tiếp theo trên sơ đồ kiến trúc Baseline B0**: xem bảng mục 3.2. |
| `cleaned_sql` | `Optional[str]` | Chuỗi SQL hoặc `None` | Câu lệnh SQL sau khi đã bóc tách sạch các thẻ markdown, loại bỏ khoảng trắng và dấu chấm phẩy thừa. |
| `columns` | `Optional[List[str]]` | `['col1', ...]` hoặc `None` | Danh sách tên các cột trả về từ bảng kết quả. Trả về `None` nếu có lỗi. |
| `rows` | `Optional[List[Dict[str, Any]]]` | `[{'col': val}, ...]` hoặc `None` | Danh sách các bản ghi kết quả đã chuẩn hóa kiểu dữ liệu nguyên thủy Python (JSON-safe). |
| `row_count` | `int` | $\ge 0$ | Tổng số lượng dòng kết quả lấy được (`len(rows)`). |
| `error_type` | `Optional[str]` | Tên mã lỗi hoặc `None` | Phân loại lỗi chuẩn hóa: `SyntaxError`, `CatalogError`, `BinderError`, `TimeoutError`, `SecurityViolation`,... |
| `error_message` | `Optional[str]` | Chuỗi text hoặc `None` | Thông báo lỗi ngắn gọn, sạch sẽ, đã loại bỏ đường dẫn nội bộ máy chủ, giữ nguyên con trỏ dòng và gợi ý `Did you mean` của DuckDB để đưa vào prompt sửa lỗi của LLM. |
| `execution_time_ms` | `float` | $\ge 0.0$ | Tổng thời gian phân tích, chuẩn hóa và thực thi câu truy vấn (đơn vị: mili-giây). |

---

### 3.2. Quy Tắc Điều Hướng Nhánh (`route`)

Trường `route` đại diện cho các mũi tên quyết định trên sơ đồ kiến trúc:

| Giá trị `route` | Điều kiện kích hoạt | Bước tiếp theo trong Pipeline B0 |
| :---: | :--- | :--- |
| **`"yes"`** | Thực thi thành công không có lỗi (`is_valid = True`). | Chuyển dữ liệu sang **`B0.5 · Format / Gate`** để định dạng thành 1 trong 9 types nộp bài. |
| **`"recoverable"`** | Có lỗi phát sinh NHƯNG `retry_count < max_retries` (còn lượt sửa) và lỗi thuộc nhóm có thể khắc phục được. | Chuyển `error_message` sang **`One bounded retry (LLM + error message)`** để LLM viết lại SQL đúng. |
| **`"abstain"`** | - Đã sử dụng hết lượt thử lại (`retry_count >= max_retries`), HOẶC<br>- Gặp lỗi hệ thống nghiêm trọng không thể khắc phục (mất file db, tràn RAM). | Chuyển sang **`Abstain if unresolved`** (chấp nhận bỏ qua câu hỏi để bảo vệ điểm phạt). |

---

### 3.3. Phân Loại Mã Lỗi (`error_type`)

Engine tự động ánh xạ ngoại lệ từ DuckDB và Sanitizer sang các nhóm lỗi chuẩn:

| Ngoại lệ gốc | Mã `error_type` | Khả năng khắc phục (`is_recoverable`) | Ý nghĩa & Hướng xử lý |
| :--- | :---: | :---: | :--- |
| `duckdb.ParserException` | `SyntaxError` | **Có** (`True`) | Sai cú pháp SQL (sai từ khóa, thiếu dấu ngoặc). |
| `duckdb.CatalogException` | `CatalogError` | **Có** (`True`) | Bảng, cột hoặc hàm không tồn tại (DuckDB cung cấp gợi ý `Did you mean`). |
| `duckdb.BinderException` | `BinderError` | **Có** (`True`) | Xung đột kiểu dữ liệu, sai điều kiện `JOIN`, thiếu cột trong `GROUP BY`. |
| `duckdb.ConversionException` | `ConversionError` | **Có** (`True`) | Lỗi ép kiểu `CAST` hoặc sai format hàm ngày tháng `strptime`. |
| `duckdb.DataError` / `OutOfRangeException` | `DataError` | **Có** (`True`) | Chia cho 0 (`division by zero`), tràn số dữ liệu. |
| `QueryTimeoutError` / `InterruptException` | `TimeoutError` | **Có** (`True`) | Truy vấn quá thời gian (gợi ý LLM thêm điều kiện `WHERE`, bỏ Cartesian join). |
| `SecurityViolation` | `SecurityViolation` | **Có** (`True`) | Phát hiện lệnh cấm (`DROP`, `INSERT`, `COPY`, `read_csv`) hoặc multi-statement. |
| `EmptyQueryError` | `EmptyQueryError` | **Có** (`True`) | Câu truy vấn rỗng sau khi bóc tách markdown. |
| `FileNotFoundError` / `duckdb.IOException` | `DatabaseIOError` | **Không** (`False`) | Không tìm thấy file `.duckdb` từ loader. |
| `duckdb.OutOfMemoryException` | `OutOfMemoryError` | **Không** (`False`) | Vượt quá giới hạn bộ nhớ cấu hình. |

---

### 3.4. Chuẩn Hóa Kiểu Dữ Liệu (`normalize_value`)

Để đảm bảo kết quả trong trường `rows` an toàn 100% khi serialize ra JSON/JSONL ở các bước sau:

* `float('nan')`, `float('inf')`, `pd.NA`, `None` $\longrightarrow$ `None` (JSON `null`).
* `decimal.Decimal('1500000.00')` $\longrightarrow$ `1500000` (`int` nếu phần thập phân bằng 0).
* `decimal.Decimal('1500000.50')` $\longrightarrow$ `1500000.5` (`float`).
* `datetime.date(2025, 12, 1)` $\longrightarrow$ `"2025-12-01"` (chuỗi ISO-8601).
* `datetime.datetime(2025, 12, 1, 8, 30)` $\longrightarrow$ `"2025-12-01T08:30:00"`.
* `bytes` / `bytearray` $\longrightarrow$ Chuỗi UTF-8 hoặc hex.
* Mảng lồng nhau (`LIST`), cấu trúc (`STRUCT`) $\longrightarrow$ Đệ quy chuẩn hóa toàn bộ phần tử con.

---

## 4. Các Kịch Bản Thực Tế (Example Payloads)

### Kịch bản 1: Thực thi thành công (`route = "yes"`)

* **Input (`ExecutionRequest`):**
```json
{
  "question_id": "q_00eadfc5c599",
  "db_path": "cache/biz_104.duckdb",
  "sql_query": "```sql\nSELECT COUNT(DISTINCT \"Mã đơn hàng\") AS cnt FROM donhang WHERE \"Trạng thái đơn hàng\" = 'Đã hủy';\n```",
  "retry_count": 0,
  "max_retries": 1
}
```

* **Output (`ExecutionResponse`):**
```json
{
  "question_id": "q_00eadfc5c599",
  "is_valid": true,
  "route": "yes",
  "cleaned_sql": "SELECT COUNT(DISTINCT \"Mã đơn hàng\") AS cnt FROM donhang WHERE \"Trạng thái đơn hàng\" = 'Đã hủy'",
  "columns": ["cnt"],
  "rows": [
    {"cnt": 64}
  ],
  "row_count": 1,
  "error_type": null,
  "error_message": null,
  "execution_time_ms": 14.85
}
```

---

### Kịch bản 2: Lỗi tên cột ở lần chạy đầu (`route = "recoverable"`)

* **Input (`ExecutionRequest`):**
```json
{
  "question_id": "q_test_col_error",
  "db_path": "cache/biz_104.duckdb",
  "sql_query": "SELECT MaDonHang FROM donhang LIMIT 5",
  "retry_count": 0,
  "max_retries": 1
}
```

* **Output (`ExecutionResponse`):**
```json
{
  "question_id": "q_test_col_error",
  "is_valid": false,
  "route": "recoverable",
  "cleaned_sql": "SELECT MaDonHang FROM donhang LIMIT 5",
  "columns": null,
  "rows": null,
  "row_count": 0,
  "error_type": "BinderError",
  "error_message": "Binder Error: Referenced column \"MaDonHang\" not found in FROM clause!\nCandidate bindings: \"Mã đơn hàng\"\n\nLINE 1: SELECT MaDonHang FROM donhang LIMIT 5\n               ^^^^^^^^^",
  "execution_time_ms": 3.42
}
```
*(Gợi ý `Candidate bindings: "Mã đơn hàng"` sẽ được chuyển ngay vào LLM để sửa lại chính xác).*

---

### Kịch bản 3: Sửa lỗi thành công sau Retry (`retry_count = 1`, `route = "yes"`)

* **Input (`ExecutionRequest`):**
```json
{
  "question_id": "q_test_col_error",
  "db_path": "cache/biz_104.duckdb",
  "sql_query": "SELECT \"Mã đơn hàng\" FROM donhang LIMIT 1",
  "retry_count": 1,
  "max_retries": 1
}
```

* **Output (`ExecutionResponse`):**
```json
{
  "question_id": "q_test_col_error",
  "is_valid": true,
  "route": "yes",
  "cleaned_sql": "SELECT \"Mã đơn hàng\" FROM donhang LIMIT 1",
  "columns": ["Mã đơn hàng"],
  "rows": [
    {"Mã đơn hàng": "DH_10023"}
  ],
  "row_count": 1,
  "error_type": null,
  "error_message": null,
  "execution_time_ms": 2.15
}
```

---

### Kịch bản 4: Vẫn lỗi sau khi đã dùng hết lượt Retry (`route = "abstain"`)

* **Input (`ExecutionRequest`):**
```json
{
  "question_id": "q_test_failed_retry",
  "db_path": "cache/biz_104.duckdb",
  "sql_query": "SELECT * FROM non_existent_table",
  "retry_count": 1,
  "max_retries": 1
}
```

* **Output (`ExecutionResponse`):**
```json
{
  "question_id": "q_test_failed_retry",
  "is_valid": false,
  "route": "abstain",
  "cleaned_sql": "SELECT * FROM non_existent_table",
  "columns": null,
  "rows": null,
  "row_count": 0,
  "error_type": "CatalogError",
  "error_message": "Catalog Error: Table with name non_existent_table does not exist!",
  "execution_time_ms": 1.82
}
```

---

### Kịch bản 5: Chặn hành vi vi phạm bảo mật (`SecurityViolation`)

* **Input (`ExecutionRequest`):**
```json
{
  "question_id": "q_hack_attempt",
  "db_path": "cache/biz_104.duckdb",
  "sql_query": "DROP TABLE donhang;",
  "retry_count": 0,
  "max_retries": 1
}
```

* **Output (`ExecutionResponse`):**
```json
{
  "question_id": "q_hack_attempt",
  "is_valid": false,
  "route": "recoverable",
  "cleaned_sql": "DROP TABLE donhang",
  "columns": null,
  "rows": null,
  "row_count": 0,
  "error_type": "SecurityViolation",
  "error_message": "Security Violation: Forbidden SQL operation 'drop' detected.. Only single read-only SELECT queries are permitted.",
  "execution_time_ms": 0.45
}
```

---

### Kịch bản 6: Tự động ngắt truy vấn quá thời gian (`TimeoutError`)

* **Input (`ExecutionRequest`):**
```json
{
  "question_id": "q_slow_cartesian",
  "db_path": "cache/biz_104.duckdb",
  "sql_query": "WITH RECURSIVE inf(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM inf) SELECT COUNT(*) FROM inf;",
  "retry_count": 0,
  "max_retries": 1,
  "timeout_sec": 1.0
}
```

* **Output (`ExecutionResponse`):**
```json
{
  "question_id": "q_slow_cartesian",
  "is_valid": false,
  "route": "recoverable",
  "cleaned_sql": "WITH RECURSIVE inf(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM inf) SELECT COUNT(*) FROM inf",
  "columns": null,
  "rows": null,
  "row_count": 0,
  "error_type": "TimeoutError",
  "error_message": "Query execution timed out after 1.0s. Please optimize your SQL query (e.g. check for Cartesian joins, missing WHERE clauses, or excessive recursion).",
  "execution_time_ms": 1012.35
}
```

---

## 5. Hướng Dẫn Tích Hợp Vào Toàn Pipeline (Code Integration)

Đoạn mã mẫu sau minh họa cách các module khác (`B0.3`, `B0.4`, `B0.5`, `One bounded retry`) phối hợp với nhau trong file thực thi pipeline chính:

```python
from src.b0_4_executor import ExecutionRequest, execute_query

def run_pipeline_step(question_id: str, db_path: str, generated_sql: str, answer_type: str):
    # Bước 1: Gửi yêu cầu thực thi lần đầu (retry_count=0)
    req = ExecutionRequest(
        question_id=question_id,
        db_path=db_path,
        sql_query=generated_sql,
        answer_type=answer_type,
        retry_count=0,
        max_retries=1,
        timeout_sec=10.0
    )
    res = execute_query(req)

    # Bước 2: Điều hướng kết quả dựa trên trường `route`
    if res.route == "yes":
        # Nhánh YES: Chuyển dữ liệu sang B0.5 Format/Gate
        print(f"[{question_id}] Thành công! Gửi {res.row_count} dòng sang B0.5.")
        return format_answer(res.rows, answer_type)

    elif res.route == "recoverable":
        # Nhánh RECOVERABLE: Gửi thông báo lỗi sang LLM Retry
        print(f"[{question_id}] Lỗi {res.error_type}! Gửi lỗi sang One bounded retry:\n{res.error_message}")
        corrected_sql = llm_retry_prompt(generated_sql, res.error_message)

        # Chạy lại với retry_count=1
        retry_req = ExecutionRequest(
            question_id=question_id,
            db_path=db_path,
            sql_query=corrected_sql,
            answer_type=answer_type,
            retry_count=1,
            max_retries=1
        )
        retry_res = execute_query(retry_req)
        
        if retry_res.route == "yes":
            return format_answer(retry_res.rows, answer_type)
        else:
            return abstain_answer(question_id)

    else:
        # Nhánh ABSTAIN: Lỗi không thể khắc phục hoặc đã hết lượt
        print(f"[{question_id}] Abstain câu hỏi do lỗi: {res.error_message}")
        return abstain_answer(question_id)
```

