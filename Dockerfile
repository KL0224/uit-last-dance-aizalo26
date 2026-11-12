# ==============================================================================
# Dockerfile: DataMate Official Submission - Zalo AI Challenge 2026
# Team: UIT Last Dance (zaic2026_datamate_uit_last_dance:final)
# Target Environment: Dual NVIDIA RTX 5090 (Blackwell cc 12.0), CUDA >= 12.8
# Reference: Sections 4, 8 & 9 of ZAC 2026 Docker Submission Guide
# ==============================================================================
FROM vllm/vllm-openai:v0.10.1.1

# Reset ENTRYPOINT [] so that a plain docker run starts predict.sh, not vLLM server
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

# Install system dependencies if required
RUN apt-get update && apt-get install -y --no-install-recommends \
    dos2unix curl pigz \
    && rm -rf /var/lib/apt/lists/*

# Install pinned inference dependencies
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt

# Official BTC workaround for RTX 5090 Blackwell dual-GPU hang fix
RUN pip install --no-cache-dir --no-deps nvidia-nccl-cu12==2.27.7

# Ensure sandbox directories exist with proper write permissions for read-only runs
RUN mkdir -p /tmp/duckdb_spill /tmp/bundles /result/logs && \
    chmod -R 777 /tmp/duckdb_spill /tmp/bundles /result

# Separate COPY steps to optimize Docker layer caching
COPY models/ /code/models/
COPY training_code/ /code/training_code/
COPY predict.sh README.md /code/
COPY configs/ /code/configs/
COPY scripts/ /code/scripts/
COPY src/ /code/src/

# Convert CRLF to LF and set executable permissions
RUN dos2unix /code/predict.sh /code/training_code/train.sh && \
    chmod +x /code/predict.sh /code/training_code/train.sh

ENV PYTHONPATH="/code/src:/code"

CMD ["bash", "/code/predict.sh"]
