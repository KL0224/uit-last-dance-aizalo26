# Báo Cáo Thay Đổi & Kết Quả Khắc Phục Lỗi Post-Merge (`voting_grouding` & `finetuning-qwen-3.5_kiet`)

> **Tài liệu:** `docs/change/POST_MERGE_VOTING_FINETUNING_FIX_CHANGELOG.md`  
> **Tham chiếu rà soát:** [POST_MERGE_VOTING_FINETUNING_REVIEW.md](file:///home/kiet97/uit-last-dance-aizalo26/docs/review/POST_MERGE_VOTING_FINETUNING_REVIEW.md)  
> **Kế hoạch triển khai:** `tasks/post_merge_fix_plan.md` & `tasks/post_merge_fix_todo.md`  
> **Ngày thực hiện:** 2026-11-16  
> **Nhánh áp dụng:** `dev` (sau các merge `4bcdaff` và `3c4be01`)  
> **Trạng thái:** **Fixed & Verified (`494 passed, 3 skipped, 15 subtests passed`)**

---

## 1. Tóm Tắt Thực Thi & Phạm Vi Thay Đổi

Sau khi phân rã công việc và áp dụng quy trình **TDD (Red → Green → Refactor)** trên toàn bộ các phát hiện trong [POST_MERGE_VOTING_FINETUNING_REVIEW.md](file:///home/kiet97/uit-last-dance-aizalo26/docs/review/POST_MERGE_VOTING_FINETUNING_REVIEW.md), đợt chỉnh sửa đã xử lý dứt điểm **3 lỗi `Critical`**, **3 lỗi `Required`** (`R1`, `R2`, `R3`) và **3 điểm `Consider`** (`#1`, `#2`, `#4`), đồng thời bổ sung đầy đủ bộ test hồi quy.

> **Lưu ý phạm vi tách riêng (`R4` — tích hợp LoRA `v1_2_a100_80gb`):**  
> Việc chuyển đổi `src/datamate/planner/prompt.py` sang hợp đồng `planner.v1.2` (`planner.v1.2-sys.1` + JSON input + `structured_plan`) và gắn adapter LoRA vào `VLLMModel` được giữ nguyên ở trạng thái tách riêng (không thay đổi hành vi base model mặc định của `predict.sh`), chờ bước benchmark đối chứng PA trên Modal GPU (`276` câu Validation) như kế hoạch tại [`finetuning/PLAN.md`](file:///home/kiet97/uit-last-dance-aizalo26/finetuning/PLAN.md).

---

## 2. Chi Tiết Các Thay Đổi Đã Thực Hiện

| Mã | Mức độ | Tệp thay đổi | Nội dung chỉnh sửa |
| :--- | :--- | :--- | :--- |
| **C1 + Consider #4** | Critical | [`src/datamate/context/runtime.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/context/runtime.py#L31-L72), [`src/datamate/ingestion/ingestion/preparation.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/ingestion/ingestion/preparation.py#L326-L328), [`scripts/run_pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/run_pipeline.py#L475-L485) | Trích xuất helper dùng chung `sync_unit_conversions_to_bundle()` để nạp bảng `main.unit_conversions` (`DECIMAL(38,12)`) vào DuckDB và chuyển `schema_catalog["tables"]` từ `tuple` sang `list` trước khi đăng ký bảng `unit_conversions`, loại bỏ hoàn toàn `AttributeError: 'tuple' object has no attribute 'append'` và xóa logic trùng lặp giữa `preparation.py` với `run_pipeline.py`. |
| **C2** | Critical | [`configs/qwen3_5_9b.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b.toml#L18-L20) | Khôi phục `enable_thinking = true` để đồng bộ với `thinking_token_budget = 4096`, đặc tả [`voting_mechanism.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b1/b13/voting_mechanism.md), và bài test `test_qwen_toml_config_loads_thinking_budget` (vòng 1 của `--voting` vẫn tự override `enable_thinking=False` tại runtime). |
| **C3** | Critical | [`main.py`](file:///home/kiet97/uit-last-dance-aizalo26/main.py#L1-L6) | Xóa bỏ biến chuỗi debug `"Thinking Process: ..."` dài 19 KB và câu lệnh `print(response)` bị dính từ merge `4bcdaff`. |
| **R1 + Consider #2** | Required | [`src/datamate/voting.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/voting.py#L22-L24), [`tests/test_voting.py`](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_voting.py) | Đồng nhất giá trị mặc định `VotingConfig.temperature = 0.7` khớp với CLI (`run_pipeline.py`, `modal_run_pipeline.py`) và tài liệu; bổ sung bộ test `tests/test_voting.py` cho voting 2 vòng, ngưỡng `>=` theo `Decimal`, hòa phiếu, `ABSTAIN` trong mẫu số, `unanswerable`, canonical values, `max_retries=2` (v1/v2), `VLLMModel` thinking override & token counting, repair `attempt=2`, batch fallback, và parity `batch_size=1` vs `batch_size>1`. |
| **R2** | Required | [`scripts/run_pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/run_pipeline.py#L100-L107) | Bỏ điều kiện `opts.enable_thinking is not None` khi gắn `top_p`, `top_k`, `presence_penalty`, `repetition_penalty` vào `extra_body` trong `OpenAICompatibleLLM.chat()`, đảm bảo chế độ không bật voting (`enable_thinking=None`) vẫn giữ nguyên cấu hình sampling từ TOML. |
| **R3** | Required | [`src/datamate/ingestion/ingestion/readers.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/ingestion/ingestion/readers.py#L67-L85) | Siết regex nhận diện sheet tháng trong `_family()` trên `fold(sheet)` giữ khoảng trắng với ranh giới từ cho `thang`/`t01..t12` và ranh giới không phải chữ-số cho mẫu `MM/YYYY` / `YYYY-MM`, tránh ghép nhầm `Q1_2025`, `Part1_2025`, `Test1_2025`, `Sheet2_2025`. |
| **Consider #1** | Minor | [`src/datamate/pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py#L248-L260) | Thêm helper `_record_writer_grounding_trace()` đọc `writer.result_dir` (fallback `writer.output_dir`) và gọi ở mọi nhánh thoát của `answer_question()` (gồm fast-path, `--voting`, và lỗi sinh SQL), đảm bảo `grounding_trace.jsonl` được ghi đủ 1 dòng/câu khi chạy `batch_size=1`. |
| **Regression Tests** | — | [`tests/test_post_merge_fixes.py`](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_post_merge_fixes.py) | Tạo bộ test hồi quy tái hiện và kiểm chứng toàn bộ các lỗi `C1`, `C3`, `R2`, `R3`, và `Consider #1`. |

---

## 3. Kết Quả Kiểm Thử & Xác Minh Sau Chỉnh Sửa

### 3.1. Chu trình TDD (Red → Green)
- **Trước khi sửa (RED):** `pytest -q tests/test_post_merge_fixes.py tests/test_voting.py tests/test_thinking_budget_diagnostics.py` → **7 failed, 10 passed** (tái hiện đúng toàn bộ 7 lỗi: `C1`, `C2`, `C3`, `R2`, `R3`, `Consider #1`, `Consider #2`).
- **Sau khi sửa (GREEN):** `pytest -q tests/test_post_merge_fixes.py tests/test_voting.py tests/test_thinking_budget_diagnostics.py` → **17 passed in 3.19s**.

### 3.2. Kiểm thử toàn hệ thống (Full Suite & Static Checks)
| Hạng mục kiểm tra | Lệnh thực thi (`.venv`) | Kết quả quan sát được |
| :--- | :--- | :--- |
| Toàn bộ Test Suite | `pytest -q` | **494 passed, 3 skipped, 15 subtests passed** (20.11s, **0 failed**) |
| Biên dịch bytecode | `python -m compileall -q src scripts main.py finetuning` | **PASS** (exit code 0) |
| Kiểm tra cú pháp Shell | `bash -n predict.sh entrypoint.sh` | **PASS** (exit code 0) |
| Quét toàn bộ sheet `.xlsx` | Quét 438 sheets trên `data/train` & `data/public_test` qua `_family()` | **370 sheets tháng/mặc định gộp về stem** (`T01_2025`..`T02_2026`, `Sheet1`); **68 sheets nghiệp vụ giữ nguyên tên** (`DanhSachHoaDon`, `BaoCaoTonKho`, `DanhSachQuyDoi`...) |
| E2E trên dữ liệu thật (`biz_113`, `biz_101`, `biz_103`) | `prepare_bundle()` + Grounding C1–C5 + Voting (`batch_size=2`) + DuckDB + Gate + Finalizer (mock LLM) | - `biz_113`: **PASS** (`tables=3`, `has_unit_conv=True`, 3/3 `VALID_RESULT`, `grounding_lines=3`)<br>- `biz_101`: **PASS** (`tables=3`, `has_unit_conv=True`, 3/3 `VALID_RESULT`, `grounding_lines=3`)<br>- `biz_103`: **PASS** (`tables=3`, `has_unit_conv=False`, 3/3 `VALID_RESULT`, `grounding_lines=3`) |

---

## 4. Hạn Chế Chưa Kiểm Chứng & Bước Tiếp Theo

1. **Môi trường CPU local (`.venv`) chưa cài `vllm`, `torch`, `transformers`, `trl`, `peft`, `ruff`:**
   - Hành vi của `VLLMModel` đã được kiểm chứng qua mock engine/tokenizer trong `tests/test_voting.py` và `tests/test_thinking_budget_diagnostics.py`, nhưng **chưa chạy suy luận GPU vLLM thực tế** (`language_model_only=True` và toggle `enable_thinking` giữa vòng 1/vòng 2 trên `Qwen/Qwen3.5-9B` + `Qwen2.5-3B-Instruct`).
2. **Bước tiếp theo đề xuất:**
   - Chạy smoke test trên Modal GPU để xác nhận vLLM runtime:
     ```bash
     source .venv/bin/activate && modal run scripts/modal_run_pipeline.py --split train --limit 10 --voting
     ```
   - Khi sẵn sàng đánh giá adapter LoRA `artifacts/finetuning/v1_2_a100_80gb/train/adapter-final/`, mở một nhánh/PR riêng để tích hợp prompt contract `planner.v1.2` và cờ `--enable-lora` vào tầng Planner.
