# Báo Cáo & Tóm Tắt Toàn Bộ Test Cases Module B0.3 (Text-to-SQL LLM Layer)

**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm thực hiện:** UIT Last Dance  
**Vị trí tài liệu:** `docs/test/b0/b03/TEST_CASES_SUMMARY.md`  
**Ngày thực thi kiểm thử:** 2026-11-06  
**Môi trường:** Python 3.12.3, Pytest 9.2.0, Linux WSL (x86_64), Virtual Environment (`.venv`)

---

## 1. Tổng Quan Kết Quả Kiểm Thử (Executive Summary)

Module **B0.3 Text-to-SQL LLM Layer** chịu trách nhiệm tiếp nhận ngữ cảnh kinh doanh (Business Context từ B0.2), thiết lập câu lệnh prompt tối ưu hóa cho mô hình ngôn ngữ lớn (Qwen3.5-9B / vLLM), sinh câu truy vấn SQL an toàn và bóc tách kết quả dạng JSON chuẩn tắc để cung cấp cho Tầng thực thi DuckDB (B0.4) và Cổng kiểm duyệt đầu ra (B0.5).

Toàn bộ logic của B0.3 được bảo vệ bởi **17 bài test tự động (Automated Tests)**, kiểm thử độc lập 100% offline, mô phỏng phản hồi LLM chính xác và xác nhận tương thích hoàn toàn giữa các tầng.

```text
============================= TEST EXECUTION SUMMARY (B0.3) =============================
Total Test Suites:            2 files (test_b03_modular_imports.py, test_b03_text2sql.py)
Total B0.3 Test Cases:        17 tests
Passed:                       17 / 17 tests (100%)
Failed:                       0
Skipped / XFailed:            0
Total Execution Time:         ~0.03 seconds (100% offline, zero-network, deterministic)
Status:                       PASSED (All quality gates satisfied)
=========================================================================================
```

---

## 2. Chi Tiết Các Bộ Kiểm Thử Của Module B0.3

### 2.1. Kiểm Thử Public API, Kiểu Dữ Liệu & Ràng Buộc Cơ Bản (`test_b03_modular_imports.py`)

Bộ kiểm thử đảm bảo việc đóng gói package `datamate.b0.b03` hoàn toàn cô lập với runtime GPU, không gây lỗi khi import trên máy không có vLLM/CUDA, và kiểm soát nghiêm ngặt tính bất biến của các đối tượng dữ liệu.

| STT | Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|:---:|---|---|:---:|:---:|
| 1 | `test_b03_exports` | Kiểm tra tất cả các symbols công khai (`BaseLLM`, `VLLMModel`, `ModelConfig`, `LLMError`,...) được export đầy đủ và kế thừa đúng cấu trúc lớp. | **PASSED** | < 0.005s |
| 2 | `test_chat_message_validation` | Xác thực `ChatMessage` chỉ chấp nhận các vai trò hợp lệ (`system`, `user`, `assistant`) và nội dung phải là chuỗi ký tự (`str`). | **PASSED** | < 0.005s |
| 3 | `test_generation_options_validation` | Đảm bảo các tham số sampling (`max_new_tokens > 0`, `temperature >= 0`, `0 < top_p <= 1`,...) tuân thủ chặt chẽ các bất biến toán học. | **PASSED** | < 0.005s |
| 4 | `test_load_config_valid` | Đọc cấu hình từ file TOML chuẩn, kiểm tra việc tự động chuẩn hóa đường dẫn weights tương đối và mapping cấu hình sampling. | **PASSED** | < 0.005s |
| 5 | `test_vllm_model_offline_lifecycle` | Kiểm tra vòng đời mô hình: cờ `is_loaded = False` khi khởi tạo, và ném lỗi `ModelLoadError` rõ ràng khi thư mục weights không tồn tại. | **PASSED** | < 0.005s |

---

### 2.2. Kiểm Thử Cấu Trúc Dữ Liệu & Tương Thích Tầng Giao Tiếp (`test_b03_text2sql.py`)

Kiểm tra đặc tả kết quả `Text2SQLResult` theo chuẩn `docs/architecture/b0/input_output_text2sql.md` và khả năng chuyển đổi trực tiếp sang hợp đồng `GenerationResult` của B0.5 Basic Output Gate.

| STT | Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|:---:|---|---|:---:|:---:|
| 6 | `test_text2sql_result_invariants` | Kiểm tra tính bất biến của `Text2SQLResult` đối với cả trường hợp `answerable` và `unanswerable`; kiểm tra phương thức `to_b05_generation_result()` ánh xạ chính xác sang B0.5 `GenerationResult`. | **PASSED** | < 0.005s |
| 7 | `test_format_context_for_prompt` | Kiểm tra khả năng định dạng `BusinessContext` (B0.2) thành chuỗi đặc tả Markdown bao gồm danh sách bảng, cột, kiểu dữ liệu, khóa chính, quan hệ join và quy tắc nghiệp vụ. | **PASSED** | < 0.005s |
| 8 | `test_build_text2sql_messages` | Đảm bảo hàm `build_text2sql_messages` sinh ra 2 message chuẩn (`system` và `user`), nhúng chính xác ngày tham chiếu `as_of_date` và nội dung câu hỏi tiếng Việt. | **PASSED** | < 0.005s |
| 9 | `test_build_repair_messages` | Đảm bảo hàm `build_repair_messages` nhúng đầy đủ câu truy vấn lỗi trước đó và thông báo lỗi từ Database/Executor cho vòng lặp Bounded Retry. | **PASSED** | < 0.005s |

---

### 2.3. Kiểm Thử Bộ Phân Tích Cú Pháp (Parser) & Cơ Chế Fallback (`test_b03_text2sql.py`)

Kiểm tra độ bền bỉ (robustness) của bộ phân tích cú pháp khi tiếp nhận nhiều dạng đầu ra khác nhau từ LLM (JSON chuẩn, JSON bọc trong markdown block, SQL thô không bọc JSON, hoặc văn bản từ chối tự nhiên).

| STT | Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|:---:|---|---|:---:|:---:|
| 10 | `test_parse_text2sql_valid_json` | Giải mã phản hồi JSON tiêu chuẩn nằm trong block ` ```json ... ``` `, bóc tách đầy đủ `status`, `answer_type`, `sql`, `tables_used`, `assumptions`. | **PASSED** | < 0.005s |
| 11 | `test_parse_text2sql_unanswerable_json` | Giải mã phản hồi `unanswerable`, kiểm tra trường `reason` được ghi nhận chính xác và `sql` được đặt thành `None`. | **PASSED** | < 0.005s |
| 12 | `test_parse_text2sql_raw_sql_fallback` | **Fallback Heuristic:** Khi LLM chỉ trả về câu SQL thô trong block ` ```sql ... ``` `, parser tự động nhận diện câu lệnh `SELECT`, suy luận `answer_type` và trích xuất danh sách bảng liên quan. | **PASSED** | < 0.005s |
| 13 | `test_parse_text2sql_rejection_text_fallback` | **Fallback Textual:** Khi LLM trả lời bằng ngôn ngữ tự nhiên từ chối (chứa các cụm từ "không thể trả lời", "thiếu dữ liệu"), parser tự động phân loại thành `status = 'unanswerable'`. | **PASSED** | < 0.005s |
| 14 | `test_parse_text2sql_empty_raises_error` | Đảm bảo ném exception `Text2SQLParseError` có kiểm soát khi chuỗi phản hồi của LLM hoàn toàn rỗng hoặc chỉ có khoảng trắng. | **PASSED** | < 0.005s |
| 15 | `test_extract_tables_from_sql` | Kiểm tra biểu thức chính quy (Regex) trích xuất chính xác tên bảng từ các mệnh đề `FROM`, `JOIN`, bao gồm cả bảng có dấu ngoặc kép. | **PASSED** | < 0.005s |
| 16 | `test_infer_answer_type` | Kiểm tra luật suy luận kiểu câu trả lời từ cú pháp SQL (`COUNT/SUM/AVG` $\rightarrow$ `number`, `strftime` $\rightarrow$ `date`, `SELECT *` $\rightarrow$ `table`). | **PASSED** | < 0.005s |

---

### 2.4. Kiểm Thử Điều Phối Cấp Cao End-to-End (`test_b03_text2sql.py`)

Kiểm tra toàn bộ luồng hoạt động của lớp điều phối `Text2SQLGenerator` kết hợp với `MockLLM`.

| STT | Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|:---:|---|---|:---:|:---:|
| 17 | `test_text2sql_generator_end_to_end` | Kiểm tra luồng `generate()` tạo ra kết quả `answerable` và luồng `repair()` tiếp nhận câu SQL lỗi kèm thông báo lỗi DuckDB để tạo câu SQL sửa đổi hoàn chỉnh. | **PASSED** | < 0.005s |

---

## 3. Kết Luận & Đánh Giá Chất Lượng

1. **Tính độc lập & Deterministic:** 100% các ca kiểm thử chạy độc lập hoàn toàn với phần cứng GPU, không yêu cầu tải weights gigabyte, đảm bảo chạy ổn định trong mọi môi trường CI/CD và dev cục bộ.
2. **Khả năng tương thích Module (Module Interoperability):**
   * **Đầu vào (Input):** Tương thích 100% với hợp đồng dữ liệu của **B0.2 Context** (`BusinessContext`, `SchemaCatalog`, `RuleCatalog`).
   * **Đầu ra (Output):** Ánh xạ trực tiếp sang hợp đồng của **B0.5 Output Gate** (`GenerationResult`, `AnswerSemantics`) và sẵn sàng cung cấp câu lệnh SQL sạch cho **B0.4 Executor**.
3. **Độ tin cậy & Khả năng chịu lỗi:** Bộ parser được trang bị các cơ chế phòng vệ đa tầng (JSON matching, Markdown stripping, Regex extraction, Fallback classification), ngăn chặn triệt để nguy cơ ứng dụng bị crash do định dạng LLM biến thiên.

