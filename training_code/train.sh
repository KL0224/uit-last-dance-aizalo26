#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Training Entrypoint Script - Qwen/Qwen3.5-9B BF16 LoRA (Planner v1.2)
# Zalo AI Challenge 2026 - DataMate | Team: UIT Last Dance
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

REVISION="${MODEL_REVISION:-c202236235762e1c871ad0ccb60c8ee5ba337b9a}"
MODE="${TRAIN_MODE:-train}"
MICRO_BATCH="${MICRO_BATCH:-2}"
MAX_LENGTH="${MAX_LENGTH:-20000}"
LORA_R="${LORA_R:-16}"
LORA_ALPHA="${LORA_ALPHA:-32}"
LR="${LR:-1e-4}"
EPOCHS="${EPOCHS:-1.0}"
SAVE_STEPS="${SAVE_STEPS:-100}"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}/checkpoints/qwen3_5_9b_v1_2_repro}"

TRAIN_FILE="${TRAIN_FILE:-${SCRIPT_DIR}/data/train_v1_2.jsonl}"
if [ ! -f "${TRAIN_FILE}" ] && [ -f "${REPO_ROOT}/data/finetuning/train_v1_2.jsonl" ]; then
  TRAIN_FILE="${REPO_ROOT}/data/finetuning/train_v1_2.jsonl"
fi

SCHEMA_FILE="${SCHEMA_FILE:-${SCRIPT_DIR}/data/planner_output.schema.json}"
if [ ! -f "${SCHEMA_FILE}" ]; then
  SCHEMA_FILE="${SCRIPT_DIR}/configs/planner_output.schema.json"
fi

if [ ! -f "${TRAIN_FILE}" ]; then
  echo "[LỖI] Không tìm thấy dữ liệu SFT tại: ${TRAIN_FILE}" >&2
  exit 1
fi

echo "=========================================================="
echo "   UIT LAST DANCE - QWEN3.5-9B LORA SFT RUNNER (v1.2)"
echo "=========================================================="
echo "Script     : ${SCRIPT_DIR}/src/train_datamate.py"
echo "Mode       : ${MODE}"
echo "Base Model : Qwen/Qwen3.5-9B @ ${REVISION}"
echo "Train File : ${TRAIN_FILE}"
echo "Schema     : ${SCHEMA_FILE}"
echo "LoRA       : r=${LORA_R}, alpha=${LORA_ALPHA}, lr=${LR}, epochs=${EPOCHS}"
echo "Batching   : micro_batch=${MICRO_BATCH}, max_length=${MAX_LENGTH}, group_by_length=true"
echo "Output Dir : ${OUT_DIR}"
echo "=========================================================="

mkdir -p "${OUT_DIR}"

python3 "${SCRIPT_DIR}/src/train_datamate.py" \
  --train "${TRAIN_FILE}" \
  --schema "${SCHEMA_FILE}" \
  --revision "${REVISION}" \
  --mode "${MODE}" \
  --micro-batch "${MICRO_BATCH}" \
  --max-length "${MAX_LENGTH}" \
  --r "${LORA_R}" \
  --alpha "${LORA_ALPHA}" \
  --lr "${LR}" \
  --epochs "${EPOCHS}" \
  --save-steps "${SAVE_STEPS}" \
  --group-by-length \
  --out "${OUT_DIR}" \
  "$@"
