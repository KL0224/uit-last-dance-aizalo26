# Báo Cáo Thay Đổi & Hồ Sơ Quyết Định Kiến Trúc (ADR-011): Đồng Bộ Tương Thích Giữa B0.4 (`b1-4-executor_minh`), B0.3, B0.5 Gate Và `B0Pipeline`

> **Tài liệu:** `docs/change/B04_B05_PIPELINE_COMPATIBILITY_CHANGELOG.md`  
> **Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
> **Nhánh hợp nhất:** `origin/feature/b1-4-executor_minh` $\rightarrow$ `dev`  
> **Phạm vi tác động:** `src/datamate/b0/b04/`, `src/datamate/b0/b05/retry.py`, `src/datamate/b0/pipeline.py`, `tests/test_b04_b05_pipeline_compatibility.py`  
> **Trạng thái:** **Accepted & Verified (345 passed, 3 skipped)**

---

## 1. Bối Cảnh & Những Thay Đổi Từ Nhánh `origin/feature/b1-4-executor_minh`

Khi hợp nhất nhánh `origin/feature/b1-4-executor_minh` (commit `6db8ffd`) vào `dev`, tầng thực thi **B0.4 / B1.4 (`src/datamate/b0/b04/`)** được nâng cấp 5 tính năng trọng tâm:

1. **Sanitizer AST-First & Che mặt nạ Literal (`src/datamate/b0/b04/sanitizer.py`)**:
   - Phân tích AST bằng `sqlglot` trước khi quét regex, và xóa bỏ các chuỗi trong dấu nháy đơn `'...'`, nháy kép `"..."` cùng comment (`_mask_literals_and_comments`, `_strip_literals_and_comments`) để không chặn nhầm các truy vấn lọc chuỗi nhạy cảm như `WHERE trang_thai = 'update'`.
   - Bóc tách khối markdown cuối cùng (`re.findall` lấy `matches[-1]`) và xóa `<think>...</think>` cũng như comment sau dấu `;`.
2. **Đính kèm Schema Hint Tự Động Khi Gặp Lỗi Schema/Cast (`src/datamate/b0/b04/error_handler.py`)**:
   - Bổ sung hàm `enrich_error_with_schema(con, error_type, base_msg)`: tự động truy vấn `SHOW TABLES` và `DESCRIBE` (loại bỏ các cột nội bộ `__dm_*` của B0.1) để nối khối `[Gợi ý Schema thực tế trong DB]:` vào cuối `error_message` khi gặp `CatalogError`, `BinderError`, hoặc `ConversionError`.
3. **Phát Hiện Kết Quả `SUM`/`AVG` Toàn `NULL` Ở Attempt 0 (`src/datamate/b0/b04/engine.py`)**:
   - Khi `retry_count < max_retries` và `answer_type in ("number", "percent")` mà kết quả trả về đúng 1 dòng với toàn bộ giá trị là `None`, B0.4 phát ra `ExecutionResponse(is_valid=False, route="recoverable", error_type="EmptyResultWarning", ...)` để yêu cầu LLM kiểm tra lại điều kiện lọc `WHERE`.
4. **Sandbox Tương Thích Docker Read-Only (`src/datamate/b0/b04/engine.py`, `Dockerfile`, `entrypoint.sh`)**:
   - Khởi tạo thư mục tạm `/tmp/duckdb_spill` và thiết lập `SET temp_directory = '/tmp/duckdb_spill'` trước khi khóa cấu hình (`SET lock_configuration = true`).
5. **Cache Thư Mục Dữ Liệu Thô (`_get_or_build_cached_dir_db` trong `src/datamate/b0/b04/engine.py`)**:
   - Tự động đóng gói thư mục CSV/Parquet/Excel/JSON thành file `.duckdb` tạm trong `/tmp/duckdb_dir_cache/b04_dir_<hash>.duckdb` ở lần gọi đầu tiên.

---

## 2. Phát Hiện Các Điểm Lệch Hợp Đồng Giữa B0.4 Và B0.5 / B0.3

Sau khi kiểm toán toàn tuyến từ **B0.1 $\rightarrow$ B0.2 $\rightarrow$ Grounding $\rightarrow$ B0.3 $\rightarrow$ B0.4 $\rightarrow$ B0.5 (`B0Pipeline`)**, chúng tôi phát hiện **3 điểm lệch hợp đồng nghiêm trọng** khiến các cải tiến mới của B0.4 bị vô hiệu hóa khi chạy End-to-End qua cổng B0.5:

| STT | Điểm lệch hợp đồng | Vị trí phát sinh | Hậu quả nếu không sửa |
| :--- | :--- | :--- | :--- |
| **1** | **`EmptyResultWarning` bị B0.5 đánh rơi thành `EXECUTOR_FAILURE` (`retryable=False`)** | [`src/datamate/b0/b05/retry.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py) | Khi B0.4 trả về `error_type="EmptyResultWarning"` (`route="recoverable"`), hàm `classify_error()` của B0.5 không nhận diện được tên lỗi này nên rơi xuống nhánh mặc định `ErrorCode.EXECUTOR_FAILURE` với `retryable=False`. Cổng B0.5 lập tức trả về `ABSTAIN` ngay ở Attempt 0 thay vì kích hoạt `RETRY`! |
| **2** | **False-Positive `SECURITY_VIOLATION` ở B0.5 khi DuckDB echo câu SQL chứa `'update '` / `'delete '`** | [`src/datamate/b0/b05/retry.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py) | Dù B0.4 đã cho phép `WHERE status = 'update record'`, nhưng nếu câu SQL đó bị gõ sai tên cột (`BinderError`), thông báo lỗi của DuckDB sẽ in lại dòng `LINE 1: SELECT wrong_col ... WHERE status = 'update record'`. Hàm `classify_error()` của B0.5 quét chuỗi `"update "` trên toàn bộ `err_msg` trước khi kiểm tra `BinderError`, dẫn đến gán nhầm thành `SECURITY_VIOLATION` (`retryable=False`) và khóa quyền retry! |
| **3** | **`ConversionError` bị gán nhầm thành `SCHEMA_ERROR` & `ExecutionRequest.from_b03` chưa chuẩn hóa alias `answer_type`** | [`src/datamate/b0/b05/retry.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py) & [`src/datamate/b0/b04/schemas.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/schemas.py) | `ConversionError` có chứa từ `"column"` bị phân loại vào `SCHEMA_ERROR` thay vì `SQL_TYPE_ERROR`. Ngoài ra, `ExecutionRequest.from_b03` lấy trực tiếp `b03_result.answer_type` mà chưa chuẩn hóa các alias (`"money"`, `"int"`, `"float"` $\rightarrow$ `"number"`), khiến kiểm tra `is_all_null_agg` không kích hoạt khi gọi trực tiếp qua `from_b03`. |

---

## 3. Chi Tiết Các Thay Đổi Đồng Bộ Đã Triển Khai

### 3.1. Đồng Bộ Bộ Phân Loại Lỗi `classify_error` Trong B0.5 (`src/datamate/b0/b05/retry.py`)
1. **Bảo vệ các lỗi phục hồi đã biết khỏi False-Positive Security (`is_known_recoverable_type`)**:
   - Xác định trước xem `error_detail.type` có thuộc tập lỗi phục hồi của B0.4 hay không (`binder`, `catalog`, `parser`, `syntax`, `conversion`, `dataerror`, `emptyquery`, `emptyresultwarning`).
   - Chỉ phân loại `ErrorCode.SECURITY_VIOLATION` (`retryable=False`) khi `"security" in err_type or "permission" in err_type`, hoặc khi `not is_known_recoverable_type` mà `err_msg` chứa từ khóa bảo mật.
2. **Nhận diện `EmptyResultWarning` để kích hoạt Bounded Retry ở Attempt 0**:
   - Khi `"emptyresultwarning" in err_type or "all null values" in err_msg`, hàm `classify_error()` trả về:
     - `code = ErrorCode.NULL_RESULT`
     - `retryable = True`
     - `safe_feedback = "Query returned NULL for aggregation. Check WHERE filter values (exact Vietnamese text or date format)."`
   - Khi sang Attempt 1 (`request.attempt >= 1`), nếu truy vấn vẫn trả về `[[None]]`, B0.4 cho phép kết quả đi qua (`route="yes"`) và `validate_execution()` của B0.5 chặn lại với `ErrorCode.NULL_RESULT` (`retryable=False`), kết thúc an toàn bằng `Decision.ABSTAIN` (`ErrorCode.RETRY_EXHAUSTED`).
3. **Ưu tiên `ConversionError` & `DataError` sang `ErrorCode.SQL_TYPE_ERROR`**:
   - Kiểm tra `"conversion" in err_type or "dataerror" in err_type` trước khối kiểm tra `"column" in err_msg` để bảo đảm lỗi ép kiểu (kể cả khi đính kèm `[Gợi ý Schema thực tế trong DB]`) luôn mang mã `ErrorCode.SQL_TYPE_ERROR` (`retryable=True`).

### 3.2. Đồng Bộ `ExecutionRequest.from_b03` Trong B0.4 (`src/datamate/b0/b04/schemas.py`)
- Trong `ExecutionRequest.from_b03()`, gọi `normalize_answer_type(ans_type, sql)` từ `datamate.b0.b03.parser` khi `ans_type is not None`. Nhờ đó, mọi alias kiểu số (`"money"`, `"int"`, `"float"`, `"count"`) đều được chuẩn hóa về `"number"` trước khi bước vào kiểm tra `is_all_null_agg` của B0.4.

---

## 4. Kiểm Chứng Bằng Bộ Test Tích Hợp (`tests/test_b04_b05_pipeline_compatibility.py`)

Đã bổ sung 5 kịch bản kiểm thử chuyên sâu trong [`tests/test_b04_b05_pipeline_compatibility.py`](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_b04_b05_pipeline_compatibility.py):
1. `test_b04_empty_result_warning_triggers_b05_bounded_retry`: Xác nhận `EmptyResultWarning` ở Attempt 0 kích hoạt `GateAction.RETRY` (`ErrorCode.NULL_RESULT`) tại cổng B0.5 và chuyển sang `Decision.ABSTAIN` (`ErrorCode.RETRY_EXHAUSTED`) nếu Attempt 1 vẫn toàn `NULL`.
2. `test_b05_binder_error_with_sensitive_sql_literal_is_not_blocked_as_security`: Xác nhận câu lệnh `SELECT wrong_column FROM customers WHERE status = 'update record'` khi gặp `BinderError` vẫn được B0.5 phân loại là `ErrorCode.SCHEMA_ERROR` (`retryable=True`) kèm `[Gợi ý Schema thực tế trong DB]`.
3. `test_b04_conversion_error_with_column_mention_maps_to_sql_type_error`: Xác nhận `ConversionError` có chứa tên cột và gợi ý schema được ánh xạ chính xác về `ErrorCode.SQL_TYPE_ERROR` (`retryable=True`).
4. `test_b04_from_b03_normalizes_answer_type_aliases_for_all_null_check`: Xác nhận `ExecutionRequest.from_b03` chuẩn hóa `answer_type="money"` thành `"number"` và kích hoạt `EmptyResultWarning`.
5. `test_b0_pipeline_e2e_recovers_from_all_null_aggregate_and_schema_hints`: Chạy `B0Pipeline` End-to-End (batch mode) chứng minh cả hai trường hợp (`EmptyResultWarning` do sai `WHERE` và `BinderError` có chứa `'update'` kèm Schema Hint) đều được sửa thành công ở Attempt 1 và không làm lộ cột nội bộ `__dm_*`.

