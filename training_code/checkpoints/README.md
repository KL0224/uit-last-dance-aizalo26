# Trained LoRA Checkpoint Declaration (`qwen3_5_9b_v1_2`)

LoRA adapter cuối cùng từ quá trình huấn luyện `train_datamate.py` trên NVIDIA A100-SXM4-80GB được lưu trực tiếp cho inference tại:
- Trong repo nguồn: `models/adapters/qwen3_5_9b_v1_2/`
- Trong Docker container: `/code/models/adapters/qwen3_5_9b_v1_2/`

## Checksums & Hyperparameters đã kiểm chứng
- Base model: `Qwen/Qwen3.5-9B` (commit revision pin: `c202236235762e1c871ad0ccb60c8ee5ba337b9a`)
- `adapter_model.safetensors`: SHA-256 `7daa40cf202860f0fcd00d380fdba678c5e31eff65c83d89f5be614156a2ebcd` (`160,486,456` bytes)
- `adapter_config.json`: SHA-256 `6cda6068de7579d82083edeca109961fbbe158c60e6fcd7c173a083f4f9bbbad` (`r=16`, `lora_alpha=32`, `lora_dropout=0.05`, `peft_version=0.21.3`)
- Target modules (10 loại lớp chiếu trên 32 transformer blocks):
  `q_proj`, `k_proj`, `v_proj`, `o_proj`, `in_proj_qkv`, `in_proj_z`, `out_proj`, `gate_proj`, `up_proj`, `down_proj`
- Quy mô tham số sau gắn LoRA: `40,108,032` trainable (`0.4459%`) / `8,993,911,296` total.
- Tùy chọn merge standalone weights (nếu cần phục vụ với `--no-lora`): xem `training_code/src/merge_lora.py`.
