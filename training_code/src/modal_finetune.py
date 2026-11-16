#!/usr/bin/env python3
"""Modal runner for DataMate Qwen/Qwen3.5-9B BF16 LoRA fine-tuning (default A100-80GB).

Examples:
  1. Prepare & validate dataset + Qwen3.5-9B token lengths on CPU (no GPU cost):
     modal run finetuning/modal_finetune.py --mode prepare --run-name v1_2_a100_80gb

  2. Benchmark 5 speed configurations (smoke on longest 2 samples + 96-sample bench) on A100-80GB:
     modal run finetuning/modal_finetune.py --mode bench-suite --run-name v1_2_a100_80gb --revision <SHA>

  3. Single smoke / bench run with custom speed flags:
     modal run finetuning/modal_finetune.py --mode bench --run-name v1_2_a100_80gb --revision <SHA> --micro-batch 2 --group-by-length --no-gradient-checkpointing

  4. Full 1-epoch SFT train + download adapter-final & metrics:
     modal run finetuning/modal_finetune.py --mode train --run-name v1_2_a100_80gb --revision <SHA> --micro-batch 2 --group-by-length --download
"""

from __future__ import annotations

import gc
import io
import json
import math
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import modal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SELECTED_GPU = os.environ.get("MODAL_GPU", "A100-80GB")
HOURLY_RATE_USD = {"A100-80GB": 2.50, "A100": 2.10, "A100-40GB": 2.10}

image = (
    modal.Image.from_registry("nvidia/cuda:12.8.1-devel-ubuntu24.04", add_python="3.12")
    .apt_install("git", "ninja-build", "build-essential")
    .env(
        {
            "HF_HOME": "/vol/hf_cache",
            "TOKENIZERS_PARALLELISM": "false",
            "PYTORCH_ALLOC_CONF": "expandable_segments:True",
            "TORCH_CUDA_ARCH_LIST": "8.0",
            "MAX_JOBS": "8",
        }
    )
    .pip_install(
        "torch>=2.6,<2.10",
        "transformers>=5.19,<6",
        "trl[peft]==1.7.1",
        "datasets>=3.0",
        "jsonschema>=4.23",
        "huggingface_hub>=0.34",
        "ninja",
        "packaging",
        "wheel",
    )
    .run_commands(
        "python -m pip install --no-build-isolation 'flash-linear-attention>=0.4.2' git+https://github.com/Dao-AILab/causal-conv1d"
    )
    .add_local_dir(str(PROJECT_ROOT / "finetuning"), remote_path="/workspace/finetuning")
    .add_local_dir(str(PROJECT_ROOT / "data" / "finetuning"), remote_path="/workspace/data/finetuning")
)

app = modal.App("datamate-finetune", image=image)
volume = modal.Volume.from_name("datamate-finetune-volume", create_if_missing=True)
VOL_ROOT = Path("/vol")


def _resolve_and_cache_model(revision: str | None) -> str:
    """Resolve commit SHA if omitted and pre-download Qwen/Qwen3.5-9B weights to /vol/hf_cache."""
    from huggingface_hub import model_info, snapshot_download

    resolved = revision.strip() if revision else model_info("Qwen/Qwen3.5-9B").sha
    print(f"[Modal] Using Qwen/Qwen3.5-9B revision: {resolved}", flush=True)
    snapshot_download(repo_id="Qwen/Qwen3.5-9B", revision=resolved)
    volume.commit()
    return resolved


def _config_tag(micro_batch: int, gradient_checkpointing: bool, group_by_length: bool) -> str:
    gc_tag = "gc" if gradient_checkpointing else "nogc"
    gbl_tag = "gbl" if group_by_length else "nogbl"
    return f"b{micro_batch}-{gc_tag}-{gbl_tag}"


def _pack_run_dir(run_dir: Path, include_checkpoints: bool = False) -> bytes:
    """Tar lightweight artifacts (or full checkpoints) from /vol/runs/<run_name>."""
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory not found on Modal Volume: {run_dir}")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in sorted(run_dir.rglob("*")):
            if not item.is_file():
                continue
            rel = item.relative_to(run_dir)
            top = rel.parts[0] if rel.parts else ""
            if not include_checkpoints and top.startswith("checkpoint-"):
                continue
            tar.add(str(item), arcname=str(rel))
    return buf.getvalue()


@app.function(
    cpu=4,
    memory=32768,
    volumes={str(VOL_ROOT): volume},
    timeout=3600,
)
def prepare_on_modal_cpu(
    run_name: str,
    revision: str = "",
    max_length: int = 20_000,
) -> dict:
    """Validate schema, prefix loss-mask, and Qwen3.5-9B token stats without renting a GPU."""
    if "/workspace" not in sys.path:
        sys.path.insert(0, "/workspace")
    from huggingface_hub import model_info
    from transformers import AutoTokenizer
    from finetuning.train_datamate import MODEL, run_training

    resolved = revision.strip() or model_info(MODEL).sha
    out_dir = VOL_ROOT / "runs" / run_name / "prepare"
    stats_file = out_dir / "token_stats.json"
    rev_file = out_dir / "resolved_revision.txt"
    if stats_file.is_file() and rev_file.is_file() and rev_file.read_text(encoding="utf-8").strip() == resolved:
        stats = json.loads(stats_file.read_text(encoding="utf-8"))
        return {"revision": resolved, **stats, "cached": True}

    if out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)

    AutoTokenizer.from_pretrained(MODEL, revision=resolved)
    stats = run_training(
        train_path=Path("/workspace/data/finetuning/train_v1_2.jsonl"),
        schema_path=Path("/workspace/data/finetuning/planner_output.schema.json"),
        revision=resolved,
        mode="prepare",
        out_dir=out_dir,
        max_length=max_length,
    )
    rev_file.write_text(resolved + "\n", encoding="utf-8")
    volume.commit()
    return {"revision": resolved, **stats}


@app.function(
    gpu=SELECTED_GPU,
    memory=65536,
    volumes={str(VOL_ROOT): volume},
    timeout=36000,
)
def finetune_on_modal_gpu(
    mode: str,
    run_name: str,
    revision: str = "",
    micro_batch: int = 1,
    max_length: int = 20_000,
    lora_r: int = 16,
    lora_alpha: int = 32,
    lr: float = 1e-4,
    epochs: float = 1.0,
    save_steps: int = 100,
    gradient_checkpointing: bool = True,
    group_by_length: bool = False,
    activation_offloading: bool = False,
    resume_checkpoint: str = "",
    download_artifacts: bool = False,
    include_checkpoints: bool = False,
) -> dict:
    """Run smoke, bench, or full SFT train on Modal GPU with periodic volume commits."""
    if "/workspace" not in sys.path:
        sys.path.insert(0, "/workspace")
    from finetuning.train_datamate import run_training

    if mode not in {"smoke", "bench", "train"}:
        raise ValueError(f"Unsupported GPU mode: {mode}")

    volume.reload()
    resolved = _resolve_and_cache_model(revision or None)
    tag = _config_tag(micro_batch, gradient_checkpointing, group_by_length)
    sub_dir = "train" if mode == "train" else f"{mode}-{tag}"
    out_dir = VOL_ROOT / "runs" / run_name / sub_dir
    resume_path = (out_dir / resume_checkpoint) if resume_checkpoint else None

    if resume_path is None and out_dir.exists() and any(out_dir.iterdir()):
        raise RuntimeError(
            f"Remote output dir already exists on Volume: {out_dir}. "
            "Use a fresh --run-name or pass --resume-checkpoint."
        )

    freeze_text = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)

    metrics = run_training(
        train_path=Path("/workspace/data/finetuning/train_v1_2.jsonl"),
        schema_path=Path("/workspace/data/finetuning/planner_output.schema.json"),
        revision=resolved,
        mode=mode,
        out_dir=out_dir,
        micro_batch=micro_batch,
        max_length=max_length,
        lora_r=lora_r,
        lora_alpha=lora_alpha,
        lr=lr,
        epochs=epochs,
        save_steps=save_steps,
        gradient_checkpointing=gradient_checkpointing,
        group_by_length=group_by_length,
        activation_offloading=activation_offloading,
        resume=resume_path,
        on_save_hook=volume.commit,
    )
    (out_dir / "datamate-train-requirements.lock").write_text(freeze_text, encoding="utf-8")
    volume.commit()

    payload = {"revision": resolved, "remote_out_dir": str(out_dir), "metrics": metrics}
    if download_artifacts:
        payload["tar_bytes"] = _pack_run_dir(out_dir, include_checkpoints=include_checkpoints)
    return payload


@app.function(
    gpu=SELECTED_GPU,
    memory=65536,
    volumes={str(VOL_ROOT): volume},
    timeout=7200,
)
def benchmark_suite_on_modal_gpu(
    run_name: str,
    revision: str = "",
    max_length: int = 20_000,
    lora_r: int = 16,
    lora_alpha: int = 32,
    configs: str = "",
) -> dict:
    """Smoke-check longest 2 samples then benchmark 96 samples across speed configs in 1 GPU session."""
    if "/workspace" not in sys.path:
        sys.path.insert(0, "/workspace")
    import shutil
    import time
    import torch
    from transformers import AutoTokenizer
    from finetuning.train_datamate import MODEL, prepare, run_training

    resolved = _resolve_and_cache_model(revision or None)
    suite_root = VOL_ROOT / "runs" / run_name / f"bench_suite_{int(time.time())}"
    suite_root.mkdir(parents=True, exist_ok=True)

    train_path = Path("/workspace/data/finetuning/train_v1_2.jsonl")
    schema_path = Path("/workspace/data/finetuning/planner_output.schema.json")
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=resolved)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    dataset = prepare(train_path, tokenizer, schema_path, max_length=max_length)
    lengths = [len(ids) for ids in dataset["input_ids"]]
    sorted_lengths = sorted(lengths)
    stats = {
        "rows": len(lengths),
        "total_input_tokens": sum(lengths),
        "p50": sorted_lengths[math.ceil(0.50 * len(lengths)) - 1],
        "p95": sorted_lengths[math.ceil(0.95 * len(lengths)) - 1],
        "max": max(lengths),
    }

    gpu_name = torch.cuda.get_device_name(0)
    total_vram_gib = round(torch.cuda.get_device_properties(0).total_memory / 2**30, 2)
    hourly_rate = HOURLY_RATE_USD.get(SELECTED_GPU.upper(), 2.50)
    import importlib.util
    has_fla = importlib.util.find_spec("fla") is not None
    has_causal_conv1d = importlib.util.find_spec("causal_conv1d") is not None
    print(f"[BenchSuite] Kernels -> fla={has_fla}, causal_conv1d={has_causal_conv1d}", flush=True)

    candidates = [
        {"name": "b1_gc_baseline", "micro_batch": 1, "gradient_checkpointing": True, "group_by_length": False},
        {"name": "b2_gc_random", "micro_batch": 2, "gradient_checkpointing": True, "group_by_length": False},
        {"name": "b2_gc_gbl", "micro_batch": 2, "gradient_checkpointing": True, "group_by_length": True},
        {"name": "b4_gc_gbl", "micro_batch": 4, "gradient_checkpointing": True, "group_by_length": True},
    ]
    if configs.strip():
        wanted = {c.strip() for c in configs.split(",") if c.strip()}
        candidates = [c for c in candidates if c["name"] in wanted]
        if not candidates:
            raise ValueError(f"No matching candidates for configs={configs!r}")

    results = []
    for cfg in candidates:
        name = cfg["name"]
        print(f"\n=== [BenchSuite] Testing {name}: {cfg} ===", flush=True)
        smoke_dir = suite_root / name / "smoke"
        bench_dir = suite_root / name / "bench"
        for d in (smoke_dir, bench_dir):
            if d.exists():
                shutil.rmtree(d)

        entry = {
            **cfg,
            "gpu_name": gpu_name,
            "gpu_total_vram_gib": total_vram_gib,
            "status": "unknown",
        }
        try:
            smoke_metrics = run_training(
                train_path=train_path,
                schema_path=schema_path,
                revision=resolved,
                mode="smoke",
                out_dir=smoke_dir,
                micro_batch=cfg["micro_batch"],
                max_length=max_length,
                lora_r=lora_r,
                lora_alpha=lora_alpha,
                gradient_checkpointing=cfg["gradient_checkpointing"],
                group_by_length=cfg["group_by_length"],
                pre_tokenized=(dataset, stats, tokenizer),
            )
            entry["smoke_peak_allocated_gib"] = smoke_metrics["peak_allocated_gib"]
            entry["smoke_peak_reserved_gib"] = smoke_metrics["peak_reserved_gib"]
            entry["smoke_wall_seconds"] = smoke_metrics["wall_seconds"]

            bench_metrics = run_training(
                train_path=train_path,
                schema_path=schema_path,
                revision=resolved,
                mode="bench",
                out_dir=bench_dir,
                micro_batch=cfg["micro_batch"],
                max_length=max_length,
                lora_r=lora_r,
                lora_alpha=lora_alpha,
                gradient_checkpointing=cfg["gradient_checkpointing"],
                group_by_length=cfg["group_by_length"],
                pre_tokenized=(dataset, stats, tokenizer),
            )
            est_hours = bench_metrics["estimated_epoch_hours_wall"]
            entry.update(
                {
                    "status": "ok",
                    "bench_peak_allocated_gib": bench_metrics["peak_allocated_gib"],
                    "bench_peak_reserved_gib": bench_metrics["peak_reserved_gib"],
                    "bench_wall_seconds": bench_metrics["wall_seconds"],
                    "bench_wall_tokens_per_second": bench_metrics["bench_wall_tokens_per_second"],
                    "steady_input_tokens_per_second": round(
                        bench_metrics["steady_input_tokens_per_second"], 2
                    ),
                    "estimated_epoch_hours_wall": est_hours,
                    "estimated_epoch_hours_steady": bench_metrics["estimated_epoch_hours_steady"],
                    "estimated_epoch_cost_usd": round(est_hours * hourly_rate, 2),
                }
            )
        except Exception as exc:
            msg = str(exc)
            is_oom = "out of memory" in msg.lower() or "OutOfMemoryError" in type(exc).__name__
            entry["status"] = "OOM" if is_oom else "ERROR"
            entry["error"] = msg[:400]
            print(f"[BenchSuite] {name} failed ({entry['status']}): {entry['error']}", flush=True)
        finally:
            gc.collect()
            torch.cuda.empty_cache()

        results.append(entry)

    passing = [r for r in results if r["status"] == "ok"]
    best = min(passing, key=lambda r: r["estimated_epoch_hours_wall"]) if passing else None
    summary = {
        "revision": resolved,
        "gpu_selected": SELECTED_GPU,
        "gpu_name": gpu_name,
        "gpu_total_vram_gib": total_vram_gib,
        "hourly_rate_usd": hourly_rate,
        "dataset_stats": stats,
        "results": results,
        "recommended": best,
    }
    (suite_root / "bench_suite_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    volume.commit()
    return summary


@app.function(
    cpu=2,
    memory=8192,
    volumes={str(VOL_ROOT): volume},
    timeout=1800,
)
def download_run_from_modal(
    run_name: str,
    sub_dir: str = "train",
    include_checkpoints: bool = False,
) -> bytes:
    """Pack and stream finished artifacts from Modal Volume using a lightweight CPU container."""
    volume.reload()
    return _pack_run_dir(VOL_ROOT / "runs" / run_name / sub_dir, include_checkpoints=include_checkpoints)


def _extract_tar(tar_bytes: bytes, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        try:
            tar.extractall(path=dest, filter="data")
        except TypeError:
            tar.extractall(path=dest)


@app.local_entrypoint()
def main(
    mode: str = "prepare",
    run_name: str = "v1_2_a100_80gb",
    revision: str = "",
    micro_batch: int = 1,
    max_length: int = 20_000,
    lora_r: int = 16,
    lora_alpha: int = 32,
    lr: float = 1e-4,
    epochs: float = 1.0,
    save_steps: int = 100,
    gradient_checkpointing: bool = True,
    group_by_length: bool = False,
    activation_offloading: bool = False,
    resume_checkpoint: str = "",
    download: bool = False,
    download_only: bool = False,
    download_subdir: str = "train",
    include_checkpoints: bool = False,
    configs: str = "",
    local_output_dir: str = "",
) -> None:
    """CLI entrypoint for `modal run finetuning/modal_finetune.py ...`."""
    data_dir = PROJECT_ROOT / "data" / "finetuning"
    if not (data_dir / "train_v1_2.jsonl").is_file() or not (data_dir / "planner_output.schema.json").is_file():
        raise SystemExit(f"Missing fine-tuning dataset files in {data_dir}")

    out_local = (
        Path(local_output_dir)
        if local_output_dir
        else (PROJECT_ROOT / "artifacts" / "finetuning" / run_name)
    )

    if download_only:
        print(f"[Local] Downloading /vol/runs/{run_name}/{download_subdir} -> {out_local / download_subdir}...", flush=True)
        tar_bytes = download_run_from_modal.remote(
            run_name=run_name,
            sub_dir=download_subdir,
            include_checkpoints=include_checkpoints,
        )
        _extract_tar(tar_bytes, out_local / download_subdir)
        print(f"[Local] Downloaded cleanly to {out_local / download_subdir}", flush=True)
        return

    if mode == "prepare":
        print(f"[Local] Running prepare on Modal CPU (run_name={run_name})...", flush=True)
        res = prepare_on_modal_cpu.remote(
            run_name=run_name,
            revision=revision,
            max_length=max_length,
        )
        print(json.dumps(res, indent=2), flush=True)
        if download:
            tar_bytes = download_run_from_modal.remote(run_name=run_name, sub_dir="prepare")
            _extract_tar(tar_bytes, out_local / "prepare")
        return

    if mode == "bench-suite":
        print(
            f"[Local] Launching Modal GPU ({SELECTED_GPU}) bench-suite for run='{run_name}'...",
            flush=True,
        )
        summary = benchmark_suite_on_modal_gpu.remote(
            run_name=run_name,
            revision=revision,
            max_length=max_length,
            lora_r=lora_r,
            lora_alpha=lora_alpha,
            configs=configs,
        )
        out_local.mkdir(parents=True, exist_ok=True)
        fname = "bench_suite_batch_summary.json" if configs.strip() else "bench_suite_summary.json"
        summary_path = out_local / fname
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)
        print(f"[Local] Saved bench suite summary to: {summary_path}", flush=True)
        return

    print(
        f"[Local] Launching Modal GPU ({SELECTED_GPU}) mode='{mode}', run='{run_name}', "
        f"micro_batch={micro_batch}, gc={gradient_checkpointing}, gbl={group_by_length}, "
        f"max_length={max_length}, lora_r={lora_r}, lora_alpha={lora_alpha}...",
        flush=True,
    )
    result = finetune_on_modal_gpu.remote(
        mode=mode,
        run_name=run_name,
        revision=revision,
        micro_batch=micro_batch,
        max_length=max_length,
        lora_r=lora_r,
        lora_alpha=lora_alpha,
        lr=lr,
        epochs=epochs,
        save_steps=save_steps,
        gradient_checkpointing=gradient_checkpointing,
        group_by_length=group_by_length,
        activation_offloading=activation_offloading,
        resume_checkpoint=resume_checkpoint,
        download_artifacts=download,
        include_checkpoints=include_checkpoints,
    )
    print("[Local] Metrics:", json.dumps(result["metrics"], indent=2), flush=True)
    print(f"[Local] Pinned revision used: {result['revision']}", flush=True)

    tar_bytes = result.get("tar_bytes")
    if tar_bytes:
        tag = _config_tag(micro_batch, gradient_checkpointing, group_by_length)
        sub = "train" if mode == "train" else f"{mode}-{tag}"
        dest = out_local / sub
        _extract_tar(tar_bytes, dest)
        print(f"[Local] Artifacts downloaded to: {dest}", flush=True)
