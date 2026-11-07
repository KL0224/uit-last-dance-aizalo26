# KẾ HOẠCH NÂNG CẤP TẦNG THỰC THI (MODULE B0.4) & QUY TRÌNH ĐÓNG GÓI DOCKER
**Dự án:** DataMate - Zalo AI Challenge 2026

* **Mục tiêu 1:** Rà soát các điểm nghẽn hiện tại trong code của Module B0.4 (DuckDB Read-Only Execution Engine).
* **Mục tiêu 2:** Đề xuất phương án sửa code cụ thể (Improvement Execute Layer Plan) để tránh mất điểm oan và hỗ trợ tốt hơn cho bước One Bounded Retry.
* **Mục tiêu 3:** Thống nhất quy trình từ lúc test trên GPU của Modal.ai sang đóng gói Docker Image nộp bài cho BTC.

---

## I. ĐÁNH GIÁ CODE HIỆN TẠI CỦA MODULE B0.4

Code hiện tại của B0.4 (gồm `schemas.py`, `sanitizer.py`, `error_handler.py`, `engine.py`) đã hoàn thiện tốt luồng cơ bản: có kiểm tra AST qua `sqlglot`, có ngắt timeout bằng `threading.Timer` + `con.interrupt()`, và chuẩn hóa đầu ra JSON-safe cho B0.5.

Tuy nhiên, khi chạy thực tế trên dữ liệu tiếng Việt và đóng gói vào môi trường Docker Read-Only của BTC, có 6 vấn đề cần xử lý:

| STT | File / Vị trí | Vấn đề hiện tại | Hướng xử lý |
| :---: | :--- | :--- | :--- |
| **1** | `sanitizer.py`<br>(dòng 89-98) | Quét regex từ khóa cấm (`update`, `create`, `delete`, `load`...) trên chuỗi SQL thô trước khi parse AST. Nếu câu truy vấn lọc chữ `'update'` trong chuỗi (VD: `WHERE status = 'update'`) sẽ bị chặn nhầm thành `SecurityViolation`. | Bỏ quét regex thô ở đầu. Dùng AST của `sqlglot` + kiểm tra `ALLOWED_ROOT_NODES`. Chỉ dùng regex khi `sqlglot` lỗi `ParseError` (sau khi đã xóa nội dung trong dấu nháy). |
| **2** | `engine.py`<br>(dòng 95-103) | Đã bật `lock_configuration = true` nhưng chưa gán `temp_directory`. Khi chạy Docker chấm thi (thư mục gốc bị khóa quyền ghi), nếu truy vấn nặng cần spill ra ổ cứng, DuckDB ghi vào `./.tmp` sẽ báo lỗi `IOException` -> bị đẩy sang nhánh `abstain`. | Thêm lệnh `SET temp_directory = '/tmp/duckdb_spill'` trước khi khóa cấu hình sandbox. |
| **3** | `error_handler.py`<br>& `engine.py` | Khi lỗi sai tên bảng/cột (`CatalogError`, `BinderError`), `error_message` chỉ trả về lỗi mặc định của DuckDB. Vì chỉ có đúng 1 lần retry (*One bounded retry*), LLM không biết bảng có những cột nào để sửa cho đúng. | Truy vấn nhanh `SHOW TABLES` và `DESCRIBE` ngay trong khối `except` của `engine.py` để đính kèm danh sách cột thực tế vào cuối `error_message`. |
| **4** | `sanitizer.py`<br>(dòng 68-77) | Dùng `re.search` lấy khối ```` ``` ```` đầu tiên và cắt dấu `;` ở cuối chuỗi. Nếu LLM sinh 2 khối markdown (khối 1 giải thích, khối 2 mới là SQL) hoặc có comment `--` sau dấu `;` thì bóc tách bị lỗi. | Dùng `re.findall` lấy khối ```` ```sql ```` cuối cùng; xóa comment trước khi cắt dấu `;`. |
| **5** | `engine.py`<br>(dòng 126-148) | Sơ đồ B0 yêu cầu kiểm tra `'SQL / result valid?'`, nhưng code hiện tại mới kiểm tra SQL chạy không lỗi. Nếu câu `SUM`/`AVG` lọc sai từ tiếng Việt trả về 1 dòng toàn giá trị `NULL`, code vẫn cho qua nhánh `'yes'`. | Nếu `retry_count == 0` mà kết quả trả về 0 dòng hoặc 1 dòng toàn `NULL`, chuyển sang `'recoverable'` để LLM kiểm tra lại điều kiện `WHERE`. |
| **6** | `engine.py`<br>(dòng 27-68) | Nếu `db_path` là thư mục chứa CSV/Excel, hàm `_load_directory_into_duckdb` nạp lại toàn bộ file vào `:memory:` ở mỗi câu hỏi, gây chậm I/O. | Cache thư mục thành file `.duckdb` tạm trong `/tmp` ở lần gọi đầu tiên. |

---

## II. CHI TIẾT KẾ HOẠCH NÂNG CẤP B0.4 (IMPROVEMENT EXECUTE LAYER PLAN)

### 1. Sửa bộ lọc bảo mật trong `sanitizer.py` (Tránh chặn nhầm câu SQL hợp lệ)

Trong file `sanitizer.py` hiện tại, biến `ALLOWED_ROOT_NODES` đã được khai báo ở dòng 52 nhưng chưa được gọi trong hàm `validate_read_only_sql()`. Kế hoạch sửa lại như sau:

* **Bước 1:** Trong `extract_clean_sql()`, dùng `re.findall()` để lấy khối code SQL cuối cùng nếu LLM trả về nhiều khối markdown. Xóa các comment dạng `--` và `/* */` ở cuối câu trước khi cắt dấu chấm phẩy `;`.
* **Bước 2:** Trong `validate_read_only_sql()`, đưa câu SQL vào `sqlglot.parse()` trước. Kiểm tra node gốc phải thuộc `ALLOWED_ROOT_NODES` (`Select`, `Union`, `Intersect`, `Except`).
* **Bước 3:** Nếu `sqlglot.parse()` báo `ParseError` (do cú pháp đặc thù của DuckDB), lúc này mới chạy regex quét từ khóa cấm, nhưng phải xóa sạch các chuỗi nằm trong dấu nháy đơn `'...'` và nháy kép `"..."` trước khi quét.

**Code mẫu cập nhật cho `sanitizer.py`:**

```python
def _strip_literals_and_comments(sql: str) -> str:
    sql = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"'(?:''|[^'])*'", "''", sql)
    sql = re.sub(r'"(?:""|[^"])*"', '""', sql)
    return sql.lower()


def extract_clean_sql(raw_sql: str) -> str:
    if not raw_sql or not raw_sql.strip():
        raise EmptyQueryError("SQL query is empty.")
    text = raw_sql.strip()
    matches = re.findall(r"```(?:sql)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    extracted = matches[-1].strip() if matches else text
    # Xóa comment ở cuối trước khi cắt dấu ';'
    extracted = re.sub(r"--[^\n]*$", "", extracted).strip()
    extracted = re.sub(r";+\s*$", "", extracted).strip()
    if not extracted:
        raise EmptyQueryError("SQL query is empty after stripping formatting.")
    return extracted


def validate_read_only_sql(sql: str) -> str:
    cleaned_sql = extract_clean_sql(sql)
    try:
        parsed_statements = sqlglot.parse(cleaned_sql, read="duckdb")
        valid_stmts = [s for s in parsed_statements if s is not None]
        if not valid_stmts:
            raise EmptyQueryError("No valid SQL statement found.")
        if len(valid_stmts) > 1:
            raise SecurityViolation("Multiple SQL statements detected.")
        stmt = valid_stmts[0]
        if not isinstance(stmt, ALLOWED_ROOT_NODES):
            raise SecurityViolation(f"Statement '{type(stmt).__name__}' is not allowed.")
        for node in stmt.walk():
            if isinstance(node, FORBIDDEN_AST_NODES):
                raise SecurityViolation(f"Forbidden operation '{type(node).__name__}'.")
            if isinstance(node, (exp.Func, exp.Anonymous, exp.Table)):
                name = (node.name or "").lower()
                if name in FORBIDDEN_FUNCTIONS or name.startswith("duckdb_"):
                    raise SecurityViolation(f"Forbidden function '{name}'.")
    except ParseError:
        masked_sql = _strip_literals_and_comments(cleaned_sql)
        for func in FORBIDDEN_FUNCTIONS:
            if re.search(rf"\b{func}\b", masked_sql):
                raise SecurityViolation(f"Forbidden function '{func}'.")
        for word in FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{word}\b", masked_sql):
                raise SecurityViolation(f"Forbidden keyword '{word}'.")
    return cleaned_sql
```

### 2. Cấu hình thư mục tạm cho DuckDB trong `engine.py` (Chống lỗi Read-Only trên Docker)

Khi container chạy trên hệ thống chấm bài của BTC, thư mục làm việc có thể bị khóa quyền ghi (Read-Only). Cần tạo sẵn thư mục `/tmp/duckdb_spill` và khai báo cho DuckDB trước khi khóa cấu hình:

```python
# Sửa Bước 3 trong hàm execute_query() của file engine.py:
os.makedirs("/tmp/duckdb_spill", exist_ok=True)
max_mem = os.getenv("B04_DUCKDB_MAX_MEMORY", "4GB")
threads = int(os.getenv("B04_DUCKDB_THREADS", "4"))

for config_sql in [
    "SET temp_directory = '/tmp/duckdb_spill'",
    f"SET max_memory = '{max_mem}'",
    f"SET threads = {threads}",
    "SET enable_external_access = false",
    "SET lock_configuration = true",
]:
    try:
        con.execute(config_sql)
    except Exception as conf_err:
        logger.debug("Sandbox setting ignored: %s", conf_err)
```

### 3. Bổ sung Schema Hint vào thông báo lỗi (Tăng hiệu quả cho One Bounded Retry)

Ở nhánh `'recoverable'`, LLM chỉ có 1 cơ hội sửa lại câu SQL dựa trên `error_message`. Nếu lỗi là `CatalogError` (sai tên bảng), `BinderError` (sai tên cột) hoặc `ConversionError` (ép kiểu sai), ta lấy trực tiếp danh sách bảng và cột từ kết nối DuckDB đang mở để đính kèm vào thông báo lỗi:

```python
# Thêm hàm này vào error_handler.py và gọi trong khối except của engine.py:
def enrich_error_with_schema(con, error_type: str, base_msg: str) -> str:
    if con is None or error_type not in ("CatalogError", "BinderError", "ConversionError"):
        return base_msg
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        if not tables:
            return base_msg
        hints = []
        for tbl in tables[:6]:
            cols = con.execute(f'DESCRIBE "{tbl}"').fetchall()
            col_list = ", ".join([f'"{c[0]}" ({c[1]})' for c in cols[:25]])
            hints.append(f'  * Bảng "{tbl}": {col_list}')
        return base_msg + "\n[Gợi ý Schema thực tế trong DB]:\n" + "\n".join(hints)
    except Exception:
        return base_msg
```

### 4. Kiểm tra kết quả rỗng / toàn NULL (Result Validation)

Sau khi fetch dữ liệu ở Bước 5 trong `engine.py`, nếu là lần chạy đầu tiên (`retry_count == 0`) mà gặp kết quả rỗng hoặc dòng duy nhất trả về toàn giá trị `None` (thường gặp khi dùng hàm `SUM`, `AVG`, `MIN`, `MAX` với điều kiện `WHERE` bị lệch từ khóa tiếng Việt), ta có thể chủ động đẩy sang nhánh `'recoverable'` để LLM kiểm tra lại điều kiện lọc:

```python
# Đặt sau bước chuẩn hóa rows trong engine.py:
is_all_null_agg = (
    len(rows) == 1
    and all(v is None for v in rows[0].values())
    and request.answer_type in ("number", "percent")
)

if request.retry_count < request.max_retries and is_all_null_agg:
    return ExecutionResponse(
        question_id=request.question_id,
        is_valid=False,
        route="recoverable",
        cleaned_sql=cleaned_sql,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        error_type="EmptyResultWarning",
        error_message="Query returned a single row with all NULL values. Please check your WHERE filter values (e.g., exact Vietnamese text matching or date format).",
        execution_time_ms=execution_time_ms,
    )
```

---

## III. QUY TRÌNH ĐÓNG GÓI DOCKER KẾT HỢP MODAL.AI

Sử dụng Modal.ai để chạy GPU (L4, A10, A100...), quy trình làm việc thuận tiện và ít rủi ro nhất là dùng chung một file `Dockerfile` cho cả việc chạy test trên Modal.ai và việc đóng gói nộp bài cuối cùng.

### Bước 1: Test riêng Module B0.4 ở máy cá nhân (Local CPU)
* B0.4 chỉ dùng CPU và RAM, không phụ thuộc GPU. Trước khi đẩy lên Modal, chạy `pytest` ngay trên máy local với các file `.duckdb` mẫu từ B0.1.
* Kiểm tra đủ các trường hợp: câu SQL đúng, câu SQL có chữ `'update'` trong điều kiện `WHERE`, câu SQL sai tên cột (xem `error_message` đã kèm Schema Hint chưa), câu SQL chạy quá timeout.

### Bước 2: Viết `Dockerfile` chuẩn cho toàn bộ Pipeline B0
Tạo file `Dockerfile` ở thư mục gốc của dự án:

```dockerfile
FROM pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    B04_DUCKDB_MAX_MEMORY="4GB" \
    B04_DUCKDB_THREADS="4"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    duckdb==1.1.3 sqlglot==25.29.0 pydantic>=2.7.0 \
    pandas>=2.2.0 openpyxl>=3.1.2 pyarrow>=16.0.0 \
    -r requirements.txt

RUN mkdir -p /tmp/duckdb_spill && chmod -R 777 /tmp/duckdb_spill

COPY src/ /workspace/src/
COPY configs/ /workspace/configs/
COPY run_b0_pipeline.py entrypoint.sh /workspace/

RUN sed -i 's/\r$//' /workspace/entrypoint.sh && chmod +x /workspace/entrypoint.sh

ENTRYPOINT ["/workspace/entrypoint.sh"]
```

### Bước 3: Chạy test Public Test trên GPU của Modal.ai từ `Dockerfile`
* Trong script chạy Modal của nhóm, thay vì cài thư viện bằng các hàm `pip_install` rời rạc, sử dụng trực tiếp: `modal.Image.from_dockerfile('Dockerfile')`.
* Khi test luồng code tích hợp (B0.1 -> B0.5), chọn GPU L4 (\$0.80/h) hoặc A10 (\$1.10/h) để tiết kiệm chi phí.
* Khi chạy toàn bộ tập Public Test để lấy file kết quả nộp thử và thu thập `error_logs.jsonl`, có thể chuyển sang A100 (\$2.10/h - \$2.50/h).
* Đảm bảo bật biến môi trường `HF_HUB_OFFLINE=1` khi chạy trên Modal để kiểm tra chắc chắn code không tự ý tải thêm dữ liệu từ Internet.

### Bước 4: Build Docker Image và chạy thử Offline trước khi nộp
Sau khi kiểm tra kết quả chạy trên Modal đã ổn định, tiến hành đóng gói và chạy thử container ở chế độ ngắt mạng hoàn toàn (`--network none`) và khóa quyền ghi thư mục dữ liệu đầu vào (`:ro`) giống hệt môi trường chấm thi của BTC:

```bash
# 1. Build Docker Image
docker build -t uit_last_dance_b0:v1.0 .

# 2. Chạy thử với tập Public Test (ngắt mạng + chỉ đọc thư mục input)
docker run --rm --gpus all --network none --shm-size=8g \
    -v "$(pwd)/public_test:/data/input:ro" \
    -v "$(pwd)/output:/data/output:rw" \
    uit_last_dance_b0:v1.0 \
    python3 /workspace/run_b0_pipeline.py --input_dir /data/input --output_dir /data/output

# 3. Xuất file nén để nộp (nếu BTC yêu cầu nộp file .tar.gz)
docker save uit_last_dance_b0:v1.0 | gzip > uit_last_dance_b0_v1.0.tar.gz
```

---

## IV. CHECKLIST (ACTION ITEMS)

* [ ] **Việc 1:** `[B0.4 - sanitizer.py]` Sửa lại hàm `extract_clean_sql` và `validate_read_only_sql` để không chặn nhầm từ khóa trong chuỗi lọc.
* [ ] **Việc 2:** `[B0.4 - engine.py]` Thêm `SET temp_directory = '/tmp/duckdb_spill'` vào cấu hình sandbox của DuckDB.
* [ ] **Việc 3:** `[B0.4 - error_handler.py]` Viết thêm hàm lấy danh sách bảng/cột từ DuckDB đính kèm vào `error_message` khi gặp lỗi `CatalogError`/`BinderError`.
* [ ] **Việc 4:** `[Docker & Modal]` Tạo `Dockerfile` chung ở thư mục gốc và cấu hình `modal.Image.from_dockerfile('Dockerfile')` để đồng bộ môi trường test GPU với môi trường nộp bài.