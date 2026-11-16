#!/usr/bin/env bash
set -e
set -o pipefail

# ==============================================================================
# Docker Build, Verification and Packaging Script
# Zalo AI Challenge 2026 - DataMate
# Team: UIT Last Dance (zaic2026_datamate_uit_last_dance:final)
# Reference: Section 9, 10 & 11 of Docker Submission Guide
# ==============================================================================

TEAM_NAME="uit_last_dance"
IMAGE_TAG="zaic2026_datamate_${TEAM_NAME}:final"
OUTPUT_TAR_GZ="zaic2026_datamate_${TEAM_NAME}.tar.gz"
OUTPUT_MD5="${OUTPUT_TAR_GZ}.md5"
BASE_IMAGE="${BASE_IMAGE:-vllm/vllm-openai:v0.17.1}"

echo "=========================================================="
echo "   UIT LAST DANCE - DOCKER BUILD & PACKAGE PIPELINE"
echo "=========================================================="
echo "Base Image       : ${BASE_IMAGE}"
echo "Image Tag        : ${IMAGE_TAG}"
echo "Archive File     : ${OUTPUT_TAR_GZ}"
echo "MD5 Checksum     : ${OUTPUT_MD5}"
echo "=========================================================="

# 1. Kiểm tra cấu trúc thư mục tối thiểu theo Section 4 & offline artifacts
echo "[1/5] Kiểm tra cấu trúc thư mục quy định (/code layout)..."
for req in \
  "Dockerfile" \
  "predict.sh" \
  "README.md" \
  "requirements.txt" \
  "requirements-docker.txt" \
  "training_code/README.md" \
  "training_code/data_manifest.json" \
  "training_code/src/train_datamate.py" \
  "training_code/logs/metrics.json" \
  "data/finetuning/train_v1_2.jsonl" \
  "models/adapters/qwen3_5_9b_v1_2/adapter_model.safetensors" \
  "src" \
  "configs" \
  "scripts"; do
  if [ ! -e "$req" ]; then
    echo "[LỖI] Thiếu thành phần bắt buộc: $req" >&2
    exit 1
  fi
done

if [ "${ALLOW_MISSING_MODELS:-0}" != "1" ]; then
  if [ ! -f "models/qwen3_5_9b_ft_v1_2/config.json" ] && [ ! -f "models/Qwen3.5-9B/config.json" ]; then
    echo "[LỖI] Thiếu snapshot 9B offline (cần models/qwen3_5_9b_ft_v1_2/config.json hoặc models/Qwen3.5-9B/config.json)" >&2
    echo "Hãy tải hoặc merge LoRA trước khi build Docker submission:" >&2
    echo "  python3 scripts/download_model.py --model Qwen/Qwen3.5-9B --revision c202236235762e1c871ad0ccb60c8ee5ba337b9a --output-dir models/Qwen3.5-9B" >&2
    echo "  python3 training_code/src/merge_lora.py --base-model models/Qwen3.5-9B --adapter-dir models/adapters/qwen3_5_9b_v1_2 --output-dir models/qwen3_5_9b_ft_v1_2" >&2
    exit 1
  fi
  if [ ! -f "models/Qwen2.5-3B-Instruct/config.json" ]; then
    echo "[LỖI] Thiếu snapshot model offline: models/Qwen2.5-3B-Instruct/config.json" >&2
    echo "  python3 scripts/download_model.py --model Qwen/Qwen2.5-3B-Instruct --output-dir models/Qwen2.5-3B-Instruct" >&2
    exit 1
  fi
fi
echo "  => Cấu trúc mã nguồn & offline weights hợp lệ."

# 2. Build Docker image
echo "[2/5] Đang build Docker image cho linux/amd64..."
docker build --platform linux/amd64 --build-arg "BASE_IMAGE=${BASE_IMAGE}" -t "${IMAGE_TAG}" .

# 3. Kiểm tra kiểm định Image (Inspect & Layout)
echo "[3/5] Kiểm tra metadata và cấu trúc bên trong container..."
docker image inspect -f 'OS/Arch: {{.Os}}/{{.Architecture}} | Kích thước uncompressed: {{.Size}} bytes' "${IMAGE_TAG}"
docker run --rm --network none --entrypoint "" "${IMAGE_TAG}" bash -c \
  'find /code -maxdepth 2 && test -x /code/predict.sh && test -f /code/training_code/data/train_v1_2.jsonl && test -f /code/training_code/src/train_datamate.py'

# 4. Đóng gói docker save | pigz/gzip (đo luôn dung lượng uncompressed trong 1 lượt đọc)
THREADS="${PIGZ_THREADS:-$(nproc 2>/dev/null || echo 8)}"
LEVEL="${PIGZ_LEVEL:-1}"
echo "[4/5] Đang xuất Docker image và nén nhanh (level=-${LEVEL}, threads=${THREADS}) thành ${OUTPUT_TAR_GZ}..."

if command -v pigz >/dev/null 2>&1; then
  COMPRESS_CMD="pigz -${LEVEL} -p ${THREADS}"
else
  echo "[Cảnh báo] Chưa cài 'pigz' -> fallback dùng 'gzip -${LEVEL}' (1 luồng, chậm hơn nhiều). Nên cài: sudo apt-get install -y pigz"
  COMPRESS_CMD="gzip -${LEVEL}"
fi

SIZE_FIFO="$(mktemp -u)"
SIZE_OUT="${SIZE_FIFO}.size"
mkfifo "${SIZE_FIFO}"
trap 'rm -f "${SIZE_FIFO}" "${SIZE_OUT}"' EXIT
wc -c < "${SIZE_FIFO}" > "${SIZE_OUT}" &
WC_PID=$!

docker save "${IMAGE_TAG}" | tee "${SIZE_FIFO}" | ${COMPRESS_CMD} > "${OUTPUT_TAR_GZ}"
wait "${WC_PID}"
UNCOMPRESSED_SIZE="$(tr -d '[:space:]' < "${SIZE_OUT}")"
rm -f "${SIZE_FIFO}" "${SIZE_OUT}"
trap - EXIT

# 5. Tạo mã MD5 checksum cho tệp nén cuối cùng
echo "[5/5] Đang tính toán checksum MD5..."
md5sum "${OUTPUT_TAR_GZ}" > "${OUTPUT_MD5}"

echo "=========================================================="
echo "ĐÓNG GÓI THÀNH CÔNG!"
echo "Tệp nén .tar.gz          : ${OUTPUT_TAR_GZ}"
echo "Mã MD5 checksum          : $(cat "${OUTPUT_MD5}")"
echo "Dung lượng uncompressed  : ${UNCOMPRESSED_SIZE} bytes"
echo "Giới hạn BTC             : <= 100 GB (107374182400 bytes)"
echo "=========================================================="
