#!/usr/bin/env bash
set -euo pipefail

echo "======================================"
echo "Qwen3.5-9B Inference Environment Setup"
echo "Target: RTX 5000 Ada / RTX 5090"
echo "======================================"

# 1. Check NVIDIA GPU
nvidia-smi

# 2. Install uv if missing
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# 3. Install Python 3.12
uv python install 3.12

# 4. Create virtual environment
uv venv --python 3.12 .venv

# 5. Activate environment
source .venv/bin/activate

# 6. Install vLLM with compatible PyTorch
uv pip install "vllm==0.33.0" --torch-backend=auto

# 7. Install OpenAI client
uv pip install openai

# 8. Check environment
python - <<'PY'
import torch
import vllm

print("\nEnvironment:")
print("PyTorch:", torch.__version__)
print("CUDA:", torch.version.cuda)
print("vLLM:", vllm.__version__)

assert torch.cuda.is_available(), "CUDA unavailable"

print("GPU:", torch.cuda.get_device_name(0))
print("Compute Capability:", torch.cuda.get_device_capability(0))
print("GPU Memory (GB):",
      round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2))

a = torch.randn(512, 512, device="cuda", dtype=torch.bfloat16)
b = a @ a
torch.cuda.synchronize()

print("BF16 CUDA test: PASS")
PY

# 9. Export exact dependency versions
uv pip freeze > requirements-lock.txt

echo "======================================"
echo "Setup completed!"
echo "Activate: source .venv/bin/activate"
echo "======================================"