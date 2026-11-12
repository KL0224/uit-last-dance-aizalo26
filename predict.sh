#!/usr/bin/env bash
set -e

# ==============================================================================
# Predict Entrypoint Script - Zalo AI Challenge 2026 (DataMate)
# Team: UIT Last Dance (zaic2026_datamate_uit_last_dance:final)
# Official Specification: Section 5 & Section 10 of Docker Submission Guide
# ==============================================================================

# Default paths according to BTC guidelines
INPUT_DIR="/data"
OUTPUT_DIR="/result"
TEMP_DIR="/tmp"
BUNDLES_DIR="/tmp/bundles"
DUCKDB_SPILL_DIR="/tmp/duckdb_spill"
BATCH_SIZE=8

# Determine code root
if [ -d "/code" ]; then
  CODE_ROOT="/code"
elif [ -d "/workspace" ]; then
  CODE_ROOT="/workspace"
else
  CODE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

CONFIG_FILE="${CODE_ROOT}/configs/qwen3_5_9b.toml"
MODEL_PATH="${CODE_ROOT}/models/qwen3_5_9b"

# Support optional flag overrides if provided
while [[ $# -gt 0 ]]; do
  case $1 in
    --input_dir|--input-dir|-i|--data)
      INPUT_DIR="$2"
      shift 2
      ;;
    --output_dir|--output-dir|-o|--result)
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
      shift
      ;;
  esac
done

echo "=========================================================="
echo "   UIT LAST DANCE - DATAMATE 2026 PREDICT RUNNER"
echo "=========================================================="
echo "Input Directory (/data)       : ${INPUT_DIR}"
echo "Output Directory (/result)    : ${OUTPUT_DIR}"
echo "Code Root Directory           : ${CODE_ROOT}"
echo "Config File                   : ${CONFIG_FILE}"
echo "Model Path                    : ${MODEL_PATH}"
echo "Batch Size                    : ${BATCH_SIZE}"
echo "=========================================================="

# Create required output and sandbox directories
mkdir -p "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}/logs"
mkdir -p "${BUNDLES_DIR}" && chmod -R 777 "${BUNDLES_DIR}" || true
mkdir -p "${DUCKDB_SPILL_DIR}" && chmod -R 777 "${DUCKDB_SPILL_DIR}" || true

# Export offline and runtime performance configurations
export B04_DUCKDB_TEMP_DIR="${DUCKDB_SPILL_DIR}"
export B04_DUCKDB_MAX_MEMORY="4GB"
export B04_DUCKDB_THREADS="4"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export NCCL_P2P_DISABLE=1
export VLLM_USE_FLASHINFER_SAMPLER=0
export PYTHONPATH="${CODE_ROOT}/src:${CODE_ROOT}"

EXTRA_ARGS=()
if [ -d "${MODEL_PATH}" ] && [ -f "${MODEL_PATH}/config.json" ]; then
  EXTRA_ARGS+=(--model-path "${MODEL_PATH}")
elif [ -n "${MODEL_PATH}" ] && [ -f "${MODEL_PATH}/config.json" ]; then
  EXTRA_ARGS+=(--model-path "${MODEL_PATH}")
fi

# Run DataMate Pipeline
python3 "${CODE_ROOT}/scripts/run_pipeline.py" \
    --split-dir "${INPUT_DIR}" \
    --output-dir "${OUTPUT_DIR}" \
    --bundles-dir "${BUNDLES_DIR}" \
    --config "${CONFIG_FILE}" \
    --batch-size "${BATCH_SIZE}" \
    "${EXTRA_ARGS[@]}"

echo "=========================================================="
echo "Predict completed successfully!"
echo "Result submission: ${OUTPUT_DIR}/submission.jsonl"
echo "Logs directory   : ${OUTPUT_DIR}/logs/"
echo "=========================================================="
