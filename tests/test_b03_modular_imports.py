"""Unit tests for B0.3 Text-to-SQL LLM module contracts and offline behavior."""

from pathlib import Path
import tempfile
import pytest

from datamate.b0.b03 import (
    BaseLLM,
    ChatMessage,
    GenerationOptions,
    GenerationResult,
    ModelConfig,
    VLLMModel,
    load_config,
    LLMError,
    ModelLoadError,
    ModelNotLoadedError,
    InferenceError,
)


def test_b03_exports() -> None:
    """Ensure all required symbols are exported from datamate.b0.b03."""
    assert issubclass(VLLMModel, BaseLLM)
    assert issubclass(ModelNotLoadedError, LLMError)
    assert issubclass(ModelLoadError, LLMError)
    assert issubclass(InferenceError, LLMError)


def test_chat_message_validation() -> None:
    """Test ChatMessage invariants."""
    msg = ChatMessage(role="user", content="Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"

    with pytest.raises(ValueError, match="Unsupported chat role"):
        ChatMessage(role="invalid_role", content="Hello")  # type: ignore

    with pytest.raises(TypeError, match="must be a string"):
        ChatMessage(role="user", content=123)  # type: ignore


def test_generation_options_validation() -> None:
    """Test GenerationOptions sampling bounds."""
    opts = GenerationOptions(max_new_tokens=256, temperature=0.0)
    assert opts.max_new_tokens == 256
    assert opts.temperature == 0.0

    with pytest.raises(ValueError, match="max_new_tokens must be positive"):
        GenerationOptions(max_new_tokens=0)

    with pytest.raises(ValueError, match="temperature must be >= 0"):
        GenerationOptions(temperature=-0.5)

    with pytest.raises(ValueError, match="top_p must be in"):
        GenerationOptions(top_p=1.5)


def test_load_config_valid() -> None:
    """Test loading model config from TOML."""
    toml_content = """
[model]
model_path = "./non_existent_weights"
max_model_len = 4096

[generation]
temperature = 0.2
max_new_tokens = 512
"""
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
        f.write(toml_content)
        f_path = Path(f.name)

    try:
        config, opts = load_config(f_path)
        assert config.max_model_len == 4096
        assert opts.temperature == 0.2
        assert opts.max_new_tokens == 512
    finally:
        f_path.unlink(missing_ok=True)


def test_vllm_model_offline_lifecycle() -> None:
    """Test VLLMModel state without GPU/weights."""
    config = ModelConfig(model_path=Path("/tmp/non_existent_model_dir_xyz"))
    model = VLLMModel(config)
    assert not model.is_loaded

    # Trying to load non-existent model raises ModelLoadError
    with pytest.raises(ModelLoadError):
        model.load()
