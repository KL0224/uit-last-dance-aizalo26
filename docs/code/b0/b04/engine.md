# Giải Thích Mã Nguồn: `engine.py` (B0.4)

**Đường dẫn file:** [`src/datamate/b0/b04/engine.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py)  
**Thuộc module:** B0.4 DuckDB Read-Only Execution Engine  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `engine.py` là **Bộ máy thực thi trung tâm (Execution Core)** của module B0.4. File này chịu trách nhiệm:
1. Kết nối tới DuckDB dưới các chế độ linh hoạt (In-memory, File cache `.duckdb`, hoặc nạp tự động thư mục file bảng thô).
2. Thiết lập môi trường Sandbox khắt khe: khóa cấu hình, giới hạn dung lượng RAM tối đa, giới hạn số luồng CPU và cấm truy cập file bên ngoài.
3. Cơ chế ngắt cứng Timeout bằng luồng Timer ngầm (`con.interrupt()`).
4. Thu thập kết quả và chuẩn hóa sang cấu trúc [`ExecutionResponse`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/schemas.md).

---

## 2. Chi Tiết Các Hàm Chức Năng

### 2.1. Hàm `_load_directory_into_duckdb(con, dir_path)` & `_get_or_build_cached_dir_db(dir_path)`
* `_load_directory_into_duckdb`: Quét toàn bộ các file bảng biểu trong một thư mục (`.parquet`, `.csv`, `.tsv`, `.json`, `.jsonl`, `.xlsx`, `.xls`) và tạo bảng trong DuckDB với tên đã chuẩn hóa SQL (`re.sub(r"[^a-zA-Z0-9_]", "_", stem)`).
* `_get_or_build_cached_dir_db`: Khi `db_path` là thư mục dữ liệu thô chưa có `data.duckdb`, hàm băm (`sha256`) đường dẫn tuyệt đối kèm `mtime_ns` và kích thước các file để khởi tạo và cache một file `.duckdb` tạm tại `/tmp/duckdb_dir_cache/b04_dir_<hash>.duckdb` (an toàn đa luồng với `_DIR_CACHE_LOCK`). Các câu hỏi tiếp theo của cùng doanh nghiệp mở trực tiếp file cache ở chế độ `read_only=True`, tăng tốc độ thực thi 1.5x–2x.

### 2.2. Hàm `execute_query(request: ExecutionRequest) -> ExecutionResponse`
Đây là hàm thực thi truy vấn chính, trải qua 7 bước nghiêm ngặt:

1. **Bước 1: Phân tích an toàn tĩnh (Pre-execution Static Analysis):**
   * Gọi `validate_read_only_sql(request.sql_query)` từ `sanitizer.py`. Nếu có vi phạm bảo mật, quá trình dừng ngay trước khi chạm tới database.
2. **Bước 2: Khởi tạo kết nối DuckDB:**
   * Nếu `db_path == ":memory:"`: Mở database in-memory.
   * Nếu `os.path.isfile(db_path)`: Mở database với cờ `read_only = True`.
   * Nếu `os.path.isdir(db_path)`: Nếu có sẵn `data.duckdb` (bundle B0.1) thì mở trực tiếp `read_only = True`; nếu không thì mở file cache từ `_get_or_build_cached_dir_db(db_path)` (hoặc fallback in-memory).
   * Nếu không tồn tại: ném `FileNotFoundError`.
3. **Bước 3: Thiết lập rào chắn Sandbox tương thích Docker Read-Only:**
   * Khởi tạo thư mục tạm `/tmp/duckdb_spill` (hoặc biến môi trường `B04_DUCKDB_TEMP_DIR`) và gán `SET temp_directory = '/tmp/duckdb_spill'` để tránh lỗi `IOException` khi container Docker mount root filesystem `:ro`.
   * `SET max_memory = '4GB'` (cấu hình qua `B04_DUCKDB_MAX_MEMORY`): Ngăn chặn các truy vấn join nhân bản dòng làm cạn kiệt RAM hệ thống.
   * `SET threads = 4` (cấu hình qua `B04_DUCKDB_THREADS`): Giới hạn tài nguyên CPU.
   * `SET enable_external_access = false` & `SET lock_configuration = true`: Vô hiệu hóa truy cập file ngoài và khóa chặt cấu hình.
4. **Bước 4: Thiết lập ngắt cứng Timeout bằng Timer Thread:**
   * Tạo `threading.Timer(request.timeout_sec, on_timeout)`.
   * Nếu hết thời gian, hàm `on_timeout` sẽ gọi `con.interrupt()` để hủy ngay lập tức tác vụ tính toán C++ của DuckDB.
5. **Bước 5: Thực thi câu lệnh SQL & lọc cột nội bộ B0.1:**
   * Chạy `cursor = con.execute(cleaned_sql)`.
   * Lấy tối đa `max_rows + 1` dòng bằng `cursor.fetchmany(request.max_rows + 1)` để phát hiện cờ `truncated`.
   * Tự động ẩn các cột lineage nội bộ của B0.1 bắt đầu bằng `__dm_` (như `__dm_row_id`) nếu câu lệnh dùng `SELECT *`.
6. **Bước 6: Chuẩn hóa dữ liệu trả về:**
   * Duyệt qua từng dòng, áp dụng `normalize_value(val)` cho từng ô giá trị.
7. **Bước 7: Kiểm tra kết quả rỗng / toàn `NULL` ở lần thử đầu (`EmptyResultWarning`):**
   * Nếu `request.retry_count < request.max_retries` (Attempt 0), `request.answer_type in ("number", "percent")` và kết quả trả về đúng 1 dòng nhưng tất cả các cột đều là `None` (`is_all_null_agg`), trả về `ExecutionResponse(is_valid=False, route="recoverable", error_type="EmptyResultWarning", ...)` để B0.5 kích hoạt One Bounded Retry nhắc LLM kiểm tra lại điều kiện lọc `WHERE`.
   * Ngược lại, trả về `ExecutionResponse(is_valid=True, route="yes", columns=columns, rows=rows, row_count=len(rows), truncated=truncated)`.

### 2.3. Xử lý ngoại lệ trong khối `except`
* Nếu có bất kỳ lỗi nào xảy ra:
  * Thu hồi câu SQL đã làm sạch để ghi log.
  * Gọi `classify_error(exc)` để phân loại lỗi và đánh giá khả năng retry.
  * Gọi `determine_route(...)` để quyết định `"recoverable"` hay `"abstain"`.
  * Gọi `format_error_message(...)` và `enrich_error_with_schema(con, error_type, error_message)` để đính kèm `[Gợi ý Schema thực tế trong DB]` khi gặp lỗi `CatalogError`, `BinderError`, hoặc `ConversionError`.
  * Trả về `ExecutionResponse(is_valid=False, route=route, error_type=error_type, error_message=error_message)`.
* **Khối `finally`:** Luôn luôn hủy timer (`timer.cancel()`) và đóng kết nối database (`con.close()`) để giải phóng con trỏ tài nguyên.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Tại sao phải dùng `con.interrupt()` thay vì `signal.alarm`?**
   * Cơ chế `signal.alarm` chỉ hoạt động trên luồng chính của Unix, không hoạt động trên Windows/WSL đa luồng và không thể ngắt các hàm C/C++ đang chạy blocking của DuckDB.
   * `con.interrupt()` là API chuyên dụng của DuckDB được thiết kế để ngắt an toàn các tác vụ tính toán song song từ một luồng khác mà không làm hỏng tiến trình Python.
2. **Tại sao phải dùng `fetchmany(max_rows)` thay vì `fetchall()`?**
   * Nếu mô hình LLM viết nhầm câu lệnh tạo Cartesian Join (nhân tích Descartes) sinh ra hàng chục triệu dòng, lệnh `fetchall()` sẽ kéo toàn bộ dữ liệu vào RAM, gây ra lỗi Linux OOM-Killer tắt ngấm tiến trình. `fetchmany` đảm bảo an toàn bộ nhớ tuyệt đối.

---

## 4. Tương Thích & Mối Liên Hệ

* Nhận yêu cầu từ [`ExecutionRequest`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/schemas.md).
* Sử dụng [`sanitizer.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/sanitizer.md) và [`error_handler.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/error_handler.md).
* Trả về [`ExecutionResponse`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/schemas.md), sẵn sàng chuyển đổi sang B0.5 Output Gate.

---

## 5. Nếu Không Có File Này Thì Sao?

* Pipeline không thể chạy câu truy vấn SQL để lấy kết quả số liệu thực tế từ cơ sở dữ liệu.
* Không có cơ chế bảo vệ máy chủ khỏi các câu truy vấn nặng gây treo máy hoặc tràn RAM.

