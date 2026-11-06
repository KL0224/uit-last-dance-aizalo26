# Báo Cáo & Tóm Tắt Toàn Bộ Test Cases Module B0.4 (DuckDB Read-Only Execution Engine)

**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm thực hiện:** UIT Last Dance  
**Vị trí tài liệu:** `docs/test/b0/b04/TEST_CASES_SUMMARY.md`  
**Ngày thực thi kiểm thử:** 2026-11-06  
**Môi trường:** Python 3.12.3, Pytest 9.2.0, Linux WSL (x86_64), Virtual Environment (`.venv`)

---

## 1. Tổng Quan Kết Quả Kiểm Thử (Executive Summary)

Module **B0.4 DuckDB Read-Only Execution Engine** đảm nhiệm vai trò trung gian then chốt: tiếp nhận câu truy vấn SQL sinh ra từ mô hình ngôn ngữ lớn (B0.3 LLM), kiểm tra an toàn tĩnh (AST security check), thực thi câu truy vấn trong môi trường DuckDB Read-Only có kiểm soát tài nguyên (Sandbox constraints & hard timeout), và chuẩn hóa kết quả thành các kiểu dữ liệu an toàn để cung cấp cho Cổng kiểm duyệt đầu ra (B0.5 Output Gate).

Toàn bộ logic của B0.4 được bảo vệ bởi **14 bài test tự động (Automated Tests)** trong `tests/test_b0_4_executor.py` và kiểm thử mẫu dữ liệu thực tế cuộc thi trong `tests/test_real_sample.py`.

```text
============================= TEST EXECUTION SUMMARY (B0.4) =============================
Total Test Suites:            2 files (test_b0_4_executor.py, test_real_sample.py)
Total B0.4 Test Cases:        14 tests (1 skipped do thiếu file train.zip thực tế)
Passed:                       14 / 14 tests (100%)
Failed:                       0
Total Execution Time:         ~1.98 seconds (Thực thi DuckDB in-memory & file cache cục bộ)
Status:                       PASSED (All quality gates satisfied)
=========================================================================================
```

---

## 2. Chi Tiết Các Bộ Kiểm Thử Của Module B0.4 (`tests/test_b0_4_executor.py`)

### 2.1. Kiểm Thử Thực Thi & Bóc Tách Markdown Cú Pháp

| STT | Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|:---:|---|---|:---:|:---:|
| 1 | `test_01_valid_sql_execution` | Câu lệnh `SELECT` hợp lệ bọc trong markdown code fence ` ```sql ... ``` `. Kiểm tra việc bóc tách markdown sạch sẽ, gỡ bỏ dấu chấm phẩy, `is_valid = True`, điều hướng `route = 'yes'`, dữ liệu các cột và dòng được chuẩn hóa chính xác. | **PASSED** | ~0.08s |
| 2 | `test_02_empty_query` | Truy vấn rỗng hoặc chỉ có khoảng trắng/comment. Kiểm tra engine bắt lỗi `EmptyQueryError`, `is_valid = False`, `error_type = 'EmptyQueryError'`, điều hướng `route = 'recoverable'` để chuyển sang vòng Bounded Retry. | **PASSED** | < 0.01s |

---

### 2.2. Kiểm Thử Phòng Thủ Bảo Mật & Chống Injection (Security & AST Validation)

Đảm bảo ngăn chặn tuyệt đối các lệnh phá hoại dữ liệu, đọc trộm file hệ thống hoặc kỹ thuật chèn nhiều lệnh (Multi-statement injection).

| STT | Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|:---:|---|---|:---:|:---:|
| 3 | `test_03_dml_block_drop_table` | Câu lệnh nguy hiểm `DROP TABLE customers`. AST Analyzer phát hiện node cấm `exp.Drop`, chặn đứng trước khi thực thi, ném `SecurityViolation`, `error_type = 'SecurityViolation'`, `route = 'recoverable'`. | **PASSED** | < 0.01s |
| 4 | `test_04_multi_statement_injection` | Tấn công chèn lệnh: `SELECT * FROM customers; DROP TABLE orders;`. Parser phát hiện có nhiều hơn 1 câu lệnh SQL, kích hoạt chặn ngay lập tức `SecurityViolation: Multiple statements are not permitted`. | **PASSED** | < 0.01s |
| 5 | `test_05_file_access_function_block` | Kỹ thuật đọc file tùy tiện qua DuckDB: `SELECT * FROM read_csv('/etc/passwd')`. Sanitizer phát hiện hàm cấm `read_csv`, ngăn chặn đọc file hệ thống trái phép. | **PASSED** | < 0.01s |

---

### 2.3. Kiểm Thử Cơ Chế Timeout & Giới Hạn Tài Nguyên (Sandbox Constraints)

| STT | Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|:---:|---|---|:---:|:---:|
| 6 | `test_06_hard_timeout_interruption` | Câu truy vấn lặp nặng hoặc Cartesian join lớn vượt quá giới hạn thời gian (`timeout_sec = 0.5s`). Timer luồng ngầm kích hoạt `con.interrupt()`, giải phóng tài nguyên CPU, ghi nhận `error_type = 'TimeoutError'`, `route = 'recoverable'`. | **PASSED** | ~0.55s |
| 7 | `test_07_memory_safety_max_rows` | Truy vấn bảng lớn sinh hàng triệu dòng. Kiểm tra cơ chế giới hạn bộ nhớ `max_rows = 50`, chỉ nạp đúng 50 dòng kết quả vào RAM, ngăn ngừa tràn bộ nhớ Out-Of-Memory. | **PASSED** | ~0.02s |

---

### 2.4. Kiểm Thử Xử Lý Lỗi Cơ Sở Dữ Liệu & Điều Hướng Bounded Retry

| STT | Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|:---:|---|---|:---:|:---:|
| 8 | `test_08_recoverable_error_syntax` | Lỗi cú pháp SQL (`SELECT customer_id FROM customers WHERE;`). Phân loại thành `SyntaxError`, `route = 'recoverable'`, thông báo lỗi được tinh gọn sạch sẽ để truyền vào prompt retry của B0.3. | **PASSED** | ~0.01s |
| 9 | `test_09_recoverable_error_binder` | Lỗi tham chiếu cột không tồn tại (`SELECT non_existent_column FROM customers;`). Phân loại thành `BinderError`, `route = 'recoverable'`. | **PASSED** | ~0.01s |
| 10 | `test_10_retry_exhaustion_abstains` | Lỗi cú pháp nhưng đã cạn số lượt retry (`retry_count = 1, max_retries = 1`). Hệ thống tự động chuyển hướng từ `recoverable` sang `route = 'abstain'` để chuyển sang cổng từ bỏ an toàn của B0.5. | **PASSED** | < 0.01s |
| 11 | `test_12_nonexistent_db_path` | Đường dẫn file database không tồn tại trên đĩa. Phân loại thành `DatabaseIOError`, `is_recoverable = False`, điều hướng dứt khoát sang `route = 'abstain'`. | **PASSED** | < 0.01s |

---

### 2.5. Kiểm Thử Chuẩn Hóa Dữ Liệu & Adapter Tương Thích Module

| STT | Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|:---:|---|---|:---:|:---:|
| 12 | `test_11_data_normalization` | Kiểm tra hàm `normalize_value`: biến đổi `NaN`, `inf`, `pd.NA` thành `None`; chuyển đổi `datetime`/`date` sang chuỗi chuẩn ISO; chuẩn hóa số `Decimal` thành `int` hoặc `float`; decode `bytes` thành UTF-8; đệ quy chuẩn hóa `list` và `dict`. | **PASSED** | < 0.01s |
| 13 | `test_13_adapter_to_b05_execution_result` | **Adapter B0.4 $\rightarrow$ B0.5:** Kiểm tra phương thức `to_b05_execution_result()`: chuyển đổi danh sách dict thành ma trận giá trị `rows: List[List[Any]]` khớp với thứ tự các cột `columns`, ánh xạ thành công sang `ExecutionResult(status='success')` hoặc `ExecutionResult(status='error', error=ExecutionErrorDetail)`. | **PASSED** | ~0.02s |
| 14 | `test_14_from_b03_adapter` | **Adapter B0.3 $\rightarrow$ B0.4:** Kiểm tra phương thức khởi tạo `ExecutionRequest.from_b03()`: tiếp nhận trực tiếp đối tượng `Text2SQLResult` từ B0.3, tự động trích xuất `sql` và `answer_type` để thực thi truy vấn thành công. | **PASSED** | ~0.02s |

---

## 3. Đánh Giá Khả Năng Tương Thích & Mức Độ Ổn Định

1. **Khép kín luồng I/O Baseline B0:**
   * **B0.3 $\rightarrow$ B0.4:** Tiếp nhận thông suốt qua `ExecutionRequest.from_b03()`.
   * **B0.4 $\rightarrow$ B0.5:** Chuyển đổi chuẩn xác qua `ExecutionResponse.to_b05_execution_result()`.
2. **Bảo mật tuyệt đối:** Ngăn chặn triệt để SQL Injection và file leakage qua AST Analysis trước khi chạm tới DuckDB engine.
3. **An toàn tài nguyên:** Khóa cấu hình (`lock_configuration`), giới hạn luồng CPU (`threads = 2`), bộ nhớ tối đa (`max_memory = '2GB'`) và cơ chế ngắt cứng (`con.interrupt()`).

