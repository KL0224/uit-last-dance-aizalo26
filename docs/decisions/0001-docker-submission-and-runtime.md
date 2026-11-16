# ADR-0001: Docker Submission Packaging, CUDA Runtime Compatibility, and Clean Output Isolation

## Status
Accepted

## Date
2026-11-16

## Context
Auditing the submission packaging against `temp/zac2026_DataMate_docker_guideline_final.pdf` (Sections 3–11) uncovered four critical incompatibilities and compliance risks prior to building the final `zaic2026_datamate_uit_last_dance:final` image for Zalo AI Challenge 2026 (2x NVIDIA RTX 5090, host Driver `570.86.10`, `CUDA Version: 12.8`, `--network none`):

1. **vLLM & CUDA Version Conflict in `Dockerfile`**:
   - The previous `Dockerfile` started from `vllm/vllm-openai:v0.10.1.1` (too old for `Qwen3_5ForCausalLM`, which requires `vLLM >= 0.17.0`), then installed `requirements-lock.txt` (generated on Modal with `torch==2.13.0`, `vllm==0.30.0`, `nvidia-nccl-cu13==2.29.7`), and finally forced `--no-deps nvidia-nccl-cu12==2.27.7`. Mixing CUDA 13 wheels with CUDA 12.8 host drivers / cu12 NCCL pins risks `ImportError` / symbol lookup failures and `nvidia-container-cli` mismatch on scoring hosts.
   - Meanwhile, Docker Hub inspection of `vllm/vllm-openai:v0.17.1` confirms native compilation for Blackwell `sm_120` (`TORCH_CUDA_ARCH_LIST=7.0 7.5 8.0 8.9 9.0 10.0 12.0`), explicit `NVIDIA_REQUIRE_CUDA` acceptance for `driver>=570,driver<571`, and a strict `transformers<5,>=4.56.0` dependency pin (meaning installing SFT libraries such as `trl==1.7.1` or `transformers>=5.x` inside the inference container would break `vllm==0.17.1`).
2. **Build Context Exclusions (`.dockerignore`) & Git Hygiene (`.gitignore`)**:
   - Unanchored rules (`data`, `logs`, `tasks`) in `.dockerignore` suppressed `data/finetuning/` (containing the 84 MB SFT dataset `train_v1_2.jsonl`) and posed accidental exclusion risks for `/code/training_code/logs/`.
   - Simultaneously, committing the 84 MB JSONL inside `training_code/` would bloat Git history.
3. **Training & Model Provenance Mismatch (Section 8)**:
   - `training_code/` contained placeholder `.gitkeep` stubs, and `README.md` / `data_manifest.json` falsely stated zero-shot unmodified weights with inaccurate model release dates (`2024-10-20` for Qwen3.5-9B) and license (`Apache-2.0` instead of `Qwen Research License Agreement` for `Qwen2.5-3B-Instruct`).
4. **Temporary Runtime Files Inside `/result/` (Section 3)**:
   - Multi-GPU execution stored `_shards/` and `.submission.lock` directly inside `--output-dir` (`/result/`), and single-GPU execution placed `_work/` inside `--output-dir`, risking leftover hidden/temporary artifacts in `/result/`.

## Decision
1. **Split Inference vs. Training Docker Environments**:
   - Update `Dockerfile` to parameterize `ARG BASE_IMAGE=vllm/vllm-openai:v0.17.1` (`FROM ${BASE_IMAGE}`), remove `requirements-lock.txt` and manual `nvidia-nccl` overrides, and install only pure runtime data/SQL libraries from `requirements-docker.txt` (`duckdb`, `sqlglot`, `pandas`, `openpyxl`, `pyarrow`, `jsonschema`).
   - Verify imports (`duckdb`, `sqlglot`, `pydantic`, `numpy`, `pandas`, `openpyxl`, `pyarrow`, `jsonschema`, `huggingface_hub`, `openai`, `vllm`, `torch`, `transformers`) during `docker build`.
   - Keep SFT training dependencies (`transformers>=5.19,<6`, `trl[peft]==1.7.1`, `flash-linear-attention`, `causal-conv1d`) documented separately in `training_code/requirements.txt` and `training_code/logs/datamate-train-requirements.lock`.
2. **Decouple Git Ignoring from Docker Inclusion for SFT Data**:
   - Anchor `.dockerignore` exclusions to repo root (`/artifacts`, `/data/train`, `/data/public_test`, `/logs`, `/tasks`, etc.) while leaving `data/finetuning/` in the build context.
   - `Dockerfile` executes `COPY data/finetuning/ /code/training_code/data/` so the full verified 84 MB SFT corpus exists inside `/code/training_code/data/` without checking `*.jsonl` into Git (`.gitignore` ignores `training_code/data/*.jsonl`).
3. **Isolate Shard Staging & Lock Files in `/tmp`**:
   - Move `_submission_lock()` in `src/datamate/gate/sharding.py` to `tempfile.gettempdir()` (keyed by SHA-256 of resolved `target_dir`).
   - Move multi-GPU `shards_root` (overridable via `DATAMATE_SHARDS_DIR`) and single-GPU `writer_dir` in `scripts/run_pipeline.py` into `tempfile.gettempdir()` and remove them in `finally:` immediately after `merge_shard_artifacts()`.
4. **Full SFT & Model Provenance Synchronization**:
   - Populate `training_code/` (`src/`, `configs/`, `data_generation/`, `logs/`, `checkpoints/`, `train.sh`) with verified `v1.2` LoRA artifacts and checksums in `training_code/data_manifest.json`.
   - Declare exact base models, pinned commit SHA `c202236235762e1c871ad0ccb60c8ee5ba337b9a`, release dates (`2026-03-02` and `2024-09-19`), licenses (`Apache-2.0` and `Qwen Research License Agreement`), parameter budget (`~8.99B + 3.09B = ~12.08B <= 15B`), and LoRA SFT metrics truthfully in `README.md` Section 8.
   - Normalize local/image file permissions (`chmod a+rX`, fixing `0600` files) and enforce pre-flight model/artifact checks in `scripts/build_and_package_docker.sh`.

## Alternatives Considered

### Rebuilding a Custom vLLM Wheel from Source on `nvidia/cuda:12.8.1-devel-ubuntu24.04`
- **Pros**: Matches exact toolkit version `12.8.1` everywhere without relying on NVIDIA CUDA 12.x minor-version compatibility.
- **Cons**: Multi-hour C++/CUDA source compilation during every clean rebuild, high fragility on custom kernels (FlashAttention / Mamba linear-attention), and breaks simple CI/build reproducibility.
- **Rejected**: `vllm/vllm-openai:v0.17.1` already ships pre-built `sm_120` kernels, matches `driver>=570,<571`, and supports `--build-arg BASE_IMAGE=...` override cleanly if a different base image is ever needed on VastAI / scoring servers.

### Checking `train_v1_2.jsonl` into `training_code/data/` in Git
- **Pros**: Zero divergence between Git checkout and Docker `/code/training_code/data/`.
- **Cons**: Commits an 84 MB JSONL blob into Git history alongside identical copies in `data/finetuning/`.
- **Rejected**: Copying `data/finetuning/` in `Dockerfile` gives identical in-container files at `/code/training_code/data/` while keeping Git clean.

## Consequences
- **Positive**: Clean `/result/` directory (no `_shards/`, `_work/`, or `.submission.lock`), intact `vllm 0.17.1` + `transformers <5` + `sm_120` runtime, reproducible `training_code/` with SHA-256 verification, and accurate model/training declarations per BTC Section 8.
- **Residual Validation Required on GPU Host**: Final `docker build`, `vllm` engine boot, and Section 10 smoke test (`docker run --rm --gpus '"device=0,1"' --network none --shm-size=16g ...`) MUST still be executed once base snapshots (`models/Qwen3.5-9B`, `models/Qwen2.5-3B-Instruct`) are downloaded onto a 2x RTX 5090 host because local verification runs on CPU without offline HF model weights.
