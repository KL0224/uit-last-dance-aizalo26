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

CONFIG_FILE="${CODE_ROOT}/configs/qwen3_5_9b_ft_v1_2.toml"
MODEL_PATH=""
LORA_PATH=""
NO_LORA=0
PROMPT_FORMAT=""
GROUNDED_HINT_MODE=""
GROUNDING_ENGINE="neo"
GROUNDING_CONFIG="${CODE_ROOT}/configs/qwen2_5_3b_neo_grounding.toml"
GROUNDING_MODEL_PATH=""
GROUNDING_CACHE=""
PHASE=""
TWO_PHASE_FLAG="--two-phase"
NUM_GPUS=""
GPU_IDS=""
VOTING_FLAG=""
VOTING_ROUNDS=""
VOTING_CANDIDATES=""
VOTING_THRESHOLD=""
VOTING_TEMPERATURE=""
VOTING_TOP_P=""
VOTING_TOP_K=""
VOTING_THINKING_MODE=""

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
    --lora_path|--lora-path)
      LORA_PATH="$2"
      shift 2
      ;;
    --no-lora)
      NO_LORA=1
      shift
      ;;
    --prompt_format|--prompt-format)
      PROMPT_FORMAT="$2"
      shift 2
      ;;
    --grounded_hint_mode|--grounded-hint-mode)
      GROUNDED_HINT_MODE="$2"
      shift 2
      ;;
    --grounding_engine|--grounding-engine)
      GROUNDING_ENGINE="$2"
      shift 2
      ;;
    --grounding_config|--grounding-config)
      GROUNDING_CONFIG="$2"
      shift 2
      ;;
    --grounding_model_path|--grounding-model-path)
      GROUNDING_MODEL_PATH="$2"
      shift 2
      ;;
    --grounding_cache|--grounding-cache)
      GROUNDING_CACHE="$2"
      shift 2
      ;;
    --phase)
      PHASE="$2"
      shift 2
      ;;
    --two-phase)
      TWO_PHASE_FLAG="--two-phase"
      shift
      ;;
    --no-two-phase)
      TWO_PHASE_FLAG="--no-two-phase"
      shift
      ;;
    --num_gpus|--num-gpus)
      NUM_GPUS="$2"
      shift 2
      ;;
    --gpu_ids|--gpu-ids)
      GPU_IDS="$2"
      shift 2
      ;;
    --batch_size|--batch-size|-b)
      BATCH_SIZE="$2"
      shift 2
      ;;
    --voting)
      VOTING_FLAG="--voting"
      shift
      ;;
    --no-voting)
      VOTING_FLAG="--no-voting"
      shift
      ;;
    --voting-rounds)
      VOTING_ROUNDS="$2"
      shift 2
      ;;
    --voting-candidates)
      VOTING_CANDIDATES="$2"
      shift 2
      ;;
    --voting-threshold)
      VOTING_THRESHOLD="$2"
      shift 2
      ;;
    --voting-temperature)
      VOTING_TEMPERATURE="$2"
      shift 2
      ;;
    --voting-top-p)
      VOTING_TOP_P="$2"
      shift 2
      ;;
    --voting-top-k)
      VOTING_TOP_K="$2"
      shift 2
      ;;
    --voting-thinking-mode)
      VOTING_THINKING_MODE="$2"
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
echo "Grounding Config (3B)         : ${GROUNDING_CONFIG}"
echo "Grounding Engine              : ${GROUNDING_ENGINE}"
echo "Model Path                    : ${MODEL_PATH}"
echo "Batch Size                    : ${BATCH_SIZE}"
echo "Num GPUs / GPU IDs            : ${NUM_GPUS:-auto} / ${GPU_IDS:-auto}"
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
if [ -z "${MODEL_PATH}" ]; then
  if [ -f "${CODE_ROOT}/models/qwen3_5_9b_ft_v1_2/config.json" ]; then
    MODEL_PATH="${CODE_ROOT}/models/qwen3_5_9b_ft_v1_2"
    if [ -z "${LORA_PATH}" ]; then
      NO_LORA=1
    fi
  elif [ -f "${CODE_ROOT}/models/Qwen3.5-9B/config.json" ]; then
    MODEL_PATH="${CODE_ROOT}/models/Qwen3.5-9B"
    if [ -z "${LORA_PATH}" ] && [ "${NO_LORA}" -eq 0 ] && [ -f "${CODE_ROOT}/models/adapters/qwen3_5_9b_v1_2/adapter_config.json" ]; then
      LORA_PATH="${CODE_ROOT}/models/adapters/qwen3_5_9b_v1_2"
    fi
  elif [ -f "${CODE_ROOT}/models/qwen3_5_9b/config.json" ]; then
    MODEL_PATH="${CODE_ROOT}/models/qwen3_5_9b"
    if [ -z "${LORA_PATH}" ] && [ "${NO_LORA}" -eq 0 ]; then
      if [ -f "${CODE_ROOT}/models/adapters/qwen3_5_9b_v1_2/adapter_config.json" ]; then
        LORA_PATH="${CODE_ROOT}/models/adapters/qwen3_5_9b_v1_2"
      elif [ -f "${CODE_ROOT}/models/adapter-final/adapter_config.json" ]; then
        LORA_PATH="${CODE_ROOT}/models/adapter-final"
      fi
    fi
  fi
fi

if [ -n "${MODEL_PATH}" ] && [ -f "${MODEL_PATH}/config.json" ]; then
  EXTRA_ARGS+=(--model-path "${MODEL_PATH}")
fi

if [ "${NO_LORA}" -eq 1 ]; then
  EXTRA_ARGS+=(--no-lora)
elif [ -n "${LORA_PATH}" ]; then
  EXTRA_ARGS+=(--lora-path "${LORA_PATH}")
fi

if [ -n "${PROMPT_FORMAT}" ]; then
  EXTRA_ARGS+=(--prompt-format "${PROMPT_FORMAT}")
fi
if [ -n "${GROUNDED_HINT_MODE}" ]; then
  EXTRA_ARGS+=(--grounded-hint-mode "${GROUNDED_HINT_MODE}")
fi
if [ -n "${GROUNDING_ENGINE}" ]; then
  EXTRA_ARGS+=(--grounding-engine "${GROUNDING_ENGINE}")
fi
if [ -n "${GROUNDING_CONFIG}" ]; then
  EXTRA_ARGS+=(--grounding-config "${GROUNDING_CONFIG}")
fi
if [ -n "${GROUNDING_MODEL_PATH}" ]; then
  EXTRA_ARGS+=(--grounding-model-path "${GROUNDING_MODEL_PATH}")
fi
if [ -n "${GROUNDING_CACHE}" ]; then
  EXTRA_ARGS+=(--grounding-cache "${GROUNDING_CACHE}")
fi
if [ -n "${PHASE}" ]; then
  EXTRA_ARGS+=(--phase "${PHASE}")
fi
if [ -n "${TWO_PHASE_FLAG}" ]; then
  EXTRA_ARGS+=("${TWO_PHASE_FLAG}")
fi
if [ -n "${NUM_GPUS}" ]; then
  EXTRA_ARGS+=(--num-gpus "${NUM_GPUS}")
fi
if [ -n "${GPU_IDS}" ]; then
  EXTRA_ARGS+=(--gpu-ids "${GPU_IDS}")
fi
if [ -n "${VOTING_FLAG}" ]; then
  EXTRA_ARGS+=("${VOTING_FLAG}")
fi
if [ -n "${VOTING_ROUNDS}" ]; then
  EXTRA_ARGS+=(--voting-rounds "${VOTING_ROUNDS}")
fi
if [ -n "${VOTING_CANDIDATES}" ]; then
  EXTRA_ARGS+=(--voting-candidates "${VOTING_CANDIDATES}")
fi
if [ -n "${VOTING_THRESHOLD}" ]; then
  EXTRA_ARGS+=(--voting-threshold "${VOTING_THRESHOLD}")
fi
if [ -n "${VOTING_TEMPERATURE}" ]; then
  EXTRA_ARGS+=(--voting-temperature "${VOTING_TEMPERATURE}")
fi
if [ -n "${VOTING_TOP_P}" ]; then
  EXTRA_ARGS+=(--voting-top-p "${VOTING_TOP_P}")
fi
if [ -n "${VOTING_TOP_K}" ]; then
  EXTRA_ARGS+=(--voting-top-k "${VOTING_TOP_K}")
fi
if [ -n "${VOTING_THINKING_MODE}" ]; then
  EXTRA_ARGS+=(--voting-thinking-mode "${VOTING_THINKING_MODE}")
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
