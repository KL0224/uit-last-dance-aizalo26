"""Đọc cấu hình TOML bằng thư viện chuẩn của Python 3.12."""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import TYPE_CHECKING, Any

from .types import GenerationOptions, ModelConfig

if TYPE_CHECKING:
    from datamate.voting import VotingConfig


def _resolve_relative_path(raw: str | Path, base_dir: Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else base_dir / path


def _load_toml_sections(
    path: str | Path,
) -> tuple[ModelConfig, GenerationOptions, dict[str, Any] | None]:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("rb") as stream:
        document = tomllib.load(stream)
    unknown = document.keys() - {"model", "generation", "voting"}
    if unknown:
        raise ValueError(f"Unknown config sections: {sorted(unknown)}")
    model_values = dict(document["model"])
    model_values["model_path"] = _resolve_relative_path(model_values["model_path"], config_path.parent)
    if "lora_path" in model_values:
        raw_lora = model_values["lora_path"]
        model_values["lora_path"] = (
            _resolve_relative_path(raw_lora, config_path.parent)
            if raw_lora not in (None, "")
            else None
        )
    model_cfg = ModelConfig(**model_values)
    gen_opts = GenerationOptions(**document.get("generation", {}))
    voting_raw = dict(document["voting"]) if "voting" in document else None
    return model_cfg, gen_opts, voting_raw


def load_config(path: str | Path) -> tuple[ModelConfig, GenerationOptions]:
    """Trả cấu hình engine và default sampling options.

    Đường dẫn weights tương đối được tính từ thư mục chứa file TOML, không
    phải current working directory. Khóa sai tên bị từ chối thay vì bỏ qua.
    """
    model_cfg, gen_opts, voting_raw = _load_toml_sections(path)
    if voting_raw is not None:
        from datamate.voting import VotingConfig

        VotingConfig(**voting_raw)
    return model_cfg, gen_opts


def load_pipeline_config(
    path: str | Path,
    *,
    default_voting: VotingConfig | None = None,
) -> tuple[ModelConfig, GenerationOptions, VotingConfig]:
    """Đọc đầy đủ [model], [generation] và tùy chọn [voting] từ file TOML."""
    from datamate.voting import VotingConfig

    model_cfg, gen_opts, voting_raw = _load_toml_sections(path)
    if voting_raw is not None:
        voting_cfg = VotingConfig(**voting_raw)
    elif default_voting is not None:
        voting_cfg = default_voting
    else:
        voting_cfg = VotingConfig()
    return model_cfg, gen_opts, voting_cfg
