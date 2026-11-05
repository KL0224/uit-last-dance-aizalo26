#!/usr/bin/env bash
# Wrapper chỉ tải khi người dùng chủ động chạy: bash scripts/download_model.sh
# Có thể truyền tiếp --revision, --model-id và --output-dir cho Python script.
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Không auto-install: --no-sync yêu cầu môi trường đã chuẩn bị trước.
exec uv run --no-sync python scripts/download_model.py "$@"
