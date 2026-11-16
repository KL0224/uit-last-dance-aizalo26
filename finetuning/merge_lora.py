#!/usr/bin/env python3
"""Merge a PEFT LoRA adapter into a standalone Qwen3.5-9B text snapshot for offline serving."""

from __future__ import annotations

import argparse
from pathlib import Path


def merge_adapter(
    base_model: str,
    adapter_dir: Path,
    output_dir: Path,
    *,
    revision: str | None = None,
) -> Path:
    """Load Qwen3.5-9B text backbone + PEFT LoRA adapter, merge weights, and save cleanly."""
    import torch
    from peft import PeftModel
    from transformers import AutoConfig, AutoTokenizer, Qwen3_5ForCausalLM

    adapter_path = Path(adapter_dir).expanduser().resolve()
    if not (adapter_path / "adapter_config.json").is_file():
        raise FileNotFoundError(f"Missing adapter_config.json in {adapter_path}")

    out_path = Path(output_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    load_kwargs: dict = {}
    if revision:
        load_kwargs["revision"] = revision

    config = AutoConfig.from_pretrained(base_model, **load_kwargs).text_config
    base = Qwen3_5ForCausalLM.from_pretrained(
        base_model,
        config=config,
        torch_dtype=torch.bfloat16,
        key_mapping={r"^model\.language_model\.": "model."},
        **load_kwargs,
    )
    peft_model = PeftModel.from_pretrained(base, str(adapter_path))
    merged = peft_model.merge_and_unload()
    merged.save_pretrained(str(out_path), safe_serialization=True)

    tokenizer_src = str(adapter_path) if (adapter_path / "tokenizer.json").is_file() else base_model
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_src, **(load_kwargs if tokenizer_src == base_model else {}))
    tokenizer.save_pretrained(str(out_path))
    return out_path


def parse_args() -> argparse.Namespace:
    default_base = (
        "models/Qwen3.5-9B"
        if Path("models/Qwen3.5-9B/config.json").is_file()
        else "Qwen/Qwen3.5-9B"
    )
    parser = argparse.ArgumentParser(description="Merge LoRA adapter into Qwen3.5-9B standalone weights")
    parser.add_argument(
        "--base-model",
        default=default_base,
        help="Base model ID or local snapshot path (auto-detects models/Qwen3.5-9B when present)",
    )
    parser.add_argument("--revision", default="", help="Optional HuggingFace commit SHA revision")
    parser.add_argument(
        "--adapter-dir",
        type=Path,
        default=Path("models/adapters/qwen3_5_9b_v1_2"),
        help="Path to PEFT LoRA adapter directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("models/qwen3_5_9b_ft_v1_2"),
        help="Destination directory for merged standalone weights",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out = merge_adapter(
        base_model=args.base_model,
        adapter_dir=args.adapter_dir,
        output_dir=args.output_dir,
        revision=args.revision.strip() or None,
    )
    print(f"Merged standalone model saved to: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
