#!/usr/bin/env bash
set -e

# ==============================================================================
# Entrypoint Script cho Container DataMate Baseline B0
# Tương thích với thể lệ chấm thi Docker Offline của BTC Zalo AI Challenge 2026
#
# Cách gọi từ Docker:
#   docker run --rm --gpus all --network none \
#       -v /path/to/input:/data/input:ro \
#       -v /path/to/output:/data/output:rw \
#       <image_name> --input_dir /data/input --output_dir /data/output
# ==============================================================================

INPUT_DIR="/data/input"
OUTPUT_DIR="/data/output"
CONFIG_FILE="/workspace/configs/qwen3_5_9b.toml"
MODEL_PATH=""
BATCH_SIZE=8

# Đọc các tham số truyền vào
while [[ $# -gt 0 ]]; do
  case $1 in
    --input_dir|--input-dir|-i)
      INPUT_DIR="$2"
      shift 2
      ;;
    --output_dir|--output-dir|-o)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --config|-c)
      CONFIG_FILE="$2"
      shift 2
      ;;
    --model_path|--model-path|-m)
      MODEL_PATH="$2"
      shift 2
      ;;
    --batch_size|--batch-size|-b)
      BATCH_SIZE="$2"
      shift 2
      ;;
    *)
      # Các tham số khác chuyển tiếp
      shift
      ;;
  esac
done

echo "=========================================================="
echo "   UIT LAST DANCE - DATAMATE 2026 BASELINE B0 RUNNER"
echo "=========================================================="
echo "Thư mục đầu vào (Input)  : ${INPUT_DIR}"
echo "Thư mục đầu ra (Output) : ${OUTPUT_DIR}"
echo "Cấu hình model (Config)  : ${CONFIG_FILE}"
echo "Batch size suy luận     : ${BATCH_SIZE}"
echo "=========================================================="

# Tạo thư mục đầu ra nếu chưa có
mkdir -p "${OUTPUT_DIR}"

# Đảm bảo thư mục tạm spill cho DuckDB sandbox đã sẵn sàng
mkdir -p /tmp/duckdb_spill && chmod -R 777 /tmp/duckdb_spill || true

EXTRA_ARGS=()
if [ -n "${MODEL_PATH}" ]; then
  EXTRA_ARGS+=(--model-path "${MODEL_PATH}")
fi

# Chạy pipeline B0.1 -> B0.5
python3 /workspace/scripts/run_b0_pipeline.py \
    --split-dir "${INPUT_DIR}" \
    --output-dir "${OUTPUT_DIR}" \
    --config "${CONFIG_FILE}" \
    --batch-size "${BATCH_SIZE}" \
    "${EXTRA_ARGS[@]}"

echo "=========================================================="
echo "Hoàn thành pipeline! Kết quả đã ghi vào ${OUTPUT_DIR}/submission.jsonl"
echo "=========================================================="

