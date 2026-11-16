"""Fine-tune Qwen/Qwen3.5-9B (BF16 base + LoRA) for DataMate Planner v1.2."""

from __future__ import annotations

import argparse
import gc
import hashlib
import inspect
import json
import math
import os
import random
import time
from collections import Counter
from pathlib import Path
from typing import Callable

import torch
from datasets import Dataset
from jsonschema import Draft202012Validator, FormatChecker
from peft import LoraConfig, TaskType, get_peft_model
from transformers import (
    AutoConfig,
    AutoTokenizer,
    Qwen3_5ForCausalLM,
    TrainerCallback,
    set_seed,
)
from trl import SFTConfig, SFTTrainer

MODEL = "Qwen/Qwen3.5-9B"
DEFAULT_MAX_LENGTH = 20_000
SEED = 3407
TARGET_COUNTS = {
    **dict.fromkeys(("q_proj", "k_proj", "v_proj", "o_proj"), 8),
    **dict.fromkeys(("in_proj_qkv", "in_proj_z", "out_proj"), 24),
    **dict.fromkeys(("gate_proj", "up_proj", "down_proj"), 32),
}


def load_text_model(revision: str):
    """Load the text-only backbone of Qwen3.5-9B in BF16 without vision/MTP weights."""
    config = AutoConfig.from_pretrained(MODEL, revision=revision).text_config
    config.use_cache = False
    model, info = Qwen3_5ForCausalLM.from_pretrained(
        MODEL,
        config=config,
        revision=revision,
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
        output_loading_info=True,
        key_mapping={r"^model\.language_model\.": "model."},
    )
    bad_keys = [
        k
        for k in info.get("unexpected_keys", [])
        if not k.startswith(("model.visual.", "visual.", "mtp.", "model.mtp."))
    ]
    if info.get("missing_keys") or info.get("mismatched_keys") or bad_keys:
        raise RuntimeError(f"Checkpoint load failed: {info}")
    return model


def render_tokens(tokenizer, messages: list[dict], generation_prompt: bool) -> list[int]:
    """Tokenize chat messages with thinking disabled to match Planner v1.2 training."""
    return tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        return_dict=True,
        add_generation_prompt=generation_prompt,
        enable_thinking=False,
    )["input_ids"]


def _split_chat_item(item: dict) -> tuple[list[dict], list[dict]]:
    """Support both SFT_v1_2_final (`messages`) and legacy (`prompt`/`completion`) rows."""
    if "messages" in item:
        msgs = item["messages"]
        if len(msgs) != 3:
            raise ValueError(f"Expected 3 messages, got {len(msgs)}")
        prompt, completion = msgs[:2], msgs[2:]
    elif "prompt" in item and "completion" in item:
        prompt, completion = item["prompt"], item["completion"]
    else:
        raise KeyError("Expected either 'messages' or ('prompt', 'completion') in JSONL row")

    if [m["role"] for m in prompt] != ["system", "user"]:
        raise ValueError("Expected system/user messages")
    if [m["role"] for m in completion] != ["assistant"]:
        raise ValueError("Expected one assistant message")
    return prompt, completion


def prepare(path: Path, tokenizer, schema_path: Path, max_length: int = DEFAULT_MAX_LENGTH) -> Dataset:
    """Validate target JSON contracts, verify assistant prefix boundary, and tokenize."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    end_token = tokenizer.convert_tokens_to_ids("<|im_end|>")
    if "<|im_end|>" not in tokenizer.get_vocab():
        raise ValueError("Qwen tokenizer is missing <|im_end|>")

    rows = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                prompt, completion = _split_chat_item(item)
                target = json.loads(completion[0]["content"])
                validator.validate(target)
                if target["status"] not in {"answerable", "unanswerable"}:
                    raise ValueError(f"Unexpected status in SFT export: {target['status']}")

                prefix = render_tokens(tokenizer, prompt, True)
                full = render_tokens(tokenizer, prompt + completion, False)
                if full[: len(prefix)] != prefix:
                    raise ValueError("Mismatch in Qwen assistant prefix")
                suffix = full[len(prefix) :]
                if not suffix or suffix.count(end_token) != 1:
                    raise ValueError("Expected one end-of-turn token in completion")
                if len(full) > max_length:
                    raise ValueError(f"{len(full)} tokens exceeds {max_length}")

                rows.append({
                    "input_ids": full,
                    "labels": [-100] * len(prefix) + suffix,
                    "length": len(full),
                })
            except Exception as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc

    if not rows:
        raise ValueError("Empty training dataset")
    return Dataset.from_list(rows)


class CompletionCollator:
    """Dynamic right-padding to multiples of 8 while keeping custom prompt -100 masks."""

    def __init__(self, pad_token_id: int) -> None:
        self.pad_token_id = pad_token_id

    def __call__(self, rows: list[dict]) -> dict[str, torch.Tensor]:
        width = 8 * math.ceil(max(len(row["input_ids"]) for row in rows) / 8)
        batch: dict[str, list[list[int]]] = {"input_ids": [], "attention_mask": [], "labels": []}
        for row in rows:
            length = len(row["input_ids"])
            pad = width - length
            batch["input_ids"].append(row["input_ids"] + [self.pad_token_id] * pad)
            batch["attention_mask"].append([1] * length + [0] * pad)
            batch["labels"].append(row["labels"] + [-100] * pad)
        return {key: torch.tensor(value, dtype=torch.long) for key, value in batch.items()}


class LengthBucketSampler(torch.utils.data.Sampler[int]):
    """Group similarly sized samples within mega-batches to reduce intra-batch padding."""

    def __init__(self, lengths: list[int], batch_size: int, seed: int) -> None:
        self.lengths = lengths
        self.batch_size = max(1, batch_size)
        self.seed = seed
        self.epoch = 0

    def __iter__(self):
        rng = random.Random(self.seed + self.epoch)
        self.epoch += 1
        indices = list(range(len(self.lengths)))
        rng.shuffle(indices)
        mega_size = max(self.batch_size, 50 * self.batch_size)
        batches: list[list[int]] = []
        for start in range(0, len(indices), mega_size):
            chunk = sorted(indices[start : start + mega_size], key=self.lengths.__getitem__, reverse=True)
            for b_start in range(0, len(chunk), self.batch_size):
                batches.append(chunk[b_start : b_start + self.batch_size])
        rng.shuffle(batches)
        for batch in batches:
            yield from batch

    def __len__(self) -> int:
        return len(self.lengths)


class LengthBucketedSFTTrainer(SFTTrainer):
    """SFTTrainer variant that uses LengthBucketSampler cleanly across Transformers/TRL versions."""

    def _get_train_sampler(self, train_dataset=None):
        ds = train_dataset if train_dataset is not None else self.train_dataset
        return LengthBucketSampler(
            ds["length"],
            batch_size=self.args.per_device_train_batch_size,
            seed=self.args.data_seed if self.args.data_seed is not None else self.args.seed,
        )


class RunMonitor(TrainerCallback):
    """Track non-padding throughput during bench, fail fast on NaN/Inf, and persist checkpoints."""

    def __init__(
        self,
        benchmark: bool,
        bench_end_step: int = 6,
        on_save_hook: Callable[[], None] | None = None,
    ) -> None:
        self.benchmark = benchmark
        self.bench_end_step = bench_end_step
        self.on_save_hook = on_save_hook
        self.start: tuple[float, int] | None = None
        self.steady_tps: float | None = None

    def on_train_begin(self, args, state, control, **kwargs):
        torch.cuda.reset_peak_memory_stats()

    def on_step_end(self, args, state, control, **kwargs):
        if not self.benchmark:
            return
        if state.global_step in (2, self.bench_end_step):
            torch.cuda.synchronize()
            point = (time.perf_counter(), state.num_input_tokens_seen)
            if state.global_step == 2:
                self.start = point
            elif self.start is not None:
                elapsed = point[0] - self.start[0]
                if elapsed > 0:
                    self.steady_tps = (point[1] - self.start[1]) / elapsed

    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs and any(
            k in logs and not math.isfinite(float(logs[k])) for k in ("loss", "grad_norm")
        ):
            raise RuntimeError(f"Training loss or gradient norm is non-finite: {logs}")

    def on_save(self, args, state, control, **kwargs):
        if self.on_save_hook is not None:
            self.on_save_hook()


def file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def run_training(
    *,
    train_path: Path,
    schema_path: Path,
    revision: str,
    mode: str,
    out_dir: Path,
    micro_batch: int = 1,
    max_length: int = DEFAULT_MAX_LENGTH,
    lora_r: int = 16,
    lora_alpha: int = 32,
    lr: float = 1e-4,
    epochs: float = 1.0,
    save_steps: int = 100,
    gradient_checkpointing: bool = True,
    group_by_length: bool = False,
    bench_steps: int = 6,
    activation_offloading: bool = False,
    resume: Path | None = None,
    on_save_hook: Callable[[], None] | None = None,
    pre_tokenized: tuple[Dataset, dict, object] | None = None,
) -> dict:
    """Execute prepare, smoke, bench, or full SFT training and return summary metrics."""
    if resume and (
        mode != "train"
        or not resume.is_dir()
        or resume.resolve().parent != out_dir.resolve()
    ):
        raise ValueError("Resume requires a checkpoint inside the selected train output directory")
    if out_dir.exists() and any(out_dir.iterdir()) and not resume:
        raise ValueError(f"Output directory is not empty (pass --resume or pick a new dir): {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    set_seed(SEED)
    if pre_tokenized is not None:
        dataset, stats, tokenizer = pre_tokenized
        lengths = [len(ids) for ids in dataset["input_ids"]]
    else:
        tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=revision)
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
        print(json.dumps(stats), flush=True)
    if mode == "prepare":
        (out_dir / "token_stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
        return stats

    if int(os.getenv("WORLD_SIZE", "1")) != 1:
        raise RuntimeError("This entry point is configured for one GPU")
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("A CUDA GPU with BF16 support is required")
    print(torch.cuda.get_device_properties(0), flush=True)

    accum = max(1, 8 // micro_batch)
    bench_tokens = 0
    if mode == "smoke":
        longest = sorted(range(len(lengths)), key=lengths.__getitem__, reverse=True)
        if len(longest) < 2:
            raise ValueError("Smoke test requires at least two examples")
        dataset = dataset.select(longest[:2] * 4)
    elif mode == "bench":
        bench_samples = bench_steps * 8
        if len(dataset) < bench_samples:
            raise ValueError(f"Benchmark requires at least {bench_samples} examples")
        bench_indices = random.Random(SEED).sample(range(len(dataset)), bench_samples)
        dataset = dataset.select(bench_indices)
        bench_tokens = sum(lengths[i] for i in bench_indices)

    identity = {
        "model": MODEL,
        "revision": revision,
        "dataset_sha256": file_sha256(train_path),
        "schema_sha256": file_sha256(schema_path),
        "max_length": max_length,
        "mode": mode,
        "micro_batch": micro_batch,
        "accumulation": accum,
        "gradient_checkpointing": gradient_checkpointing,
        "group_by_length": group_by_length,
        "lora_r": lora_r,
        "lora_alpha": lora_alpha,
        "lr": lr,
        "epochs": epochs,
        "seed": SEED,
        "script_sha256": file_sha256(Path(__file__)),
    }
    identity_file = out_dir / "run_identity.json"
    if resume and json.loads(identity_file.read_text(encoding="utf-8")) != identity:
        raise ValueError("Resume configuration or dataset differs from the original run")
    identity_file.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")

    model = None
    trainer = None
    try:
        model = load_text_model(revision)
        observed = Counter(
            name.rsplit(".", 1)[-1]
            for name, layer in model.named_modules()
            if isinstance(layer, torch.nn.Linear) and name.rsplit(".", 1)[-1] in TARGET_COUNTS
        )
        if observed != Counter(TARGET_COUNTS):
            raise RuntimeError(f"Unexpected projection counts: {observed}")

        lora_cfg = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=lora_r,
            lora_alpha=lora_alpha,
            lora_dropout=0.05,
            bias="none",
            target_modules=list(TARGET_COUNTS),
        )
        peft_kwargs = {"revision": revision} if "revision" in inspect.signature(get_peft_model).parameters else {}
        model = get_peft_model(model, lora_cfg, **peft_kwargs)
        model.print_trainable_parameters()

        monitor = RunMonitor(mode == "bench", bench_end_step=bench_steps, on_save_hook=on_save_hook)
        steps = {"smoke": 1, "bench": bench_steps, "train": -1}[mode]
        sft_kwargs: dict = {
            "output_dir": str(out_dir),
            "seed": SEED,
            "data_seed": SEED,
            "bf16": True,
            "fp16": False,
            "max_length": max_length,
            "packing": False,
            "dataset_kwargs": {"skip_prepare_dataset": True},
            "remove_unused_columns": False,
            "completion_only_loss": False,
            "loss_type": "chunked_nll",
            "per_device_train_batch_size": micro_batch,
            "gradient_accumulation_steps": accum,
            "gradient_checkpointing": gradient_checkpointing,
            "optim": "adamw_torch",
            "learning_rate": lr,
            "weight_decay": 0.0,
            "lr_scheduler_type": "cosine",
            "warmup_steps": 0.03,
            "max_grad_norm": 1.0,
            "num_train_epochs": epochs,
            "max_steps": steps,
            "eval_strategy": "no",
            "logging_steps": 10 if mode == "train" else 1,
            "logging_nan_inf_filter": False,
            "include_num_input_tokens_seen": "non_padding" if mode == "bench" else "no",
            "save_strategy": "steps" if mode == "train" else "no",
            "save_steps": save_steps,
            "save_total_limit": 4,
            "save_only_model": False,
            "report_to": "none",
        }
        if gradient_checkpointing:
            sft_kwargs["gradient_checkpointing_kwargs"] = {"use_reentrant": False}
        if activation_offloading:
            sft_kwargs["activation_offloading"] = True

        trainer_cls = LengthBucketedSFTTrainer if group_by_length else SFTTrainer
        trainer = trainer_cls(
            model=model,
            processing_class=tokenizer,
            train_dataset=dataset,
            data_collator=CompletionCollator(tokenizer.pad_token_id),
            callbacks=[monitor],
            args=SFTConfig(**sft_kwargs),
        )
        t_start = time.perf_counter()
        result = trainer.train(resume_from_checkpoint=str(resume) if resume else None)
        torch.cuda.synchronize()
        wall_seconds = time.perf_counter() - t_start

        metrics = {
            **stats,
            **result.metrics,
            "micro_batch": micro_batch,
            "accumulation": accum,
            "gradient_checkpointing": gradient_checkpointing,
            "group_by_length": group_by_length,
            "wall_seconds": round(wall_seconds, 2),
            "optimizer_steps": trainer.state.global_step,
            "peak_allocated_gib": round(torch.cuda.max_memory_allocated() / 2**30, 3),
            "peak_reserved_gib": round(torch.cuda.max_memory_reserved() / 2**30, 3),
            "steady_input_tokens_per_second": monitor.steady_tps,
        }
        if mode == "bench":
            if not monitor.steady_tps or monitor.steady_tps <= 0:
                raise RuntimeError("Non-padding input-token tracking produced no benchmark")
            metrics["bench_tokens"] = bench_tokens
            metrics["bench_wall_tokens_per_second"] = round(bench_tokens / wall_seconds, 2)
            metrics["estimated_epoch_hours_steady"] = round(sum(lengths) / monitor.steady_tps / 3600, 3)
            metrics["estimated_epoch_hours_wall"] = round(
                (sum(lengths) / bench_tokens) * wall_seconds / 3600, 3
            )
            metrics["estimated_epoch_hours"] = metrics["estimated_epoch_hours_wall"]
        if mode == "train":
            trainer.save_model(str(out_dir / "adapter-final"))
            tokenizer.save_pretrained(out_dir / "adapter-final")
            trainer.save_state()
            if on_save_hook is not None:
                on_save_hook()
        (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(metrics, indent=2), flush=True)
        return metrics
    finally:
        del trainer, model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def main() -> None:
    p = argparse.ArgumentParser(description="Fine-tune DataMate Qwen3.5-9B BF16 LoRA.")
    p.add_argument("--train", type=Path, default=Path("data/finetuning/train_v1_2.jsonl"))
    p.add_argument("--schema", type=Path, default=Path("data/finetuning/planner_output.schema.json"))
    p.add_argument("--revision", required=True)
    p.add_argument("--mode", choices=("prepare", "smoke", "bench", "train"), required=True)
    p.add_argument("--micro-batch", type=int, choices=(1, 2, 4), default=1)
    p.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH)
    p.add_argument("--r", type=int, default=16)
    p.add_argument("--alpha", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--epochs", type=float, default=1.0)
    p.add_argument("--save-steps", type=int, default=100)
    p.add_argument("--no-gradient-checkpointing", action="store_true")
    p.add_argument("--group-by-length", action="store_true")
    p.add_argument("--activation-offloading", action="store_true")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--resume", type=Path)
    a = p.parse_args()
    run_training(
        train_path=a.train,
        schema_path=a.schema,
        revision=a.revision,
        mode=a.mode,
        out_dir=a.out,
        micro_batch=a.micro_batch,
        max_length=a.max_length,
        lora_r=a.r,
        lora_alpha=a.alpha,
        lr=a.lr,
        epochs=a.epochs,
        save_steps=a.save_steps,
        gradient_checkpointing=not a.no_gradient_checkpointing,
        group_by_length=a.group_by_length,
        activation_offloading=a.activation_offloading,
        resume=a.resume,
    )


if __name__ == "__main__":
    main()
