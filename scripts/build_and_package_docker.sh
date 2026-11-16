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
  for model_cfg in \
    "models/Qwen3.5-9B/config.json" \
    "models/Qwen2.5-3B-Instruct/config.json"; do
    if [ ! -f "$model_cfg" ]; then
      echo "[LỖI] Thiếu snapshot model offline: $model_cfg" >&2
      echo "Hãy tải đủ weights trước khi build Docker submission:" >&2
      echo "  python3 scripts/download_model.py --model Qwen/Qwen3.5-9B --revision c202236235762e1c871ad0ccb60c8ee5ba337b9a --output-dir models/Qwen3.5-9B" >&2
      echo "  python3 scripts/download_model.py --model Qwen/Qwen2.5-3B-Instruct --output-dir models/Qwen2.5-3B-Instruct" >&2
      echo "(Hoặc đặt ALLOW_MISSING_MODELS=1 nếu chỉ test build cấu trúc.)" >&2
      exit 1
    fi
  done
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

# 4. Đóng gói docker save | gzip
echo "[4/5] Đang xuất Docker image và nén thành ${OUTPUT_TAR_GZ} (vui lòng đợi vài phút)..."
if command -v pigz >/dev/null 2>&1; then
  docker save "${IMAGE_TAG}" | pigz -p 8 > "${OUTPUT_TAR_GZ}"
else
  docker save "${IMAGE_TAG}" | gzip > "${OUTPUT_TAR_GZ}"
fi

# 5. Đo đạc kích thước uncompressed và tạo mã MD5
echo "[5/5] Tính toán checksum MD5 và đo kích thước uncompressed..."
md5sum "${OUTPUT_TAR_GZ}" > "${OUTPUT_MD5}"

if command -v pigz >/dev/null 2>&1; then
  UNCOMPRESSED_SIZE=$(pigz -dc "${OUTPUT_TAR_GZ}" | wc -c)
else
  UNCOMPRESSED_SIZE=$(gzip -dc "${OUTPUT_TAR_GZ}" | wc -c)
fi

echo "=========================================================="
echo "ĐÓNG GÓI THÀNH CÔNG!"
echo "Tệp nén .tar.gz          : ${OUTPUT_TAR_GZ}"
echo "Mã MD5 checksum          : $(cat "${OUTPUT_MD5}")"
echo "Dung lượng uncompressed  : ${UNCOMPRESSED_SIZE} bytes"
echo "Giới hạn BTC             : <= 100 GB (107374182400 bytes)"
echo "=========================================================="
