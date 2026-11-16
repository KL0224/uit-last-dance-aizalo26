# Báo Cáo Rà Soát Pipeline & Code Review Sau Merge Nhánh `voting_grouding` và `feature/finetuning-qwen-3.5_kiet` vào `dev`

> **Ngày:** 2026-11-16  
> **Nhánh hiện tại:** `dev` (`3c4be01`) — gồm merge `4bcdaff` (`origin/feature/bao/voting_grouding`, commit `8aaef8e`) và merge `3c4be01` (`feature/finetuning-qwen-3.5_kiet`, các commit `8d34e33`, `78eb9f5`, `ea7eebd`)  
> **Tiêu chuẩn áp dụng:** Code Review 5 Trục (*Correctness, Readability & Simplicity, Architecture, Security, Performance*) + Kiểm thử luồng E2E pipeline thực tế  
> **Kết luận chung (Verdict):** **Request changes** — **Chưa thể coi pipeline chạy trơn tru hoàn toàn.** Phát hiện **3 lỗi mức `Critical`** (làm hỏng `pytest`, làm sập `prepare_bundle()` trên 24 doanh nghiệp có bảng quy đổi đơn vị, và code debug thừa trong `main.py`), **4 vấn đề `Required`** (thiếu `tests/test_voting.py`, adapter LoRA chưa tích hợp vào planner, `OpenAICompatibleLLM` bỏ sót tham số sampling, regex `_family()` nhận nhầm sheet), cùng một số điểm `Consider` / `Nit`.

---

## 1. Kết quả kiểm tra tự động & Kiểm thử luồng E2E thực tế

| Kiểm tra | Phạm vi / Điều kiện | Kết quả quan sát được |
| :--- | :--- | :--- |
| `python -m compileall -q src scripts main.py finetuning` | Toàn bộ source, scripts, finetuning | **PASS** (0 lỗi cú pháp) |
| `pytest -q` (trong `.venv`) | Toàn bộ test suite hiện có | **FAIL** — **1 failed, 483 passed, 3 skipped, 15 subtests passed** (19.63s). Lỗi tại `tests/test_thinking_budget_diagnostics.py::test_qwen_toml_config_loads_thinking_budget` |
| `ruff` static lint | Không có `ruff` trong `.venv` | **Chưa kiểm tra được** (`ruff: command not found`) |
| `python scripts/run_pipeline.py --help` | Kiểm tra CLI & import voting | **PASS** |
| `python main.py` | Chạy entrypoint gốc | **CẢNH BÁO** — In ra 19 KB chuỗi debug `"Thinking Process: ..."` trước `"Hello from uit-last-dance-aizalo26!"` |
| E2E mock-LLM trên bundle synthetic | `batch_size=1` & `batch_size=2`, voting tắt/bật, repair 2 lần (`attempt=2`), hòa 2 vòng → `VOTING_THRESHOLD_NOT_MET`, batch fallback | **PASS** các nhánh điều phối voting, repair budget `max_retries=2`, canonical vote & fallback (`tokens_complete=False`) |
| E2E trên dữ liệu thật `data/train` (`biz_101`, `biz_113`, `biz_103`) | `prepare_bundle()` + Grounding C1–C5 + Voting + DuckDB + Gate + Finalizer | **`biz_101` & `biz_113` CRASH** ở `prepare_bundle()` (`PreparationError: 'tuple' object has no attribute 'append'`). **`biz_103` PASS** đầy đủ cả `submission.jsonl`, `submission.manifest.json`, `detailed_logs.jsonl`, `grounding_trace.jsonl`, `logs/*.json` |
| GPU runtime (`vllm`, `torch`, `transformers`, `trl`, `peft`) | `.venv` hiện tại là môi trường CPU | **Chưa kiểm thử thực thi GPU/vLLM/Modal thực tế** trong phiên này |

---

## 2. Đánh giá luồng hoạt động End-to-End của Pipeline

Luồng chuẩn: `Ingestion & Preparation (A/B)` → `Context Runtime` → `Grounding (C1–C5)` → `Planner / Voting (D)` → `DuckDB Execution (E)` → `Bounded Repair (F)` → `Output Gate & Audit/Finalizer (G/H)`.

1. **Chặn đứng ở bước A/B (`prepare_business`) với các doanh nghiệp có `unit_conversions`:**  
   Khi chạy từ dữ liệu thô (`predict.sh` trong Docker, hoặc `scripts/run_pipeline.py` khi chưa có cache bundle), [`prepare_business`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/ingestion/ingestion/preparation.py#L326-L351) sập với `AttributeError: 'tuple' object has no attribute 'append'` ở dòng 339. Qua quét thực tế `README.md`, **18/30 doanh nghiệp trong `data/train`** và **6/14 doanh nghiệp trong `data/public_test`** có quy tắc quy đổi đơn vị nên sẽ vấp lỗi này nếu dựng bundle mới. *(Ghi nhận: `artifacts/b01_b02_full/enriched_bundles` cũng không tồn tại trên đĩa hiện tại).*
2. **Giai đoạn C (Grounding C1–C5) & Fast-path:**  
   Hoạt động trơn tru trên doanh nghiệp dựng được bundle (`biz_103`). Fast-path `is_directly_unanswerable` trả thẳng về Gate trước khi vào `run_voting()`, không gọi Planner thừa. Tuy nhiên, khi chạy `batch_size=1` (`answer_question`), file `grounding_trace.jsonl` không được ghi do kiểm tra nhầm thuộc tính `writer.output_dir` (thực tế là `writer.result_dir`) và do return sớm ở nhánh voting.
3. **Giai đoạn D/E/F/G/H khi bật `--voting`:**  
   Luồng voting hai vòng hoạt động khớp logic trong [`src/datamate/voting.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/voting.py) trên mock LLM:
   - Vòng 1 sinh `k` ∈ `{4, 8}` candidates với `enable_thinking=False`, `thinking_token_budget=None`, mỗi candidate được retry tối đa 2 lần (`attempt = 0, 1, 2`, `max_retries=2` được truyền xuyên suốt `GateRequest` và `ExecutionRequest`).
   - So sánh kết quả sau formatter bằng `_canonical()`, bỏ qua `ABSTAIN`/`ERROR` ở tử số nhưng vẫn giữ ở mẫu số `total_candidates`, dùng `Decimal` tránh sai số float ở ngưỡng `>= threshold`.
   - Nếu vòng 1 chưa có winner duy nhất, vòng 2 sinh thêm `4` candidates với `enable_thinking=True` và giữ `thinking_token_budget` từ `base`, vote cộng dồn trên `k+4`. Nếu vẫn hòa/không đạt ngưỡng → `ABSTAIN` với `reason_code="VOTING_THRESHOLD_NOT_MET"`.
   - Khi batch inference lỗi hoặc trả thiếu phần tử, `_infer()` fallback tuần tự từng item với `seed + index` và đánh dấu `tokens_complete=False`.
   - Tuy nhiên, nếu chạy `--voting=false` với cấu hình mặc định mới của [`configs/qwen3_5_9b.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b.toml) (`enable_thinking=false` nhưng `thinking_token_budget=4096`), `VLLMModel` bị cấu hình mâu thuẫn giữa chat template và `ReasoningConfig`/`SamplingParams`.
4. **Nhánh Fine-tuning Qwen3.5-9B LoRA (`finetuning/`):**  
   Code huấn luyện độc lập (`prepare` / `smoke` / `bench` / `train` trên Modal A100-80GB) được viết sạch sẽ, tách biệt với `src/`, đã xuất adapter về `artifacts/finetuning/v1_2_a100_80gb/`, **nhưng chưa được tích hợp vào pipeline suy luận** (`ModelConfig`/`VLLMModel` chưa nạp LoRA, `src/datamate/planner/prompt.py` vẫn dùng prompt Markdown cũ thay vì `planner.v1.2`).

---

## 3. Danh sách phát hiện chi tiết (Phân loại theo mức độ)

### 3.1. `Critical:` (Chặn merge / làm hỏng test hoặc luồng chạy)

#### [C1] `Critical:` `prepare_business()` sập với `AttributeError` khi doanh nghiệp có `unit_conversions`
- **Vị trí:** [`src/datamate/ingestion/ingestion/preparation.py:337-350`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/ingestion/ingestion/preparation.py#L337-L350), tương tác với [`BusinessContext.to_dict()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/context/contracts.py#L93-L107).
- **Mô tả & Bằng chứng:**  
  `SchemaCatalog.tables` là một `tuple`, nên `dataclasses.asdict(self)` trả về `ctx_dict["schema_catalog"]["tables"]` vẫn là `tuple`. Khi `unit_convs` khác rỗng, dòng 339 gọi `.append({...})` trực tiếp lên `tuple` đó:
  ```text
  [train:biz_113] FAILED: PreparationError: 'tuple' object has no attribute 'append'
  ```
  Lỗi xảy ra trên cả `biz_101` và `biz_113` khi chạy `DataMatePipeline.prepare_bundle()`. Theo kiểm tra `README.md`, 18/30 doanh nghiệp `train` và 6/14 doanh nghiệp `public_test` có công thức quy đổi đơn vị (`1 <unit> = <num> <unit>`), tức phần lớn tập test sẽ lỗi nếu build bundle mới (bao gồm khi chạy `predict.sh` trong Docker).
- **Hướng khắc phục:** Chuyển `tables` thành `list` trước khi `append` và gán lại vào `ctx_dict["schema_catalog"]["tables"]`, đồng thời thêm unit test hồi quy cho `prepare_business()` với dữ liệu có `unit_conversions`.

#### [C2] `Critical:` Thay đổi `enable_thinking = false` trong `configs/qwen3_5_9b.toml` làm gãy `pytest` và gây trạng thái cấu hình mâu thuẫn
- **Vị trí:** [`configs/qwen3_5_9b.toml:18-24`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b.toml#L18-L24), [`tests/test_thinking_budget_diagnostics.py:46-56`](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_thinking_budget_diagnostics.py#L46-L56), [`src/datamate/planner/types.py:50-51`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/types.py#L50-L51).
- **Mô tả & Bằng chứng:**  
  Commit `8aaef8e` sửa `enable_thinking = true` thành `enable_thinking = false` trong `configs/qwen3_5_9b.toml` nhưng vẫn giữ `thinking_token_budget = 4096`. Hệ quả:
  1. `pytest -q` **FAIL** tại `test_qwen_toml_config_loads_thinking_budget`: `AssertionError: assert False is True`.
  2. Khi chạy không bật `--voting` và không truyền `--enable-thinking` (chính là lệnh mặc định trong [`predict.sh:94-100`](file:///home/kiet97/uit-last-dance-aizalo26/predict.sh#L94-L100)), `VLLMModel.load()` vẫn khởi tạo `ReasoningConfig` và truyền `thinking_token_budget=4096` vào `SamplingParams`, trong khi chat template lại tắt thinking (`enable_thinking=False`). Đây đúng là trạng thái mà `GenerationOptions.__post_init__` chủ động cấm (`Thinking disabled requires thinking_token_budget=None`).
- **Hướng khắc phục:** Trả `enable_thinking = true` về lại [`configs/qwen3_5_9b.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b.toml) (vì khi bật `--voting`, `VotingConfig.options()` đã tự override vòng 1 về `enable_thinking=False, thinking_token_budget=None` mà không cần sửa TOML). Nếu cố ý đổi mặc định non-voting sang tắt thinking, cần bỏ `thinking_token_budget` (hoặc tách file config riêng) và cập nhật test + tài liệu tương ứng.

#### [C3] `Critical:` Dính mã debug 19 KB hardcoded trong `main.py`
- **Vị trí:** [`main.py:5-8`](file:///home/kiet97/uit-last-dance-aizalo26/main.py#L5-L8) (merge từ `8aaef8e`).
- **Mô tả & Bằng chứng:**  
  `main.py` bị chèn một chuỗi raw CoT + JSON dài 19,083 bytes (`response = "Thinking Process:..."`) và gọi `print(response)` ngay trong `if __name__ == "__main__":`. Điều này cũng mâu thuẫn trực tiếp với [`docs/code/b1/b13/voting_mechanism.md:138`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b1/b13/voting_mechanism.md#L138) (*"không sửa `main.py`"*).
- **Hướng khắc phục:** Xóa hai dòng `response = ...` và `print(response)` trong `main.py`.

---

### 3.2. Required (Cần sửa trước khi đưa lên nhánh chính / chạy chính thức)

#### [R1] Thiếu toàn bộ bộ test `tests/test_voting.py` được mô tả trong tài liệu
- **Vị trí:** [`docs/code/b1/b13/voting_mechanism.md:154,177`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b1/b13/voting_mechanism.md#L154), thư mục `tests/`.
- **Mô tả:** Tài liệu ghi nhận đã thêm `tests/test_voting.py` và chạy được test coverage đầy đủ cho voting, nhưng `git show 8aaef8e --stat` cho thấy file này **chưa từng được commit**. Hiện tại `src/datamate/voting.py` (206 dòng), luồng `max_retries=2` trong `gate/`, và override `enable_thinking` trong `VLLMModel` không có test hồi quy tự động nào trong `pytest`.
- **Hướng khắc phục:** Bổ sung `tests/test_voting.py` bao phủ: `VotingConfig` validation, `vote()` (`>= threshold`, tie, `ABSTAIN` trong mẫu số, `unanswerable`, canonical số/list/table), `run_voting()` single vs batch parity, repair `attempt=2`, batch fallback, và `VLLMModel`/`Text2SQLGenerator` thinking override.

#### [R2] `OpenAICompatibleLLM.chat()` bỏ rơi tham số sampling khi `enable_thinking` là `None`
- **Vị trí:** [`scripts/run_pipeline.py:100-104`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/run_pipeline.py#L100-L104).
- **Mô tả & Bằng chứng:**  
  `top_p`, `top_k`, `presence_penalty`, `repetition_penalty` chỉ được thêm vào `extra_body` khi `opts.enable_thinking is not None`. Khi chạy `--api-base` ở chế độ không voting (`enable_thinking=None`), `OpenAICompatibleLLM` chỉ gửi `max_tokens`, `temperature`, `seed`, bỏ qua toàn bộ `top_p=1.0`, `top_k=-1`, `repetition_penalty=1.05` từ TOML (đã xác minh trực tiếp qua mock OpenAI client: `call 1 extra_body = {'chat_template_kwargs': {'enable_thinking': False}, 'thinking_token_budget': 4096}`).
- **Hướng khắc phục:** Truyền `top_p` (tham số chuẩn OpenAI API) và các sampling kwargs của vLLM bất cứ khi nào `opts` khác `None`, không phụ thuộc vào `opts.enable_thinking is not None`.

#### [R3] Regex trong `readers._family()` ghép nhầm các sheet không phải theo tháng
- **Vị trí:** [`src/datamate/ingestion/ingestion/readers.py:67-76`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/ingestion/ingestion/readers.py#L67-L76) (commit `8d34e33`).
- **Mô tả & Bằng chứng:**  
  Chạy thử trực tiếp `_family()` cho thấy:
  - `_family(Path("f.xlsx"), "Q1_2025", 0)` → `'f'` vì `re.search(r"(?:^|\D)\d{1,2}\s*[./_-]\s*(?:19|20)\d{2}", "Q1_2025")` khớp chuỗi con `Q1_2025`.
  - `_family(Path("f.xlsx"), "Part1_2025", 0)` / `"Test1_2025"` / `"Sheet2_2025"` → `'f'` vì `re.search(r"(?:thang|t\d)", folded_sheet)` không có ranh giới đầu từ/phân tách trước `t\d` (khớp `t1` trong `part1`, `test1` và `t2` trong `sheet2`).
- **Hướng khắc phục:** Neo ranh giới trước `t\d` (ví dụ `(?:^|[^a-z])t(?:0?[1-9]|1[0-2])(?:\D|$)`) và yêu cầu `\d{1,2}` chỉ khớp số tháng `1..12` đứng đầu hoặc sau ký tự phân tách không phải chữ cái (`q`, `p`...). Bổ sung unit test cho `readers._family()`.

#### [R4] Adapter fine-tune LoRA (`v1_2_a100_80gb`) chưa được nối vào pipeline suy luận
- **Vị trí:** [`finetuning/PLAN.md:114-118`](file:///home/kiet97/uit-last-dance-aizalo26/finetuning/PLAN.md#L114-L118), [`docs/finetuning/QWEN35_9B_LORA_FINETUNING_REPORT.md:142-144`](file:///home/kiet97/uit-last-dance-aizalo26/docs/finetuning/QWEN35_9B_LORA_FINETUNING_REPORT.md#L142-L144), [`src/datamate/planner/prompt.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/prompt.py), [`src/datamate/planner/vllm_model.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/vllm_model.py).
- **Mô tả:** Nhánh `feature/finetuning-qwen-3.5_kiet` mới dừng ở phần training/export adapter (`artifacts/finetuning/v1_2_a100_80gb/`). Nếu đưa adapter này vào chạy qua pipeline hiện tại ngay sẽ lệch hợp đồng:
  1. `VLLMModel` và `ModelConfig` chưa hỗ trợ `enable_lora` / `lora_path` (hoặc chưa merge adapter thành model standalone trong `models/`).
  2. `src/datamate/planner/prompt.py` vẫn dùng `SYSTEM_INSTRUCTION` dạng Markdown và output schema cũ, trong khi adapter được train với `planner.v1.2-sys.1` + JSON input (`planner.v1.2-input.1`) + `planner_output.schema.json` (gồm `structured_plan` + `sql`) và `enable_thinking=False`.
- **Hướng khắc phục:** Khi tích hợp adapter vào `dev` để đánh giá Validation/Holdout, cần tách rõ hoặc cấu hình hóa prompt builder + parser cho `planner.v1.2`, thêm hỗ trợ LoRA (hoặc merge checkpoint) vào `VLLMModel`/`ModelConfig`, và đồng bộ cách chạy với chế độ `enable_thinking=False` của adapter.

---

### 3.3. `Consider:` & `Nit:` (Cải tiến kiến trúc, khả năng quan sát, hiệu năng)

1. **`Consider:` `grounding_trace.jsonl` bị bỏ qua khi `batch_size=1` hoặc khi bật `voting` ở chế độ single-question**  
   - [`src/datamate/pipeline.py:445-446`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py#L445-L446) kiểm tra `getattr(writer, "output_dir", None)`, nhưng [`SubmissionWriter`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/gate/writer.py#L17) lưu đường dẫn ở `self.result_dir`. Ngoài ra nhánh voting tại `pipeline.py:359` return trước dòng 445. Nên chuyển việc ghi `grounding_trace.jsonl` về `run_questions()` (giống nhánh `batch_size > 1` tại dòng 872) để hai chế độ `batch_size=1` và `batch_size > 1` đồng nhất hoàn toàn.
2. **`Consider:` Không đồng nhất mặc định `temperature` giữa thư viện và CLI**  
   - [`VotingConfig.temperature`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/voting.py#L696) mặc định `0.5`, trong khi [`scripts/run_pipeline.py:710`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/run_pipeline.py#L710) và [`scripts/modal_run_pipeline.py:96,208`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/modal_run_pipeline.py#L96) mặc định `0.7`. Nên thống nhất về một hằng số chung.
3. **`Consider:` Rủi ro nghẽn/quá tải batch khi kết hợp `batch_size=16` và `--voting`**  
   - Trong [`scripts/modal_run_pipeline.py:88,94`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/modal_run_pipeline.py#L88), `batch_size=16` với `voting_candidates=8` sẽ đẩy tới `16 × 8 = 128` prompt (mỗi prompt ~9K–17K tokens) trong một lần `generate_batch`. Với vLLM offline, engine tự xếp hàng theo `max_num_seqs=16`, nhưng nếu dùng `--api-base`, `OpenAICompatibleLLM.chat_batch` chạy tuần tự 128 request HTTP có thể chậm và dễ chạm timeout.
4. **`Consider:` Đồng bộ `unit_conversions` giữa `preparation.py` và `scripts/run_pipeline.py` (khi `enable_grounding_llm=True`)**  
   - [`scripts/run_pipeline.py:477-487`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/run_pipeline.py#L477-L487) dùng kiểu cột `factor DOUBLE` (khác `DECIMAL(38,12)` ở `preparation.py:330`) và không đăng ký bảng `unit_conversions` vào `schema_catalog.tables` trong `business_context.json`.
5. **`Consider:` Kiểm thử thực tế trên GPU vLLM với `language_model_only=True` và `ReasoningConfig`**  
   - `ModelConfig.language_model_only` nay mặc định là `True` ([`src/datamate/planner/types.py:90`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/types.py#L90)), được truyền cho cả model 9B lẫn model Grounding 3B (`Qwen2.5-3B-Instruct`, [`create_qwen3b_vllm_parser`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/llm_fallback.py#L390)). Cần chạy smoke test thực tế trên vLLM phiên bản lock (`vllm==0.30.0` trong `requirements-lock.txt`, lưu ý `Dockerfile` base là `vllm/vllm-openai:v0.10.1.1` trước khi cài `requirements-lock.txt`) để xác nhận `language_model_only=True` không lỗi trên text-only model và `enable_thinking` toggle qua lại giữa vòng 1/vòng 2 hoạt động đúng trên tokenizer thật.
6. **`Nit:` Đánh giá 5 trục bổ sung cho `finetuning/`**  
   - **Correctness / Readability / Architecture:** [`finetuning/train_datamate.py`](file:///home/kiet97/uit-last-dance-aizalo26/finetuning/train_datamate.py) và [`finetuning/modal_finetune.py`](file:///home/kiet97/uit-last-dance-aizalo26/finetuning/modal_finetune.py) tổ chức sạch, kiểm tra chặt prefix `apply_chat_template`, kiểm `Draft202012Validator` trên 100% mẫu, tách riêng khỏi `src/` và không kéo dependencies nặng (`torch`/`trl`/`peft`) vào `pyproject.toml` hay runtime container.
   - **Security:** `configs/qwen3_5_9b.toml` và `finetuning` dùng `trust_remote_code = false` (tốt); `tar.extractall(..., filter="data")` an toàn trước path traversal; không phát hiện secret lọt vào code/diff.
   - **Nit ở `finetuning/modal_finetune.py:131-133`:** `prepare_on_modal_cpu` xóa `out_dir` khi `resolved` đổi, trong khi `finetune_on_modal_gpu` kiểm tra `run_identity.json` trước khi cho resume — hành vi hợp lý, nên giữ nguyên.

---

## 4. Kế hoạch hành động khuyến nghị theo thứ tự ưu tiên

1. **Sửa ngay 3 lỗi `Critical`:**
   - Sửa `list(...)` tại [`src/datamate/ingestion/ingestion/preparation.py:337-350`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/ingestion/ingestion/preparation.py#L337-L350) và chạy kiểm thử dựng bundle lại trên `biz_101`, `biz_113`, `dev_001`.
   - Khôi phục `enable_thinking = true` trong [`configs/qwen3_5_9b.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b.toml) (hoặc chốt rõ policy mới và cập nhật test) để `pytest` xanh 100%.
   - Xóa code debug trong [`main.py`](file:///home/kiet97/uit-last-dance-aizalo26/main.py).
2. **Hoàn thiện độ phủ test & sửa bug nhỏ (`Required`):**
   - Bổ sung `tests/test_voting.py` và unit test cho `readers._family()` + `preparation.py` (`unit_conversions`).
   - Sửa truyền sampling kwargs trong `OpenAICompatibleLLM.chat()` ([`scripts/run_pipeline.py:100-104`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/run_pipeline.py#L100-L104)) và siết regex trong `readers._family()`.
   - Sửa ghi `grounding_trace.jsonl` cho `batch_size=1` trong [`src/datamate/pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py).
3. **Smoke test GPU trên Modal trước khi tích hợp LoRA:**
   - Chạy thử `modal run scripts/modal_run_pipeline.py --split train --limit 10 --voting` để xác nhận vLLM `language_model_only=True` + chuyển đổi `enable_thinking` vòng 1/vòng 2 + `ReasoningConfig` chạy trơn tru trên GPU thật.
   - Sau đó mới thực hiện bước tích hợp prompt `planner.v1.2` + LoRA adapter `v1_2_a100_80gb` để benchmark PA trên 276 câu Validation.
