# Báo cáo Quy trình & Kết quả Fine-Tuning `Qwen/Qwen3.5-9B` BF16 LoRA (Planner v1.2)

Tài liệu này tổng hợp đầy đủ quy trình kỹ thuật, cấu hình tối ưu, benchmark phần cứng và kết quả huấn luyện thực tế cho mô hình **DataMate Planner v1.2 (`Plan + SQL`)** trên nền tảng **Modal Serverless GPU (`A100-80GB`)**.

---

## 1. Tổng quan & Mục tiêu

- **Mục tiêu**: Huấn luyện `Qwen/Qwen3.5-9B` ở chế độ **`enable_thinking=False`** để sinh cấu trúc JSON (`Plan + SQL`) tuân thủ hợp đồng `planner.v1.2` và `planner_output.schema.json`.
- **Chiến lược mô hình**: Load nhánh text-only (`Qwen3_5ForCausalLM`, loại bỏ nhánh `visual.*` và `mtp.*`), giữ nguyên trọng số base ở **BF16** (đóng băng) và chỉ huấn luyện **LoRA adapter (`r=16`, `alpha=32`)**.
- **Quy mô tham số**:
  - Tham số huấn luyện (LoRA): **`40,108,032`** (~`40.11 triệu`)
  - Tổng tham số sau gắn LoRA: **`8,993,911,296`** (~`8.99 tỷ`)
  - Tỷ lệ tham số train: **`0.4459%`**
  - Phân bổ trên toàn bộ **10 loại lớp chiếu (`TARGET_COUNTS`)** qua 32 transformer blocks:
    - **8** lớp Full Attention: `q_proj`, `k_proj`, `v_proj`, `o_proj`
    - **24** lớp Gated DeltaNet: `in_proj_qkv`, `in_proj_z`, `out_proj`
    - **32** lớp FFN / MLP: `gate_proj`, `up_proj`, `down_proj`
- **Phạm vi hiện tại**: Đã hoàn tất pha **SFT Training 1 Epoch** và tải `adapter-final` về máy local. Bước đánh giá PA end-to-end trên tập Validation (`276` câu) và Holdout (`276` câu) được tách riêng để chạy sau khi pipeline chính tích hợp đầy đủ.

---

## 2. Dữ liệu & Kiểm định đầu vào (`data/finetuning/`)

Toàn bộ dữ liệu được tách riêng khỏi lịch sử Git (nằm dưới `data/`, đã được `.gitignore` bỏ qua) tại `data/finetuning/`:

| Thành phần | Chi tiết kiểm định |
|---|---|
| `train_v1_2.jsonl` | **`2,448` mẫu** chuẩn hóa định dạng `{"id", "messages": [system, user, assistant]}`, SHA-256 `4a5a45275357790c517c120ab7c6406b9f673111cd9529a620a38a91c378c6fe` (`84 MB`). Toàn bộ `2,448/2,448` mẫu đều đạt `verified_l3` trên 24 doanh nghiệp. |
| `manifest.json` | Hợp đồng `planner.v1.2`, input builder `planner.v1.2-input.1`, system prompt `planner.v1.2-sys.1` (`system_prompt_sha256: 5048a2c2...`). Phân bổ `answer_type`: `number` (1,548), `percent` (460), `list` (162), `date` (107), `string` (79), `unanswerable` (58), `boolean` (19), `table` (15). |
| `planner_output.schema.json` | JSON Schema Draft 2020-12 (SHA-256 `03baa425...`), đã đồng bộ để `2,448 / 2,448` mẫu pass **0 lỗi** (`periods[*].label` tùy chọn, `order_by` nhận `expression` hoặc `column`, hỗ trợ `not_like`/`not_ilike`). |
| `splits/` | Phân tách theo `business_id` chống rò rỉ dữ liệu: `train_ids.json` (`2,448`), `val_ids.json` (`276`), `holdout_ids.json` (`276`). |

### Thống kê Token thực tế (bước `prepare` trên `Qwen/Qwen3.5-9B`)
- **Commit SHA model đã pin**: `c202236235762e1c871ad0ccb60c8ee5ba337b9a`
- **Tổng token đầu vào**: **`25,130,728` tokens**
- **Phân bố độ dài**: `p50 = 9,403` | `p95 = 16,644` | `max = 17,029` tokens (`0` mẫu vượt `max_length = 20,000`).
- **Loss masking**: Trong `train_datamate.py`, prefix của `apply_chat_template(..., add_generation_prompt=True, enable_thinking=False)` được đối chiếu khớp 100% với chuỗi đầy đủ và gán nhãn `-100` cho phần prompt + padding; completion kết thúc bằng đúng 1 token `<|im_end|>`.

---

## 3. Kiến trúc Code & Môi trường thực thi (`finetuning/` & Modal)

### Cấu trúc mã nguồn
- `finetuning/PLAN.md` — Kế hoạch triển khai & cấu hình chuẩn trên Modal.
- `finetuning/train_datamate.py` — Script huấn luyện độc lập (hỗ trợ `prepare`, `smoke`, `bench`, `train`; đọc trường `messages`, `CompletionCollator` pad động bội số 8, `LengthBucketSampler` + `LengthBucketedSFTTrainer`, `RunMonitor`).
- `finetuning/modal_finetune.py` — Runner điều phối Modal (`datamate-finetune`) và Modal Volume (`datamate-finetune-volume` mount tại `/vol`, cache weight tại `/vol/hf_cache` và artifact tại `/vol/runs/<run_name>/`).

### Môi trường Container GPU (`nvidia/cuda:12.8.1-devel-ubuntu24.04`, Python 3.12)
Các phiên bản khóa trong `datamate-train-requirements.lock`:
- `torch==2.9.1`, `transformers==5.23.0`, `trl==1.7.1`, `peft==0.21.3`, `datasets==5.2.0`
- CUDA kernel tăng tốc cho kiến trúc hybrid Gated DeltaNet của Qwen3.5:
  - `flash-linear-attention==0.6.0`
  - `causal-conv1d` (`git+https://github.com/Dao-AILab/causal-conv1d@cd81f0413cad2fc1e6f17e785ac39f59aae690cd`, biên dịch với `TORCH_CUDA_ARCH_LIST="8.0"`)

### Các điểm kỹ thuật then chốt đã xử lý
1. **Mở khóa kernel Gated DeltaNet (`fla=True, causal_conv1d=True`)**: Khắc phục tình trạng chạy fallback PyTorch chậm ở tốc độ `571.9 tok/s` (~`12.2 giờ`/epoch), đưa tốc độ lên `1,787 – 2,037 tok/s` (nhanh hơn **~3.1× – 3.5×**).
2. **Length Bucketing cho `micro_batch > 1`**: `transformers 5.23.0` không chấp nhận trực tiếp một số cấu hình `group_by_length` mặc định với custom dataset, nên đã triển khai `LengthBucketSampler` + `LengthBucketedSFTTrainer._get_train_sampler` (gom nhóm độ dài trong mega-batch 50×batch) giúp tăng **+44.5%** tốc độ ở `micro_batch=2` so với shuffle ngẫu nhiên.
3. **An toàn Volume & Resume**: `RunMonitor.on_save` tự gọi `volume.commit()` sau mỗi `100` updates. Đồng thời đã sửa lỗi ghi `datamate-train-requirements.lock` trước khi kiểm tra thư mục rỗng trong `finetune_on_modal_gpu`, giúp `--mode train` khởi chạy sạch sẽ.

---

## 4. Quy trình triển khai & Kết quả Benchmark chọn cấu hình

### Bước 1 — Chuẩn bị & Kiểm định trên CPU (`--mode prepare`)
Chạy trên CPU container (không tốn GPU) để tải cache base model vào `/vol/hf_cache` và kiểm định toàn bộ `2,448` mẫu:
```bash
source .venv/bin/activate && modal run finetuning/modal_finetune.py --mode prepare --run-name v1_2_a100_80gb
```

### Bước 2 — Đo Benchmark 5 cấu hình trên `NVIDIA A100-SXM4-80GB` (`$2.50/h`)
Chạy bài đo `smoke` (2 mẫu dài nhất ~`17K` tokens) và `bench` (`48` mẫu hỗn hợp độ dài / `6` optimizer updates, effective batch = `8`):

| Cấu hình | Tham số chính | VRAM Peak (Alloc / Reserved) | Thời gian `bench` (48 mẫu) | Tốc độ (Wall / Steady `tok/s`) | Ước tính 1 Epoch (Wall / Cost) | Kết luận |
|---|---|---:|---:|---:|---:|---|
| **`b2_gc_gbl`** | `--micro-batch 2 --group-by-length`, GC bật | **`40.73 / 46.68 GiB`** | **`275.04s`** | **`1,787.12` / `1,943.12`** | **`3.91 giờ` / `$9.77`** | **Tối ưu nhất (Đã chọn)** |
| `b1_gc_baseline` | `--micro-batch 1`, GC bật | `29.01 / 31.53 GiB` | `301.38s` | `1,630.92` / `2,036.93` | `4.28 giờ` / `$10.70` | Dự phòng VRAM thấp |
| `b4_gc_gbl` | `--micro-batch 4 --group-by-length`, GC bật | `64.00 / 73.64 GiB` | `332.65s` | `1,477.59` / `1,486.34` | `4.72 giờ` / `$11.81` | Chậm hơn & sát OOM |
| `b2_gc_random` | `--micro-batch 2`, không bucketing, GC bật | `40.73 / 46.81 GiB` | `397.48s` | `1,236.60` / `1,511.52` | `5.65 giờ` / `$14.11` | Lãng phí do pad 6.5K lên 17K |
| `b1_nogc` | `--micro-batch 1 --no-gradient-checkpointing` | `> 73.12 GiB` | **OOM** (lỗi ở smoke `17K`) | — | — | Tràn `79.27 GiB` VRAM |

**Quyết định cấu hình train**:
- Chọn **`b2_gc_gbl`** trên **`A100-80GB`** (không hạ về `A100-40GB` vì chỉ rẻ hơn ~`$0.8` trong khi chậm hơn, không đẩy lên `batch 4` vì vừa chậm hơn vừa sát ngưỡng OOM).
- Chạy **`1.0` epoch (`306` updates)** thay vì 2 epoch để vừa hợp ngân sách tài khoản (`$19.63`), vừa giữ trọn vẹn cả 4 mốc (`checkpoint-100`, `checkpoint-200`, `checkpoint-300`, `adapter-final`) không bị `save_total_limit=4` ghi đè, và hạn chế nguy cơ overfit theo schema tập train.

---

## 5. Thực thi & Kết quả Fine-Tuning chính thức (`v1_2_a100_80gb`)

### Lệnh chạy chính thức (`--detach` chống ngắt khi tắt máy local)
```bash
source .venv/bin/activate && modal run --detach finetuning/modal_finetune.py \
  --mode train \
  --run-name v1_2_a100_80gb \
  --revision c202236235762e1c871ad0ccb60c8ee5ba337b9a \
  --micro-batch 2 \
  --group-by-length \
  --epochs 1.0 \
  --download
```

### Tổng kết vận hành (`Modal App: ap-T7kiU2jtdQnaUAXUwhDyb4`)
- **Trạng thái**: Hoàn tất `306 / 306` optimizer updates (`epoch 1.0`), GPU container tự tắt lúc `12:24 UTC` (`2026-11-15`, chạy từ `08:47 UTC`).
- **Thời gian thực tế (`wall_seconds`)**: **`12,840.38 giây` (`3 giờ 34 phút` ≈ `3.57 giờ`)** — nhanh hơn cả ước tính `3.91 giờ`.
- **Chi phí ước tính (`$2.50/h`)**: **~`$8.92`**.
- **Đỉnh VRAM thực tế**: **`41.29 GiB` allocated / `48.867 GiB` reserved** trên `79.27 GiB` `A100-SXM4-80GB`.
- **Kết quả tổng hợp cuối epoch (`metrics.json`)**:
  - `train_loss`: **`0.03433`** (`0.034326`)
  - `entropy` cuối: **`0.01284`**
  - `mean_token_accuracy` toàn epoch: **`99.58%`** (`0.995774`)
  - `total_flos`: `1.2099e+18`

### Diễn biến quá trình học theo từng mốc (`trainer_state.json`)
*(Optimizer: `adamw_torch`, `lr = 1e-4`, `cosine` decay, `warmup = 3%`, `max_grad_norm = 1.0`, `seed = 3407`)*

| Step | Epoch | Loss | Grad Norm | Learning Rate | Mean Token Accuracy |
|---:|---:|---:|---:|---:|---:|
| `10` | `0.0327` | `0.1947` | `0.3818` | `9.000e-05` | `94.93%` |
| `50` | `0.1634` | `0.0460` | `0.2079` | `9.578e-05` | `98.71%` |
| `100` | `0.3268` | `0.0263` | `0.2228` | `7.930e-05` | `99.24%` |
| `150` | `0.4902` | `0.0249` | `0.2087` | `5.477e-05` | `99.23%` |
| `200` | `0.6536` | `0.0166` | `0.1874` | `2.892e-05` | `99.48%` |
| `250` | `0.8170` | `0.0135` | `0.2113` | `8.874e-06` | `99.58%` |
| `300` | `0.9804` | `0.0119` | `0.2157` | `1.379e-07` | `99.63%` |

Không ghi nhận bất kỳ lỗi `NaN`/`Inf`, spike gradient lớn hay OOM nào trong suốt quá trình train.

---

## 6. Artifact đầu ra & Hướng dẫn sử dụng tiếp theo

### Artifact đã tải về máy (`artifacts/finetuning/v1_2_a100_80gb/train/`)
- `adapter-final/` (`173 MB` tổng cộng):
  - `adapter_model.safetensors` (`154 MB`) & `adapter_config.json` (`1.3 KB`) — trọng số LoRA BF16 (`r=16, alpha=32`, pin revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`).
  - Bộ tokenizer chuẩn hóa (`tokenizer.json` `20 MB`, `tokenizer_config.json`, `chat_template.jinja`).
- `metrics.json` (`664 B`), `run_identity.json` (`582 B`), `trainer_state.json` (`11 KB`), `datamate-train-requirements.lock` (`1.8 KB`), `README.md` (`1.4 KB`).
- **Bản lưu trên Modal Volume (`datamate-finetune-volume:/runs/v1_2_a100_80gb/train/`)**: Lưu giữ đủ các mốc `checkpoint-100`, `checkpoint-200`, `checkpoint-300`, `checkpoint-306` cùng `adapter-final/`. Nếu cần tải thêm các mốc trung gian về để kiểm tra chéo (chỉ dùng CPU container, không thuê GPU):
  ```bash
  source .venv/bin/activate && modal run finetuning/modal_finetune.py --download-only --run-name v1_2_a100_80gb --include-checkpoints
  ```

### Lưu ý khi tích hợp vào Pipeline & Đánh giá PA
1. **Giữ Base + Adapter riêng trong giai đoạn đánh giá**: Gắn trực tiếp `adapter-final/` lên base `Qwen/Qwen3.5-9B` (revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`) hoặc chạy qua vLLM `--enable-lora` để linh hoạt đối chiếu giữa `Base`, `checkpoint-200`, `checkpoint-300`, `adapter-final`. Chỉ dùng `merge_and_unload()` khi đã chốt cấu hình cuối để deploy/quantize.
2. **Đồng bộ Prompt khi suy luận**: Adapter hiện tại được huấn luyện với **`enable_thinking=False`**, system prompt **`planner.v1.2-sys.1`** và JSON input của `planner.v1.2-input.1`; cần giữ đồng bộ cấu trúc prompt này ở tầng Planner của pipeline trước khi đo điểm PA trên **Validation (`276` câu)** và **Holdout (`276` câu)**.
