# Kế hoạch Fine-Tune DataMate Qwen3.5-9B BF16 LoRA trên Modal (A100-80GB)

Train `Qwen/Qwen3.5-9B` bằng **Transformers + TRL + PEFT** trên **Modal Serverless GPU (`A100-80GB` mặc định, `$2.50/h`)**.
Lượt đầu huấn luyện **Planner v1.2 (`Plan + SQL`)** ở chế độ **`enable_thinking=False`** trên đủ **`2,448` mẫu** đã kiểm định (`L2 = 2,448/2,448`, `L3 = 0` lỗi, `p50 = 9,403`, `p95 = 16,644`, `max = 17,029`, tổng `25,130,728` tokens trên tokenizer thực tế).

---

## 1. Cấu trúc thư mục chuẩn trong repo

- **Code huấn luyện & Modal runner**: đặt tại `finetuning/` ở thư mục gốc repo (song song với `src/`, `scripts/`, `configs/`), để **Git theo dõi đầy đủ code**.
  - `finetuning/PLAN.md` — Kế hoạch chuẩn hóa cho `SFT_v1_2_final` và Modal.
  - `finetuning/train_datamate.py` — Script train độc lập (hỗ trợ cả GPU local lẫn Modal).
  - `finetuning/modal_finetune.py` — Runner chạy `prepare` trên CPU, `smoke` / `bench` / `train` trên Modal GPU và tải artifact về máy.
- **Dữ liệu huấn luyện**: đặt tại `data/finetuning/` (nằm trong `data/` nên tự động được `.gitignore` bỏ qua, không làm phình lịch sử Git):
  - `data/finetuning/train_v1_2.jsonl` — `2,448` mẫu chuẩn từ `SFT_v1_2_final` (định dạng `{"id", "messages": [system, user, assistant]}`).
  - `data/finetuning/manifest.json` — SHA-256 (`4a5a45275357...`) và siêu dữ liệu bản xuất.
  - `data/finetuning/planner_output.schema.json` — Schema Draft 2020-12 đã đồng bộ `2,448 / 2,448` mẫu (`time_range.periods[*].label` tùy chọn, `order_by` nhận `expression` hoặc `column`, hỗ trợ `not_like`/`not_ilike`).
  - `data/finetuning/splits/{train_ids.json, val_ids.json, holdout_ids.json}` — Tách rời `2,448 / 276 / 276` câu theo `biz_id`.

> **Các lỗi từ bản nháp cũ đã được sửa trong bộ code mới:**
> 1. `train_datamate.py` đọc trực tiếp trường `messages` của `SFT_v1_2_final` (vẫn tương thích ngược `prompt`/`completion`), không còn lỗi `KeyError: 'prompt'`.
> 2. `planner_output.schema.json` pass **100% (`2,448 / 2,448`, `0` lỗi)** thay vì bị chặn `245` mẫu ở schema nháp cũ.
> 3. Guard tham số `revision` ở `get_peft_model` theo chữ ký của phiên bản `peft` thực tế.

---

## 2. Cấu hình khởi điểm & kiến trúc LoRA

| Thành phần | Giá trị | Lý do |
|---|---|---|
| Base model | `Qwen/Qwen3.5-9B`, pin commit SHA `c202236235762e1c871ad0ccb60c8ee5ba337b9a` | Load text-only (`Qwen3_5ForCausalLM`, bỏ `visual.*` và `mtp.*`), giữ base frozen ở BF16 |
| CUDA Kernels | `nvidia/cuda:12.8.1-devel-ubuntu24.04` + `flash-linear-attention` (`>=0.4.2`) + `causal-conv1d` | Mở khóa kernel Gated DeltaNet (`fla=True`, `causal_conv1d=True`), nhanh gấp ~3.5× so với fallback PyTorch (`571.9 tok/s` -> `1,787–2,037 tok/s`) |
| SFT & Loss | `enable_thinking=False`, `completion_only_loss=False`, `loss_type="chunked_nll"` | `train_datamate.py` tự kiểm prefix `apply_chat_template` khớp 100%, mask prompt/pad bằng `-100` |
| Context & Sampler | `max_length=20_000`, `packing=False`, `LengthBucketSampler` (`--group-by-length`) | Giữ trọn `max = 17,029` tokens (`0` mẫu cắt); gom nhóm độ dài giảm padding thừa cho batch 2 (+44.5% tốc độ) |
| Batch & VRAM | `micro_batch=2`, `grad_accum=4`, `gradient_checkpointing=True` | Effective batch = 8 trên 1 GPU (~`306` optimizer updates / 1 epoch), peak `40.73 GiB` allocated / `46.68 GiB` reserved trên `79.27 GiB` |
| LoRA | `r=16`, `alpha=32`, `dropout=0.05`, `bias="none"` | Gắn đủ **8** full-attention (`q,k,v,o_proj`), **24** Gated DeltaNet (`in_proj_qkv,in_proj_z,out_proj`), **32** FFN (`gate,up,down_proj`) |
| Optimizer & LR | `adamw_torch`, `lr=1e-4`, cosine, warmup `3%`, `max_grad_norm=1.0`, `weight_decay=0.0` | Khởi điểm chuẩn cho Qwen3.5 LoRA; chọn checkpoint tốt nhất theo PA trên 276 câu Validation |
| Checkpoint | Lưu mỗi `100` updates (`save_total_limit=4`), commit ngay lên Modal Volume | An toàn resume nếu container Modal bị ngắt giữa chừng |

### Kết quả Benchmark thực nghiệm trên `NVIDIA A100-SXM4-80GB` (48 mẫu / 6 updates + smoke 17K)

| Cấu hình | Flags | Peak Alloc / Reserved | Wall (48 mẫu) | Tok/s (Wall / Steady) | Ước tính 1 Epoch (Wall / Cost @ `$2.50/h`) | Kết luận |
|---|---|---|---|---|---|---|
| **`b2_gc_gbl`** | `--micro-batch 2 --group-by-length` | `40.73 / 46.68 GiB` | **`275.04s`** | **`1,787.12` / `1,943.12`** | **`3.91 giờ` / `$9.77`** | **Tối ưu nhất (Khuyến nghị)** |
| `b1_gc_baseline` | `--micro-batch 1` | `29.01 / 31.53 GiB` | `301.38s` | `1,630.92` / `2,036.93` | `4.28 giờ` / `$10.70` | An toàn dự phòng (VRAM thấp) |
| `b4_gc_gbl` | `--micro-batch 4 --group-by-length` | `64.00 / 73.64 GiB` | `332.65s` | `1,477.59` / `1,486.34` | `4.72 giờ` / `$11.81` | Chậm hơn & sát trần VRAM |
| `b2_gc_random` | `--micro-batch 2` (không bucket) | `40.73 / 46.81 GiB` | `397.48s` | `1,236.60` / `1,511.52` | `5.65 giờ` / `$14.11` | Tốn padding thừa (6.5K pad lên 17K) |
| `b1_nogc` | `--micro-batch 1 --no-gradient-checkpointing` | `> 73.12 GiB` | OOM | — | — | **OOM** (tràn `79.27 GiB` khi không checkpointing) |

---

## 3. Lưu trữ & kiến trúc chạy trên Modal

- **Modal App**: `datamate-finetune` (`finetuning/modal_finetune.py`)
- **Modal Volume**: `datamate-finetune-volume` mount tại `/vol`:
  - `/vol/hf_cache` (`HF_HOME`): cache trọng số `Qwen/Qwen3.5-9B` (~19.3 GB) theo commit SHA đã pin — chỉ tải lần đầu, các lần sau khởi động ngay.
  - `/vol/runs/<run_name>/`: lưu `prepare/`, `smoke-*/`, `bench-*/`, `train/` (`checkpoint-100`, `checkpoint-200`, `adapter-final`, `run_identity.json`, `metrics.json`, `datamate-train-requirements.lock`).
- **Tối ưu chi phí Modal**:
  - `--mode prepare` và `--download-only` chạy trên **CPU container**, không thuê GPU.
  - GPU mặc định là `A100-80GB` (`MODAL_GPU=A100-80GB`, có thể đổi tạm qua biến môi trường `MODAL_GPU=A100` nếu cần chạy bản 40GB với `--micro-batch 1`).
  - Mỗi lần `SFTTrainer` lưu checkpoint (`save_steps=100`), `RunMonitor.on_save` tự gọi `volume.commit()` để bảo toàn trạng thái resume.

---

## 4. Thứ tự lệnh chạy trên Modal

Kích hoạt `.venv` trên máy local trước khi chạy `modal`:

```bash
source .venv/bin/activate
```

### Bước 1: Prepare trên CPU (đã hoàn tất cho `v1_2_a100_80gb`)
```bash
modal run finetuning/modal_finetune.py --mode prepare --run-name v1_2_a100_80gb
```
*Revision đã pin: `c202236235762e1c871ad0ccb60c8ee5ba337b9a` (`2,448` mẫu, `25,130,728` tokens).*

### Bước 2: Bench-suite (đã hoàn tất)
```bash
modal run finetuning/modal_finetune.py --mode bench-suite --run-name v1_2_a100_80gb --revision c202236235762e1c871ad0ccb60c8ee5ba337b9a --download
```
Kết quả JSON đã lưu tại `artifacts/finetuning/v1_2_a100_80gb/bench_suite_summary.json` và `artifacts/finetuning/v1_2_a100_80gb/bench_suite_batch_summary.json`.

### Bước 3: Train chính 1 epoch (cấu hình tối ưu `b2_gc_gbl`) & tải `adapter-final`
```bash
modal run finetuning/modal_finetune.py \
  --mode train \
  --run-name v1_2_a100_80gb \
  --revision c202236235762e1c871ad0ccb60c8ee5ba337b9a \
  --micro-batch 2 \
  --group-by-length \
  --download
```
Nếu run bị ngắt giữa chừng (ví dụ sau khi đã commit `checkpoint-200`), chạy resume đúng cùng `--run-name` và `--revision`:
```bash
modal run finetuning/modal_finetune.py \
  --mode train \
  --run-name v1_2_a100_80gb \
  --revision c202236235762e1c871ad0ccb60c8ee5ba337b9a \
  --micro-batch 2 \
  --group-by-length \
  --resume-checkpoint checkpoint-200 \
  --download
```
Tải lại artifact bất cứ lúc nào trên CPU (không tốn GPU):
```bash
modal run finetuning/modal_finetune.py --download-only --run-name v1_2_a100_80gb
```
Artifact sẽ nằm tại `artifacts/finetuning/v1_2_a100_80gb/train/` (gồm `adapter-final/`, `metrics.json`, `run_identity.json`, `datamate-train-requirements.lock`).

---

## 5. Đánh giá Local CV (276 Validation) & chuyển sang RTX 5090

1. **Bắt buộc khớp prompt khi đánh giá**: Khi chạy baseline `Qwen/Qwen3.5-9B` (`enable_thinking=False`) và chấm `checkpoint-100`, `checkpoint-200`, `adapter-final` trên **276 câu Validation (`biz_111, biz_114, biz_130`)**, phải dựng input bằng đúng `SYSTEM_PROMPT` (`planner.v1.2-sys.1`) và JSON input format (`make_input`) — **không** dùng `SYSTEM_INSTRUCTION` Markdown cũ trong `src/datamate/planner/prompt.py`.
2. **Đo đối chứng hợp lý**: So sánh trực tiếp **`Base OFF` vs `Base ON` vs `Adapter OFF`** trên toàn bộ 276 ID (tính `PA = (correct - wrong) / 276`, không bỏ câu lỗi parse). Không kỳ vọng `Adapter OFF` chạy đẹp ở chế độ `enable_thinking=True` nếu chưa có `<think>` trace trong SFT.
3. **Chốt Holdout & chuyển RTX 5090 (32 GB VRAM)**: Chỉ chạy `276` câu Holdout **1 lần** sau khi chốt adapter + parser + retry policy; giữ nguyên revision base model và khóa lại profile throughput/VRAM trên RTX 5090 với ngân sách 6 giờ.
