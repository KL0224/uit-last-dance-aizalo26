# Báo Cáo Thay Đổi & Hồ Sơ Quyết Định Kiến Trúc (ADR-014): Tích Hợp Qwen3.5-9B Fine-Tuned (`planner.v1.2`) Với Voting 1 Vòng

> **Tài liệu:** [`docs/change/SFT_V1_2_VOTING_INTEGRATION_CHANGELOG.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/change/SFT_V1_2_VOTING_INTEGRATION_CHANGELOG.md)  
> **Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
> **Phạm vi tác động:** `configs/`, `src/datamate/`, `scripts/`, `finetuning/`, `predict.sh`, `tests/`  
> **Kế hoạch tham chiếu:** [`tasks/sft_voting_integration_plan.md`](file:///home/kiet97/uit-last-dance-aizalo26/tasks/sft_voting_integration_plan.md), [`tasks/sft_voting_integration_todo.md`](file:///home/kiet97/uit-last-dance-aizalo26/tasks/sft_voting_integration_todo.md)  
> **Trạng thái:** **Accepted & Verified on CPU Suite (`502 passed, 3 skipped, 15 subtests passed` — GPU end-to-end inference chưa chạy trên thiết bị GPU)**

---

## 1. Bối Cảnh & Động Lực (Context & Motivation)

Mô hình Qwen3.5-9B vừa được fine-tune LoRA bằng dữ liệu SFT theo hợp đồng **`planner.v1.2`** (`artifacts/finetuning/v1_2_a100_80gb/train/adapter-final`) với chế độ **non-thinking** (`enable_thinking=false`). Trước khi tích hợp:

1. **Lệch hợp đồng prompt/output:** `src/datamate/planner/` mặc định dùng legacy Markdown/SQL prompt (`prompt.py`), chưa hỗ trợ system prompt chuẩn hóa `planner.v1.2-sys.1`, JSON input schema `planner.v1.2-input.1`, trường `structured_plan`, trạng thái `needs_more_context`, và đối tượng `retry` có cấu trúc khi repair.
2. **Chiến lược voting 2 vòng gắn cứng thinking ở vòng 2:** `VotingConfig` và `run_voting()` mặc định chạy tối đa 2 vòng và ép `enable_thinking = (round_id == 2)`. Với mô hình SFT không bật thinking, vòng 2 bật thinking gây lệch phân phối huấn luyện, trong khi chạy lại 1 lần nữa cùng model non-thinking với cùng prompt sẽ trùng lặp chi phí không cần thiết.
3. **Thiếu cơ chế cấu hình tách LoRA và chuyển đổi Base vs SFT:** `ModelConfig` và `VLLMModel` chỉ nạp snapshot đầy đủ qua `model_path`; `scripts/run_pipeline.py`, `scripts/modal_run_pipeline.py` và `predict.sh` gắn cứng `configs/qwen3_5_9b.toml` (Base model `enable_thinking = true`), riêng `scripts/modal_run_pipeline.py` trước đây đặt mặc định `enable_thinking: bool = True` ghi đè cấu hình TOML.

---

## 2. Các Quyết Định Kiến Trúc (ADR-014)

### Quyết định 1: Duy trì 2 file cấu hình song song, đặt `v1.2` làm mặc định thực thi ở runner
- **Lựa chọn đã chốt:**
  - Giữ nguyên [`configs/qwen3_5_9b.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b.toml) cho Base model (`prompt_format = "legacy"`, `lora_path = None`, `enable_thinking = true`, `thinking_token_budget = 4096`).
  - Thêm mới [`configs/qwen3_5_9b_ft_v1_2.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b_ft_v1_2.toml) cho SFT model (`prompt_format = "v1_2"`, `lora_path = "../artifacts/finetuning/v1_2_a100_80gb/train/adapter-final"`, `max_lora_rank = 16`, `enable_thinking = false`, `temperature = 0.5`, `top_p = 0.8`, `top_k = 20`, `repetition_penalty = 1.05`, `presence_penalty = 0.0`, `seed = 42`).
  - Đặt mặc định tại [`scripts/run_pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/run_pipeline.py), [`scripts/modal_run_pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/modal_run_pipeline.py) và [`predict.sh`](file:///home/kiet97/uit-last-dance-aizalo26/predict.sh) sử dụng `configs/qwen3_5_9b_ft_v1_2.toml`.
  - Đổi mặc định `enable_thinking` trong `scripts/modal_run_pipeline.py` từ `True` sang `None` để tôn trọng `chat_template_kwargs.enable_thinking` trong file TOML trừ khi người dùng truyền cờ `--enable-thinking` / `--no-enable-thinking`.
- **Phương án thay thế đã cân nhắc:**
  - *Chỉ dùng 1 file `qwen3_5_9b_ft_v1_2.toml` và xóa config gốc:* Từ chối vì sẽ phá vỡ test contract `tests/test_thinking_budget_diagnostics.py` và mất đường fallback/A-B test nhanh về Base thinking model.
  - *Sửa đè trực tiếp `configs/qwen3_5_9b.toml`:* Từ chối vì dễ gây nhầm lẫn khi đối chiếu giữa Base và LoRA fine-tuned.
- **Hệ quả:** Có thể A/B hoặc rollback tức thì qua `--config configs/qwen3_5_9b.toml --no-lora`, trong khi mọi lệnh chạy mặc định đều kích hoạt SFT `v1.2`.

### Quyết định 2: Voting 1 vòng (`rounds=1`, `k=4`, `threshold=0.5`, `temperature=0.5`, `thinking_mode="always_off"`)
- **Lựa chọn đã chốt:**
  - Mở rộng [`VotingConfig`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/voting.py) thêm `rounds: int = 2` (`1 | 2`) và `thinking_mode: Literal["two_round", "always_off", "always_on", "inherit"] = "two_round"`.
  - Giữ mặc định thư viện (`VotingConfig()`, `Text2SQLGenerator()`, `DataMatePipeline()`) tương thích ngược với code/test cũ, đồng thời cấu hình mặc định tại runner CLI/Modal/`predict.sh` là: `voting=True`, `voting_rounds=1`, `voting_candidates=4`, `voting_threshold=0.5`, `voting_temperature=0.5`, `voting_thinking_mode="always_off"`.
  - Ở chế độ `always_off`, `VotingConfig.options()` luôn ép `enable_thinking=False`, `thinking_token_budget=None`, giữ `temperature=0.5` và biến thiên `seed` theo batch index để tạo đa dạng có kiểm soát giữa 4 candidates. Nếu sau vòng 1 không có kết quả đạt ngưỡng (`>= 2/4` phiếu đồng thuận), hệ thống kết luận `VOTING_THRESHOLD_NOT_MET` (`next_action="abstain"`).
- **Phương án thay thế đã cân nhắc:**
  - *Tắt hoàn toàn voting (`k=1`):* Rủi ro chọn nhầm 1 lần sinh lỗi biên hoặc câu hỏi mơ hồ gây phạt điểm PA.
  - *Voting 2 vòng (`rounds=2`) trên cùng model SFT non-thinking:* Không bổ sung mô hình suy luận khác ở vòng 2, chỉ tăng chi phí gấp đôi.
- **Hệ quả:** Giảm độ trễ và lượng token tiêu thụ so với 2 vòng thinking mà vẫn giữ được màng lọc đồng thuận kết quả thực thi DuckDB.

### Quyết định 3: Tách Base + LoRA qua `lora_path` (`LoRARequest`) kèm công cụ merge dự phòng
- **Lựa chọn đã chốt:**
  - Mở rộng `ModelConfig` ([`src/datamate/planner/types.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/types.py)), `load_config()` ([`src/datamate/planner/config.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/config.py)) và `VLLMModel` ([`src/datamate/planner/vllm_model.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/vllm_model.py)) để nạp LoRA runtime (`enable_lora=True`, `max_lora_rank=self.config.max_lora_rank`, `LoRARequest("datamate_lora", 1, ...)`), kèm fail-fast khi thiếu `adapter_config.json`.
  - Bổ sung `--lora-path` và `--no-lora` trên CLI/Modal/`predict.sh` để bật/tắt adapter linh hoạt.
  - Viết [`finetuning/merge_lora.py`](file:///home/kiet97/uit-last-dance-aizalo26/finetuning/merge_lora.py) sử dụng PEFT `merge_and_unload()` làm đường dự phòng hoặc khi đóng gói snapshot merged standalone (ví dụ cho Docker `models/qwen3_5_9b_ft_v1_2`, nơi [`predict.sh`](file:///home/kiet97/uit-last-dance-aizalo26/predict.sh) tự động nhận diện và truyền `--no-lora`).
- **Hệ quả:** Không phải nhân bản thêm bản sao ~18 GB weights cho riêng giai đoạn thử nghiệm; vẫn sẵn sàng xuất weights hợp nhất khi triển khai độc lập.

### Quyết định 4: Chuẩn hóa `planner.v1.2` và xử lý `needs_more_context` trong bounded retry
- **Lựa chọn đã chốt:**
  - Đóng gói prompt chuẩn SFT vào [`src/datamate/planner/prompt_v1_2.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/prompt_v1_2.py) (`SYSTEM_PROMPT_V1_2`, `build_v1_2_user_payload()`, `build_v1_2_messages()`, `build_v1_2_repair_messages()`), khớp parity bảng/quan hệ/quy tắc/`date_context` từ `BusinessContext` bundle.
  - Mở rộng `Text2SQLResult`, `parse_text2sql_response()` ([`src/datamate/planner/parser.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/parser.py)) hỗ trợ `status = "needs_more_context"`, `structured_plan`, `requested_context`, và fallback `extract_tables_from_sql(sql)` khi JSON v1.2 không liệt kê `tables_used`.
  - Trong `DataMatePipeline._evaluate_attempt_unsafe()` ([`src/datamate/pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py)): khi model trả `status == "needs_more_context"`, nếu `attempt < max_retries` sẽ phát `GateAction.RETRY` (`ErrorCode.MISSING_EVIDENCE`) nhắc model rằng toàn bộ `context.schema`, quan hệ và quy tắc đã được cung cấp đầy đủ; nếu hết ngân sách retry thì chuyển sang `ABSTAIN` (`ErrorCode.RETRY_EXHAUSTED`).
  - Truyền đầy đủ `previous_plan`, `error_code`, `failed_checks` qua `Text2SQLGenerator`, `DataMatePipeline`, và `run_voting()`.

---

## 3. Danh Sách Tệp Thay Đổi & Bổ Sung

| Thành phần | Tệp | Tóm tắt thay đổi |
| :--- | :--- | :--- |
| Config SFT mới | [`configs/qwen3_5_9b_ft_v1_2.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b_ft_v1_2.toml) | Khai báo `prompt_format = "v1_2"`, `lora_path`, `enable_thinking = false`, `temperature = 0.5`, `seed = 42`. |
| Config Base | [`configs/qwen3_5_9b.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b.toml) | Giữ nguyên cho Base thinking model (`enable_thinking = true`, `thinking_token_budget = 4096`). |
| Voting Engine | [`src/datamate/voting.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/voting.py) | Thêm `rounds`, `thinking_mode`, cập nhật `options()` và `run_voting()` (kèm propagation `previous_plan`, `error_code`, `failed_checks`). |
| Prompt v1.2 | [`src/datamate/planner/prompt_v1_2.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/prompt_v1_2.py) | Module mới cài đặt `SYSTEM_PROMPT_V1_2`, `build_v1_2_user_payload`, `build_v1_2_messages`, `build_v1_2_repair_messages`. |
| Kiểu & Config | [`src/datamate/planner/types.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/types.py), [`src/datamate/planner/config.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/config.py) | Thêm `prompt_format`, `lora_path`, `max_lora_rank`, `structured_plan`, `requested_context`, `status="needs_more_context"`. |
| Parser & Generator | [`src/datamate/planner/parser.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/parser.py), [`src/datamate/planner/generator.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/generator.py) | Parse schema v1.2, định tuyến `prompt_format` (`legacy`/`v1_2`) và xây dựng `retry` object có cấu trúc. |
| vLLM Engine & Merge | [`src/datamate/planner/vllm_model.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/vllm_model.py), [`finetuning/merge_lora.py`](file:///home/kiet97/uit-last-dance-aizalo26/finetuning/merge_lora.py) | Hỗ trợ `enable_lora`, `max_lora_rank`, `LoRARequest` trong `VLLMModel` và script CLI `merge_lora.py`. |
| Pipeline Orchestrator | [`src/datamate/pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py) | Xử lý retry/abstain cho `needs_more_context` và truyền `previous_plan` vào repair batch. |
| Runners | [`scripts/run_pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/run_pipeline.py), [`scripts/modal_run_pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/modal_run_pipeline.py), [`predict.sh`](file:///home/kiet97/uit-last-dance-aizalo26/predict.sh) | Mặc định chạy `configs/qwen3_5_9b_ft_v1_2.toml` + voting 1 vòng (`k=4`, `threshold=0.5`, `temp=0.5`, `always_off`). |
| Tests | [`tests/test_planner_v1_2.py`](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_planner_v1_2.py), [`tests/test_voting.py`](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_voting.py) | Bộ test TDD kiểm tra SHA-256 prompt, parity `biz_103`, parser 3 trạng thái, repair `retry`, LoRA config/vLLM mock, voting 1 vòng và defaults của cả 3 runner. |

---

## 4. Hướng Dẫn Sử Dụng & Chuyển Đổi Cấu Hình

1. **Chạy mặc định (Fine-tuned `v1.2` + 1-round voting `k=4`, `threshold=0.5`, `temp=0.5`, non-thinking):**
   ```bash
   # Local / Server CLI
   python scripts/run_pipeline.py --split-dir data/val --bundles-dir artifacts/b01_b02_full/enriched_bundles --output-dir artifacts/runs/val_v1_2

   # Modal GPU
   modal run scripts/modal_run_pipeline.py --split train --limit 10

   # Submission wrapper
   bash predict.sh --input-dir /data/input --output-dir /data/output
   ```
2. **Chuyển sang Base thinking model khi cần A/B hoặc rollback:**
   ```bash
   python scripts/run_pipeline.py \
     --config configs/qwen3_5_9b.toml \
     --no-lora \
     --enable-thinking \
     --voting-rounds 2 \
     --voting-temperature 0.7 \
     --voting-thinking-mode two_round
   ```
3. **Merge LoRA thành weights độc lập (dự phòng hoặc đóng gói Docker):**
   ```bash
   python finetuning/merge_lora.py \
     --base-model Qwen/Qwen3.5-9B \
     --adapter-dir artifacts/finetuning/v1_2_a100_80gb/train/adapter-final \
     --output-dir models/qwen3_5_9b_ft_v1_2
   ```

---

## 5. Kết Quả Kiểm Thử & Giới Hạn Xác Minh (Verification & Limitations)

Các lệnh kiểm thử được chạy trực tiếp trong `.venv` sau lần chỉnh sửa code cuối cùng:

- **`source .venv/bin/activate && pytest -rs -q`**: **`502 passed, 3 skipped, 15 subtests passed` (`23.88s`)**.
  - 3 test bị skip theo điều kiện môi trường dữ liệu có sẵn trong repo: `tests/test_real_sample.py:23` (`train.zip not found in workspace`), `tests/test_train_smoke.py:90` và `tests/test_train_smoke.py:153` (`set DATAMATE_TRAIN_DIR for real-data smoke tests`).
- **`python -m compileall -q src scripts main.py finetuning`**: exit code `0`.
- **`bash -n predict.sh entrypoint.sh`**: exit code `0`.
- **`modal run scripts/modal_run_pipeline.py --help`**: exit code `0` (xác nhận parse đầy đủ cờ `--config`, `--lora-path`, `--no-lora`, `--prompt-format`, `--voting / --no-voting`, `--voting-rounds`, `--voting-thinking-mode`, `--enable-thinking / --no-enable-thinking`).
- **`python finetuning/merge_lora.py --help`**: exit code `0`.

> [!NOTE]
> Toàn bộ kiểm thử trên được xác minh trên môi trường CPU với `VLLMModel`/`BaseLLM` giả lập (mock) và dữ liệu thật tại `data/train/data/biz_103` & `data/finetuning/`. Quá trình nạp weights thật `Qwen/Qwen3.5-9B` + LoRA adapter `adapter-final` bằng `vLLM` trên GPU và đánh giá chất lượng trên tập validation **chưa được thực thi** theo đúng phạm vi yêu cầu hiện tại. Khi sẵn sàng kiểm chứng GPU thực tế, khuyến nghị chạy smoke-test nhanh:
> ```bash
> modal run scripts/modal_run_pipeline.py --split train --limit 3
> ```
