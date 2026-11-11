# Báo Cáo Thay Đổi & Hồ Sơ Quyết Định Kiến Trúc (ADR-012): Đồng Bộ Tương Thích Nhánh `origin/feature/B1.3_bao` (Thinking Token Budget & Diagnostics)

> **Tài liệu:** `docs/change/B13_PIPELINE_COMPATIBILITY_CHANGELOG.md`  
> **Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
> **Nhánh hợp nhất:** `origin/feature/B1.3_bao` $\rightarrow$ `dev`  
> **Phạm vi tác động:** `configs/qwen3_5_9b.toml`, `src/datamate/b0/b03/`, `src/datamate/b0/b05/`, `src/datamate/b0/pipeline.py`, `scripts/`, `tests/`  
> **Trạng thái:** **Accepted & Verified (352 passed, 3 skipped)**

---

## 1. Bối Cảnh & Những Thay Đổi Từ Nhánh `origin/feature/B1.3_bao`

Nhánh `origin/feature/B1.3_bao` (commit `cbdb96f`) triển khai cải tiến tầng mô hình **B1.3** nhằm giải quyết vấn đề mô hình suy luận sâu (như Qwen3.5-9B Thinking) kéo dài reasoning block `<think>...</think>`, làm cạn kiệt ngân sách output token (`max_new_tokens = 8192`) trước khi kịp sinh ra câu lệnh SQL/JSON hoàn chỉnh:

1. **Giới Hạn Thinking Token Budget (`thinking_token_budget = 4096`)**:
   - Thêm trường `thinking_token_budget: int | None = None` vào `GenerationOptions` ([`src/datamate/b0/b03/types.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py)). Khi có giá trị, bắt buộc là số nguyên dương và `< max_new_tokens`.
   - Cập nhật [`configs/qwen3_5_9b.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b.toml) với `thinking_token_budget = 4096`, `max_new_tokens = 8192`, `max_model_len = 32768`.
2. **Cấu Hình Ranh Giới Reasoning Trên vLLM Backend**:
   - Trong `VLLMModel` ([`src/datamate/b0/b03/vllm_model.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/vllm_model.py)), sử dụng `ReasoningConfig(reasoning_start_str="<think>", reasoning_end_str="</think>")` và truyền `thinking_token_budget` vào `SamplingParams`.
3. **Thu Thập & Ghi Nhận Diagnostics Đầy Đủ**:
   - Định nghĩa dataclass `GenerationDiagnostics` ([`src/datamate/b0/b03/types.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py)) lưu: `raw_response`, `input_tokens`, `output_tokens`, `finish_reason`, `thinking_enabled`, `thinking_token_budget`, `max_new_tokens`, `parse_success`, `failure_kind`, `error_type`, `error_message`, `traceback`.
   - Phân biệt 3 nhóm lỗi `failure_kind`: `inference_error`, `parse_error`, và `parse_error_after_length_limit`.
   - Ghi nhận trường `generation_diagnostics` và `batch_fallback_error` xuyên suốt qua `B0Pipeline`, `SubmissionWriter` và `AuditLogger` vào `detailed_logs.jsonl` và `logs/<id>_<hash>.json`.

---

## 2. Xung Đột Merge & Điểm Lệch Tương Thích Phát Hiện

### 2.1. Xung Đột Merge Cú Pháp
* **`.gitignore`**: Xung đột giữa các thư mục dữ liệu mới (`benchmark_outputs`, `synthetic_data`, `khoi_docs/`). Đã hợp nhất sạch sẽ không làm mất bất kỳ cấu hình nào.
* **`src/datamate/b0/b03/vllm_model.py`**:
  * Nhánh `dev` trước đó đã tái cấu trúc `_apply_chat_template` và `count_chat_tokens` để chuẩn hóa việc tokenize và đo lường context.
  * Nhánh `feature/B1.3_bao` đã inline việc gọi template vào `chat_batch` với xử lý lỗi `thinking_token_budget`, dẫn đến việc merge tự động sinh ra biến `payloads` chưa được định nghĩa và trùng lặp mã nguồn.
  * **Giải pháp:** Tích hợp logic xử lý lỗi `thinking_token_budget` trực tiếp vào `_apply_chat_template(messages, tokenize=..., options=...)` theo nguyên lý DRY (Don't Repeat Yourself), giúp cả `count_chat_tokens` lẫn `chat_batch` đều được bảo vệ đồng nhất.

### 2.2. Điểm Thiếu Sót Trong Commit Nhánh B1.3
* Tài liệu `docs/code/b1/b13/b13_1_fix_invalid_generation.md` mô tả bộ test `tests/test_thinking_budget_diagnostics.py` và script kiểm chứng GPU `scripts/check_thinking_budget.py`, nhưng commit `cbdb96f` bị sót hai tệp này khỏi chỉ mục git.
* **Giải pháp:** Đã tạo mới đầy đủ `tests/test_thinking_budget_diagnostics.py` (7 test cases kiểm chứng chặt chẽ mọi ràng buộc của B1.3) và `scripts/check_thinking_budget.py`.

### 2.3. Tăng Cường Độ Bền Của Pipeline (`B0Pipeline.answer_question`)
* Trong `answer_question` (chế độ chạy đơn lẻ), ban đầu chỉ bắt `except LLMError as exc:`. Nếu quá trình sinh gặp ngoại lệ bất ngờ khác (`RuntimeError`, `ValueError`, lỗi hệ thống), pipeline sẽ bị gián đoạn thay vì ghi nhận chẩn đoán và chuyển sang trạng thái dừng an toàn `abstain`.
* **Giải pháp:** Chuyển sang bắt `except Exception as exc:` tương tự như khối batch mode, đảm bảo mọi ngoại lệ đều được chuyển thành `generation_diagnostics` thông qua `diagnostics_dict(exc)`.

---

## 3. Kết Quả Kiểm Thử Toàn Tuyến

* Bộ kiểm thử B1.3 mới ([`tests/test_thinking_budget_diagnostics.py`](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_thinking_budget_diagnostics.py)): **7/7 passed**.
* Toàn bộ test suite hệ thống: **`352 passed, 3 skipped, 15 subtests passed`** (tăng từ 345 lên 352).
* Mọi hợp đồng giao tiếp giữa B0.1, B0.2, Grounding, B0.3 (B1.3), B0.4 và B0.5 đều hoạt động chính xác và an toàn.

