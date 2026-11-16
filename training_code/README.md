# Training Code & Model Declarations - DataMate 2026

**Team:** UIT Last Dance (`zaic2026_datamate_uit_last_dance:final`)

## 1. Training Status & Strategy Declaration (Section 8 Compliance)

Giải pháp **DataMate** của đội **UIT Last Dance** sử dụng kiến trúc suy luận 2 pha trên từng GPU:
- **Phase 1 — Semantic Grounding (`Qwen/Qwen2.5-3B-Instruct`, 3.09B params, unmodified weights)**: trích xuất verbatim mentions, ý định (C1), mốc thời gian (C2) và liên kết nghiệp vụ (contract v3) trong subprocess riêng rồi giải phóng 100% VRAM.
- **Phase 2 — Text-to-SQL Planner (`Qwen/Qwen3.5-9B`, 8.99B total incl. LoRA v1.2, voting k=4)**: kết hợp base model **BF16** (`Qwen3_5ForCausalLM`, commit SHA `c202236235762e1c871ad0ccb60c8ee5ba337b9a`) với **PEFT LoRA adapter `v1.2`** (`/code/models/adapters/qwen3_5_9b_v1_2`, `40,108,032` trainable params = `0.4459%`) sinh structured JSON (`Plan + DuckDB SQL`), thực thi trong sandbox DuckDB có retry sửa lỗi và thẩm định qua Proof-Driven Risk Gate (Aggressive Abstain).
- **Tổng tham số suy luận**: `8.99B + 3.09B = ~12.08B <= 15B` (tuân thủ giới hạn Rule 2).

### Khai báo dữ liệu & quy trình SFT (Rule 6 Compliance)
- **Dữ liệu huấn luyện**: `2,448` mẫu chuẩn hóa `train_v1_2.jsonl` (`planner.v1.2`, `25,130,728` input tokens), được xây dựng hoàn toàn từ **24 doanh nghiệp thuộc tập `train` chính thức** và xác thực 100% **Level-2 Schema (`planner_output.schema.json`)** + **Level-3 DuckDB Execution (`verified_l3 = 2,448 / 2,448`)**.
- **Chống rò rỉ dữ liệu**: Tập train (`2,448`), validation (`276`) và holdout (`276`) được phân tách rời hoàn toàn theo `business_id`. **Không** sử dụng bất kỳ mẫu nào từ `public_test` hoặc `private_test`.
- **Kết quả huấn luyện thực tế (1 epoch trên NVIDIA A100-SXM4-80GB)**:
  - `optimizer_steps = 306` (`micro_batch = 2`, `accumulation = 4`, effective batch = 8, `max_length = 20,000`, `lr = 1e-4`, `r = 16`, `lora_alpha = 32`)
  - `train_loss = 0.0343`, `mean_token_accuracy = 0.9958`, `wall_seconds = 12,840.38s`, `peak_allocated_gib = 41.29 GiB`.

## 2. Directory Structure

```text
training_code/
├── README.md                  # Tài liệu khai báo huấn luyện & thông số LoRA v1.2
├── requirements.txt           # Dependencies SFT (lock đầy đủ tại logs/datamate-train-requirements.lock)
├── train.sh                   # Entrypoint tái lập lại pha SFT LoRA v1.2
├── data_manifest.json         # Manifest model URLs, revision, release dates, licenses & SHA-256
├── configs/                   # Kế hoạch SFT, JSON Schema v1.2 và Inference TOML configs
│   ├── PLAN.md
│   ├── planner_output.schema.json
│   ├── qwen3_5_9b_ft_v1_2.toml
│   └── qwen2_5_3b_neo_grounding.toml
├── src/                       # Mã nguồn huấn luyện & merge LoRA
│   ├── train_datamate.py
│   ├── modal_finetune.py
│   └── merge_lora.py
├── data_generation/           # Snapshot prompt contract & manifest thống kê tổng hợp SFT v1.2
│   ├── README.md
│   ├── prompt_v1_2.py
│   └── manifest_v1_2.json
├── data/                      # Tập SFT v1.2 đầy đủ (train_v1_2.jsonl, manifest, schema, splits) được Docker copy vào
├── logs/                      # Metrics, run_identity, trainer_state & benchmark suite JSONs
└── checkpoints/               # Khai báo checkpoint LoRA v1.2 (/code/models/adapters/qwen3_5_9b_v1_2)
```

## 3. Reproduction & Execution

Kiểm tra dataset và tái lập quá trình huấn luyện LoRA `v1.2`:
```bash
# 1. Cài đặt môi trường training (trên GPU CUDA 12.8+, Python 3.12)
pip install -r /code/training_code/requirements.txt

# 2. Chạy bước prepare (CPU) để kiểm định token & schema không tốn GPU
TRAIN_MODE=prepare bash /code/training_code/train.sh

# 3. Chạy huấn luyện SFT 1 epoch trên GPU
bash /code/training_code/train.sh
```
