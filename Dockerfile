# ==============================================================================
# Dockerfile: DataMate Official Submission - Zalo AI Challenge 2026
# Team: UIT Last Dance (zaic2026_datamate_uit_last_dance:final)
# Target Environment: Dual NVIDIA RTX 5090 (Blackwell cc 12.0), Host CUDA 12.8
# Reference: Sections 4, 8 & 9 of ZAC 2026 Docker Submission Guide
# ==============================================================================
ARG BASE_IMAGE=vllm/vllm-openai:v0.17.1
FROM ${BASE_IMAGE}

# Reset ENTRYPOINT [] so both `docker run ... --entrypoint bash ... /code/predict.sh` and CMD work cleanly
ENTRYPOINT []

# Offline inference & multi-GPU performance configurations
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PIP_NO_CACHE_DIR=1 \
    NCCL_P2P_DISABLE=1 \
    VLLM_USE_FLASHINFER_SAMPLER=0 \
    B04_DUCKDB_MAX_MEMORY="4GB" \
    B04_DUCKDB_THREADS="4" \
    B04_DUCKDB_TEMP_DIR="/tmp/duckdb_spill"

WORKDIR /code

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    dos2unix curl pigz \
    && rm -rf /var/lib/apt/lists/*

# Install only pure runtime app/SQL/data packages; keep base image torch/vllm/transformers/cuda intact
COPY pyproject.toml requirements.txt requirements-docker.txt ./
RUN pip install --no-cache-dir -r requirements-docker.txt && \
    python3 -c "import duckdb, sqlglot, pydantic, numpy, pandas, openpyxl, pyarrow, jsonschema, huggingface_hub, openai, vllm, torch, transformers; print('Verified runtime deps | vllm=', vllm.__version__, '| transformers=', transformers.__version__)"

# Ensure sandbox directories exist with proper write permissions for read-only /data runs
RUN mkdir -p /tmp/duckdb_spill /tmp/bundles /result && \
    chmod -R 777 /tmp/duckdb_spill /tmp/bundles /result

# Copy offline model snapshots & LoRA v1.2 adapter weights
COPY models/ /code/models/

# Copy training code, configs, SFT logs/metrics, and verified SFT dataset (Section 4 & 8)
COPY training_code/ /code/training_code/
COPY data/finetuning/ /code/training_code/data/

# Copy codebase & runtime entrypoints
COPY predict.sh README.md /code/
COPY configs/ /code/configs/
COPY scripts/ /code/scripts/
COPY src/ /code/src/

# Convert CRLF to LF and ensure non-root/host-readable permissions across artifacts
RUN dos2unix /code/predict.sh /code/training_code/train.sh && \
    chmod +x /code/predict.sh /code/training_code/train.sh /code/scripts/run_pipeline.py && \
    chmod -R a+rX /code/models /code/training_code /code/src /code/configs /code/scripts

ENV PYTHONPATH="/code/src:/code"

CMD ["bash", "/code/predict.sh"]
