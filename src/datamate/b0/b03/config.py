"""Đọc cấu hình TOML bằng thư viện chuẩn của Python 3.12."""

from pathlib import Path
import tomllib

from .types import GenerationOptions, ModelConfig


def load_config(path: str | Path) -> tuple[ModelConfig, GenerationOptions]:
    """Trả cấu hình engine và default sampling options.

    Đường dẫn weights tương đối được tính từ thư mục chứa file TOML, không
    phải current working directory. Khóa sai tên bị từ chối thay vì bỏ qua.
    """
    config_path = Path(path).expanduser().resolve()
    with config_path.open("rb") as stream:
        document = tomllib.load(stream)
    unknown = document.keys() - {"model", "generation"}
    if unknown:
        raise ValueError(f"Unknown config sections: {sorted(unknown)}")
    model_values = dict(document["model"])
    model_path = Path(model_values["model_path"]).expanduser()
    if not model_path.is_absolute():
        model_path = config_path.parent / model_path
    model_values["model_path"] = model_path
    return ModelConfig(**model_values), GenerationOptions(**document.get("generation", {}))
