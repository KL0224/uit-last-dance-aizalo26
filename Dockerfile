# ==============================================================================
# Dockerfile: DataMate Baseline B0 - Zalo AI Challenge 2026
# UIT Last Dance
# ==============================================================================
FROM pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    VLLM_USE_FLASHINFER_SAMPLER=0 \
    B04_DUCKDB_MAX_MEMORY="4GB" \
    B04_DUCKDB_THREADS="4" \
    B04_DUCKDB_TEMP_DIR="/tmp/duckdb_spill"

# Cài đặt các gói hệ thống tối thiểu
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl dos2unix \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Cài đặt thư viện Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    duckdb==1.1.3 sqlglot==25.29.0 pydantic>=2.7.0 \
    pandas>=2.2.0 openpyxl>=3.1.2 pyarrow>=16.0.0 \
    -r requirements.txt

# Tạo sẵn thư mục tạm spill cho sandbox DuckDB (tránh lỗi IOException khi root bị read-only)
RUN mkdir -p /tmp/duckdb_spill && chmod -R 777 /tmp/duckdb_spill

# Sao chép mã nguồn và cấu hình
COPY src/ /workspace/src/
COPY configs/ /workspace/configs/
COPY scripts/ /workspace/scripts/
COPY entrypoint.sh /workspace/entrypoint.sh

# Chuyển đổi định dạng ngắt dòng CRLF sang LF và phân quyền thực thi
RUN dos2unix /workspace/entrypoint.sh && chmod +x /workspace/entrypoint.sh

ENV PYTHONPATH="/workspace/src:/workspace"

ENTRYPOINT ["/workspace/entrypoint.sh"]
CMD ["--input_dir", "/data/input", "--output_dir", "/data/output"]
