"""Compliance tests for BTC Docker submission layout, manifests, permissions, and hygiene."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import subprocess

REPO_ROOT = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_dockerfile_avoids_cu13_conflicts_and_packages_sft_data() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG BASE_IMAGE=vllm/vllm-openai:v0.17.1" in dockerfile
    assert "FROM ${BASE_IMAGE}" in dockerfile
    assert "ENTRYPOINT []" in dockerfile
    assert "HF_HUB_OFFLINE=1" in dockerfile
    assert "TRANSFORMERS_OFFLINE=1" in dockerfile
    assert "requirements-docker.txt" in dockerfile
    assert "requirements-lock.txt" not in dockerfile
    assert "nvidia-nccl-cu12==2.27.7" not in dockerfile
    assert "COPY data/finetuning/ /code/training_code/data/" in dockerfile
    assert "chmod -R a+rX /code/models" in dockerfile


def test_requirements_docker_keeps_vllm_transformers_intact() -> None:
    req_text = (REPO_ROOT / "requirements-docker.txt").read_text(encoding="utf-8")
    pkgs = [
        line.strip().split(">=")[0].split("==")[0].split("<")[0].strip().lower()
        for line in req_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for required in ("duckdb", "sqlglot", "pandas", "openpyxl", "pyarrow", "jsonschema"):
        assert required in pkgs
    for forbidden in ("torch", "vllm", "transformers", "trl", "peft", "nvidia-nccl-cu13", "nvidia-nccl-cu12"):
        assert forbidden not in pkgs


def test_dockerignore_anchors_heavy_dirs_and_preserves_training_artifacts() -> None:
    lines = {
        line.strip()
        for line in (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    # Bare unanchored `data` or `logs` would drop data/finetuning/ or training_code/logs/
    assert "data" not in lines
    assert "logs" not in lines
    for expected_ignored in ("/data/train", "/data/public_test", "/logs", "/tasks", "/artifacts"):
        assert expected_ignored in lines
    assert "/data/finetuning" not in lines


def test_training_code_artifacts_manifest_checksums_and_model_provenance() -> None:
    manifest_path = REPO_ROOT / "training_code" / "data_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    models = {m["model_name"]: m for m in manifest["base_models"]}
    assert "Qwen/Qwen3.5-9B" in models
    assert models["Qwen/Qwen3.5-9B"]["fixed_revision"] == "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
    assert models["Qwen/Qwen3.5-9B"]["release_date"] == "2026-03-02"
    assert models["Qwen/Qwen3.5-9B"]["license"] == "Apache-2.0"

    assert "Qwen/Qwen2.5-3B-Instruct" in models
    assert models["Qwen/Qwen2.5-3B-Instruct"]["release_date"] == "2024-09-19"
    assert "Qwen Research License Agreement" in models["Qwen/Qwen2.5-3B-Instruct"]["license"]

    for rel_path, expected_digest in manifest["fine_tuning"]["artifacts_sha256"].items():
        target = REPO_ROOT / rel_path
        assert target.is_file(), f"Missing manifest artifact: {rel_path}"
        assert _sha256(target) == expected_digest

    sft_dataset = next(d for d in manifest["datasets"] if d.get("split") == "train_sft_2448")
    assert sft_dataset["row_count"] == 2448
    if (REPO_ROOT / "data" / "finetuning" / "train_v1_2.jsonl").is_file():
        for rel_file, expected_digest in sft_dataset["files_sha256"].items():
            target = REPO_ROOT / "data" / "finetuning" / rel_file
            assert target.is_file(), f"Missing dataset file: {target}"
            assert _sha256(target) == expected_digest

    for required in (
        "training_code/README.md",
        "training_code/requirements.txt",
        "training_code/train.sh",
        "training_code/src/train_datamate.py",
        "training_code/src/modal_finetune.py",
        "training_code/src/merge_lora.py",
        "training_code/configs/PLAN.md",
        "training_code/configs/planner_output.schema.json",
        "training_code/configs/qwen3_5_9b_ft_v1_2.toml",
        "training_code/configs/qwen2_5_3b_neo_grounding.toml",
        "training_code/logs/metrics.json",
        "training_code/logs/run_identity.json",
        "training_code/logs/datamate-train-requirements.lock",
        "training_code/checkpoints/README.md",
    ):
        assert (REPO_ROOT / required).is_file(), f"Missing required training artifact: {required}"


def test_readme_declares_lora_v1_2_and_exact_model_licenses() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "c202236235762e1c871ad0ccb60c8ee5ba337b9a" in readme
    assert "2026-03-02" in readme
    assert "LoRA" in readme and "v1.2" in readme
    assert "Qwen/Qwen2.5-3B-Instruct" in readme
    assert "Qwen Research License Agreement" in readme
    assert "không thực hiện fine-tuning" not in readme.lower()


def test_shell_scripts_syntax_line_endings_and_artifact_permissions() -> None:
    for rel in ("predict.sh", "training_code/train.sh", "scripts/build_and_package_docker.sh"):
        path = REPO_ROOT / rel
        raw = path.read_bytes()
        assert b"\r\n" not in raw, f"CRLF found in {rel}"
        mode = path.stat().st_mode
        assert mode & stat.S_IXUSR, f"Expected executable bit on {rel}"
        res = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
        assert res.returncode == 0, f"bash -n failed for {rel}: {res.stderr}"

    adapter_model = REPO_ROOT / "models/adapters/qwen3_5_9b_v1_2/adapter_model.safetensors"
    if adapter_model.is_file():
        assert adapter_model.stat().st_mode & stat.S_IROTH, "Adapter weights must be world-readable"

    for split_file in (REPO_ROOT / "data" / "finetuning" / "splits").glob("*.json"):
        assert split_file.stat().st_mode & stat.S_IROTH, f"Split file must be world-readable: {split_file}"


def test_gitignore_tracks_training_logs_and_skips_heavy_jsonl() -> None:
    if not (REPO_ROOT / ".git").exists():
        return
    keep_res = subprocess.run(
        ["git", "check-ignore", "training_code/logs/metrics.json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert keep_res.returncode != 0, "training_code/logs/metrics.json must not be gitignored"

    drop_res = subprocess.run(
        ["git", "check-ignore", "training_code/data/train_v1_2.jsonl"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert drop_res.returncode == 0, "training_code/data/*.jsonl must remain gitignored"
