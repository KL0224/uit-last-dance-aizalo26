# Giải Thích Mã Nguồn: `retry.py`
**Đường dẫn file:** `src/datamate/b05/retry.py`  
**Thuộc module:** B0.5 Basic Output Gate  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

File `retry.py` là **Bộ điều khiển máy trạng thái sửa lỗi có chặn (Bounded Retry Controller & Error Classifier)**.

Trong sơ đồ kiến trúc Baseline B0 (HÌNH 10), khi câu lệnh SQL gặp lỗi, hệ thống không bỏ cuộc ngay mà cho phép:
> *"One bounded retry: Lỗi có thể sửa cho retry tối đa một lần, còn thất bại hoặc lỗi không sửa được thì Abstain."*

File `retry.py` đảm nhiệm 2 công việc quan trọng:
1. **Phân tích lỗi**: Xem lỗi này là do sai cú pháp/sai tên cột (sửa được) hay lỗi hệ thống/bảo mật (không nên sửa).
2. **Quyết định Retry**: Tạo ra gói chỉ dẫn `RepairRequest` và kiểm soát biến đếm `attempt` để **tuyệt đối không retry quá 1 lần**.

---

## 2. Chi Tiết Các Hàm

### 2.1. `classify_error(error_detail, validation_error_code) -> ErrorClassification`
Hàm nhận vào chi tiết lỗi từ DuckDB Executor và mã lỗi từ Validator để phân loại:

* **Trường hợp lỗi từ DuckDB (`error_detail != None`)**:
  * Phân tích chuỗi lỗi kết hợp giữa `error.type` và `error.message` (đồng bộ hoàn toàn với 9 loại lỗi có thể phục hồi của B0.4 / B1.4):
    * **Bảo vệ chống False-Positive `SECURITY_VIOLATION`**: Kiểm tra cờ `is_known_recoverable_type` (`binder`, `catalog`, `parser`, `syntax`, `conversion`, `dataerror`, `emptyquery`, `emptyresultwarning`). Chỉ gán `SECURITY_VIOLATION` (`retryable = False`) khi `error.type` là lỗi bảo mật/quyền hạn (`security`, `permission`) hoặc khi không phải các lỗi phục hồi đã biết mà `error.message` chứa từ khóa cấm (`"forbidden"`, `"drop "`, `"delete "`, `"update "`, `"insert "`, `"read-only"`). Nhờ đó, các câu SQL hợp lệ có điều kiện lọc `WHERE status = 'update record'` khi gặp `BinderError` (do DuckDB echo lại câu SQL trong thông báo lỗi) vẫn được phép retry.
    * **Hỗ trợ `EmptyResultWarning` từ B0.4**: Khi `error.type` là `EmptyResultWarning` (hoặc `error.message` chứa `"all null values"` do truy vấn `SUM`/`AVG` ở Attempt 0 trả về 1 dòng toàn `NULL`), gán mã `NULL_RESULT` với `retryable = True` và hướng dẫn LLM kiểm tra lại điều kiện lọc `WHERE` (dấu tiếng Việt hoặc định dạng ngày tháng).
    * **Ưu tiên `ConversionError` & `DataError`**: Khi `error.type` là `ConversionError` hoặc `DataError`, gán ngay `SQL_TYPE_ERROR` (`retryable = True`) trước khi quét từ khóa `"column"` trong message (kể cả khi B0.4 đính kèm `[Gợi ý Schema thực tế trong DB]`).
    * Chứa `"binder"`, `"catalog"`, `"not found"`, `"column"`, `"unknown table"`: Gán `SCHEMA_ERROR`, `retryable = True`. Phản hồi: *"Reinspect exact available column and table names from schema."*
    * Chứa `"parser"`, `"syntax"`, `"emptyquery"`: Gán `SQL_SYNTAX`, `retryable = True`. Phản hồi: *"Fix SQL syntax error to match valid dialect."*
    * Chứa `"cast"`, `"type mismatch"`, `"conversion"`, `"out of range"`, `"invalid input"`: Gán `SQL_TYPE_ERROR`, `retryable = True`.
    * Chứa `"timeout"`, `"deadline"`, `"time limit"`: Gán `QUERY_TIMEOUT`, `retryable = False`.
    * Lỗi khác: Gán `EXECUTOR_FAILURE`, `retryable = False`.
* **Trường hợp lỗi từ Validator (`validation_error_code != None`)**:
  * `SCALAR_SHAPE_MISMATCH`: `retryable = True`. Phản hồi: *"Add aggregate function or appropriate GROUP BY / LIMIT to return exactly 1 row and 1 column."*
  * `OUTPUT_TYPE_ERROR`: `retryable = True`.
  * Các lỗi khác (`EMPTY_RESULT`, `NULL_RESULT`, `TRUNCATED_RESULT`, `TABLE_SHAPE_ERROR`): `retryable = False`.

---

### 2.2. `decide_retry(request, classification) -> Optional[RepairRequest]`
Bộ điều phối logic máy trạng thái (State Machine):

```python
# Bất biến cốt lõi: Nếu attempt >= 1 thì khóa retry
if request.attempt >= 1:
    return None

if not classification.retryable:
    return None
```

* Nếu thỏa mãn điều kiện retry (`attempt == 0` và `retryable == True`):
  * Đóng gói đối tượng `RepairRequest`:
    * `attempt = 1`: Đánh dấu lượt thử kế tiếp là lượt cuối cùng.
    * `failed_sql`: Câu lệnh SQL đã gây ra lỗi.
    * `error_code`, `error_type`, `error_message`: Chi tiết lỗi cụ thể.
    * `schema_hint`: Lời nhắc định hướng để B0.3 biết cần sửa cái gì.
    * `do_not_change_question = True`: Nhắc B0.3 giữ nguyên ngữ nghĩa câu hỏi.
* Nếu không thỏa mãn: Trả về `None` (báo hiệu cho `gate.py` chuyển sang `abstain`).

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Chống vòng lặp vô tận (Infinite Loop Prevention)**:
   * Nếu không kiểm tra `request.attempt >= 1`, LLM có thể sinh sai SQL liên tục, B0.5 lại yêu cầu retry liên tục, làm tiêu tốn sạch token và treo cứng pipeline thi đấu.
   * Ràng buộc này đảm bảo một câu hỏi chỉ tốn **tối đa 2 lần gọi LLM** (1 lần tạo ban đầu + 1 lần sửa).
2. **"Safe Feedback" thay vì đẩy toàn bộ lỗi thô**:
   * Khi DuckDB báo lỗi dài hàng trăm dòng chứa cả stack trace C++, việc nhồi toàn bộ vào prompt cho LLM sẽ làm loãng ngữ cảnh và tốn token. `classify_error()` chắt lọc ra các thông điệp ngắn gọn (`safe_feedback`) giúp LLM tập trung vào đúng chỗ sai (ví dụ: kiểm tra lại tên cột).
3. **Chặn đứng nguy cơ tấn công qua SQL**:
   * Nếu câu lệnh có chứa `DROP TABLE` hoặc can thiệp dữ liệu, việc cấm retry lập tức ngăn chặn LLM thử các biến thể bypass bảo mật khác.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các File Khác

* **Được gọi bởi `gate.py`**: Khi `validators.py` báo kết quả không hợp lệ, `gate.py` gọi ngay `classify_error()` và `decide_retry()`.
* **Phát tín hiệu cho Orchestrator**: Khi hàm trả về `RepairRequest`, `gate.py` sẽ phát ra `GateOutcome(action="RETRY", repair_request=...)` để Orchestrator gọi lại B0.3.
* **Cung cấp dữ liệu cho `audit.py`**: Ghi vết xem câu hỏi đã được sửa thành công ở attempt nào và nguyên nhân lỗi trước đó là gì.

---

## 5. Nếu Không Có File Này Thì Sao?

* Baseline B0 sẽ mất đi tính năng "tự sửa sai" (Self-debugging). Mọi câu SQL dù chỉ gõ nhầm 1 chữ cái trong tên cột cũng sẽ bị bỏ cuộc ngay lập tức, làm sụt giảm nghiêm trọng tỷ lệ trả lời đúng và điểm PA.
* Hoặc ngược lại, nếu retry không có kiểm soát, hệ thống sẽ bị treo máy chủ vì vòng lặp vô hạn.

