# Báo Cáo Thay Đổi & Hồ Sơ Quyết Định Kiến Trúc (ADR-015): Đồng Bộ Thư Mục `models/`, Bù Ngữ Cảnh `prompt_v1_2`, Config `[voting]` & Mặc Định LoRA + Voting

> **Tài liệu:** [`docs/change/MODEL_SYNC_AND_CONFIG_VOTING_CHANGELOG.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/change/MODEL_SYNC_AND_CONFIG_VOTING_CHANGELOG.md)  
> **Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
> **Phạm vi tác động:** `.gitignore`, `configs/`, `models/`, `src/datamate/`, `scripts/`, `finetuning/`, `predict.sh`, `entrypoint.sh`, `tests/`  
> **Kế hoạch tham chiếu:** [`tasks/v1_2_sync_config_plan.md`](file:///home/kiet97/uit-last-dance-aizalo26/tasks/v1_2_sync_config_plan.md), [`tasks/v1_2_sync_config_todo.md`](file:///home/kiet97/uit-last-dance-aizalo26/tasks/v1_2_sync_config_todo.md)  
> **Trạng thái:** **Accepted & Verified on CPU Suite (`505 passed, 3 skipped, 15 subtests passed` — GPU end-to-end inference chưa chạy trên thiết bị GPU)**

---

## 1. Bối Cảnh & Động Lực (Context & Motivation)

Sau [`ADR-014`](file:///home/kiet97/uit-last-dance-aizalo26/docs/change/SFT_V1_2_VOTING_INTEGRATION_CHANGELOG.md), rà soát kiến trúc cho thấy 4 điểm cần chuẩn hóa để hệ thống sạch, đồng bộ và không đánh rơi ngữ nghĩa:

1. **Phân mảnh đường dẫn weights giữa các mô hình & môi trường:** LoRA adapter từng nằm trong `artifacts/finetuning/...`, 2 base model (Qwen3.5-9B & Qwen2.5-3B) trỏ tới `.models/` không có trong `.gitignore`, trong khi [`Dockerfile`](file:///home/kiet97/uit-last-dance-aizalo26/Dockerfile#L41) lại chỉ `COPY models/ /code/models/`.
2. **Thiếu thông tin ngữ nghĩa trong `prompt_v1_2`:** [`src/datamate/planner/prompt_v1_2.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/prompt_v1_2.py) chưa đưa `semantic_catalog` (`metrics`, `suggested_joins`, `unit_conversions`, `unsupported_capabilities`) và `answerability_constraints` vào prompt; đồng thời runtime Grounding gửi `grounded_hint` dạng Markdown dài trong khi SFT `v1.2` được huấn luyện theo định dạng JSON.
3. **Tham số Voting bị hardcode ở runner:** Trước đây `load_config()` chỉ chấp nhận `[model]` và `[generation]`, khiến mặc định voting bị lặp lại cứng trong `run_pipeline.py`, `modal_run_pipeline.py` và `predict.sh`.
4. **Một số entrypoint phụ còn trỏ config cũ:** [`entrypoint.sh`](file:///home/kiet97/uit-last-dance-aizalo26/entrypoint.sh) và [`src/datamate/planner/inference.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/inference.py) vẫn mặc định `configs/qwen3_5_9b.toml`.

---

## 2. Các Quyết Định Kiến Trúc (ADR-015)

### Quyết định 1: Quy hoạch thống nhất toàn bộ weights phục vụ inference về `models/`
- Di chuyển LoRA adapter từ `artifacts/finetuning/v1_2_a100_80gb/train/adapter-final/` sang [`models/adapters/qwen3_5_9b_v1_2/`](file:///home/kiet97/uit-last-dance-aizalo26/models/adapters/qwen3_5_9b_v1_2), giữ `artifacts/` thuần cho nhật ký/metrics/output thực nghiệm.
- Cập nhật [`configs/qwen3_5_9b.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b.toml), [`configs/qwen2_5_3b_grounding.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen2_5_3b_grounding.toml), [`configs/qwen3_5_9b_ft_v1_2.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b_ft_v1_2.toml), [`scripts/download_model.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/download_model.py) và [`finetuning/merge_lora.py`](file:///home/kiet97/uit-last-dance-aizalo26/finetuning/merge_lora.py) dùng chung cấu trúc `models/Qwen3.5-9B`, `models/Qwen2.5-3B-Instruct`, `models/adapters/qwen3_5_9b_v1_2` và `models/qwen3_5_9b_ft_v1_2`.
- Thêm `models/*` + `!models/.gitkeep` và `.models/` vào [`.gitignore`](file:///home/kiet97/uit-last-dance-aizalo26/.gitignore) để weights nặng không bị push lên Git nhưng vẫn tương thích `COPY models/ /code/models/` trong `Dockerfile`.

### Quyết định 2: Bù ngữ nghĩa thiếu vào `context.relations` / `context.rules` và dùng `compact_json` cho `grounded_hint`
- Giữ nguyên schema JSON `planner.v1.2-input.1` (`question`, `as_of_date`, `context.{schema, relations, rules, date_context}`, `industry`, `grounded_hint`, `retry`) để không lệch phân phối SFT:
  - `_build_relations()` nối thêm `semantic_catalog.suggested_joins` (loại trùng với `join_graph`, đánh dấu `status="suggested"`).
  - `_append_semantic_and_constraint_rules()` chuyển hóa `semantic_catalog.metrics` (`SEM_METRIC_<id>`), `name_suffix_match` joins (`SEM_JOIN_SUFFIX_<idx>`), `unit_conversions` (`SEM_UNIT_CONVERSIONS`), `unsupported_capabilities` (`CONSTRAINT_UNSUPPORTED`) và `answerability_constraints` (`CONSTRAINT_ANSWERABILITY`) thành các `{id, text}` khử trùng trong `context.rules`.
- Bổ sung [`GroundingToPlannerAdapter.format_grounded_hint_for_v1_2()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/adapters.py#L461-L518) xuất JSON gọn với khoảng thời gian nửa mở `[start_inclusive, end_exclusive)` khớp quy ước prompt SFT, kết hợp `_normalize_grounded_hint()` giúp `payload["grounded_hint"]` thành JSON object sạch (không lồng chuỗi escape).
- Thêm trường `grounded_hint_mode: Literal["auto", "markdown", "compact_json", "off"] = "auto"` vào [`ModelConfig`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/types.py#L94) và đặt `grounded_hint_mode = "compact_json"` làm mặc định trong `configs/qwen3_5_9b_ft_v1_2.toml` (có cờ `--grounded-hint-mode off` khi muốn A/B với `grounded_hint = null`).

### Quyết định 3: Đưa section `[voting]` vào TOML config và dùng làm nguồn mặc định cho mọi runner
- Mở rộng [`src/datamate/planner/config.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/config.py) hỗ trợ section tùy chọn `[voting]`, giữ nguyên 2-tuple của `load_config()` (đồng thời vẫn validate `[voting]` ngay khi đọc) và bổ sung [`load_pipeline_config()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/config.py#L57-L71) trả `(ModelConfig, GenerationOptions, VotingConfig)`.
- Khai báo `[voting]` trực tiếp trong `configs/qwen3_5_9b_ft_v1_2.toml` (`enabled=true, rounds=1, initial_candidates=4, threshold=0.5, temperature=0.5, thinking_mode="always_off"`) và `configs/qwen3_5_9b.toml` (`enabled=true, rounds=2, initial_candidates=4, threshold=0.5, temperature=0.7, thinking_mode="two_round"`).
- Chuyển các tham số voting CLI trên [`scripts/run_pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/run_pipeline.py), [`scripts/modal_run_pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/modal_run_pipeline.py) và [`predict.sh`](file:///home/kiet97/uit-last-dance-aizalo26/predict.sh) sang cơ chế `None`/override: khi không truyền cờ, mọi runner đọc mặc định LoRA + Voting từ TOML (`configs/qwen3_5_9b_ft_v1_2.toml`), và đổi cấu hình `--config configs/qwen3_5_9b.toml` sẽ tự động chuyển đồng bộ cả model lẫn chiến lược voting.
- Cập nhật cả [`entrypoint.sh`](file:///home/kiet97/uit-last-dance-aizalo26/entrypoint.sh#L17) và [`src/datamate/planner/inference.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/inference.py#L15) dùng `configs/qwen3_5_9b_ft_v1_2.toml` làm mặc định.

---

## 3. Danh Sách Tệp Thay Đổi

- [`.gitignore`](file:///home/kiet97/uit-last-dance-aizalo26/.gitignore): Ignore `models/*` (trừ `!models/.gitkeep`) và `.models/`.
- [`models/adapters/qwen3_5_9b_v1_2/`](file:///home/kiet97/uit-last-dance-aizalo26/models/adapters/qwen3_5_9b_v1_2): Di chuyển từ `artifacts/finetuning/v1_2_a100_80gb/train/adapter-final/`.
- [`configs/qwen3_5_9b_ft_v1_2.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b_ft_v1_2.toml), [`configs/qwen3_5_9b.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b.toml), [`configs/qwen2_5_3b_grounding.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen2_5_3b_grounding.toml): Đồng bộ path `../models/...`, bổ sung `[voting]` và `grounded_hint_mode`.
- [`src/datamate/planner/types.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/types.py), [`src/datamate/planner/config.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/config.py), [`src/datamate/planner/__init__.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/__init__.py): Thêm `grounded_hint_mode` và `load_pipeline_config()`.
- [`src/datamate/planner/prompt_v1_2.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/prompt_v1_2.py), [`src/datamate/grounding/adapters.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/adapters.py), [`src/datamate/planner/generator.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/generator.py), [`src/datamate/pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py): Bù ngữ nghĩa `semantic_catalog` / `answerability_constraints`, bổ sung `format_grounded_hint_for_v1_2()` (`compact_json`) và `grounded_hint_mode`.
- [`scripts/download_model.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/download_model.py), [`finetuning/merge_lora.py`](file:///home/kiet97/uit-last-dance-aizalo26/finetuning/merge_lora.py), [`scripts/run_pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/run_pipeline.py), [`scripts/modal_run_pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/modal_run_pipeline.py), [`predict.sh`](file:///home/kiet97/uit-last-dance-aizalo26/predict.sh), [`entrypoint.sh`](file:///home/kiet97/uit-last-dance-aizalo26/entrypoint.sh), [`src/datamate/planner/inference.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/inference.py): Đồng bộ thư mục `models/`, đọc `[voting]` từ TOML và mặc định LoRA + Voting.
- [`tests/test_planner_v1_2.py`](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_planner_v1_2.py): Kiểm thử `[voting]` TOML, enrichment `prompt_v1_2`, `compact_json` / `off` `grounded_hint_mode`, và chuyển config + CLI override end-to-end (mock LLM).

---

## 4. Kết Quả Kiểm Thử Sau Chỉnh Sửa Cuối

- `source .venv/bin/activate && pytest -rs -q`: **`505 passed, 3 skipped, 15 subtests passed`** (`23.76s`).
  - 3 test bị skip do điều kiện file/biến môi trường ngoài repo: [`tests/test_real_sample.py`](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_real_sample.py#L23) (`train.zip not found in workspace`), [`tests/test_train_smoke.py`](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_train_smoke.py#L90) và [`tests/test_train_smoke.py`](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_train_smoke.py#L153) (`set DATAMATE_TRAIN_DIR for real-data smoke tests`).
- `python -m compileall -q src scripts main.py finetuning`: **pass (exit code `0`)**.
- `bash -n predict.sh entrypoint.sh`: **pass (exit code `0`)**.
- `modal run scripts/modal_run_pipeline.py --help`, `python finetuning/merge_lora.py --help`, `python scripts/download_model.py --help`: **pass (exit code `0`)**.
- `git check-ignore -v models/adapters/qwen3_5_9b_v1_2/adapter_model.safetensors`: khớp rule `.gitignore:29:models/*` (trong khi `models/.gitkeep` không bị ignore).
- **Giới hạn xác minh:** Các bài test trên chạy trên CPU với LLM giả lập (mock `VLLMModel`/`BaseLLM`); inference GPU thật với `vLLM` và đánh giá validation chưa chạy.
