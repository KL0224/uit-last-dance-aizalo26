"""Tests for B1.3 thinking token budget, reasoning boundaries, and generation diagnostics."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
from typing import Any
import pytest

from datamate.b0 import B0Pipeline
from datamate.b0.b03 import (
    BaseLLM,
    ChatMessage,
    GenerationDiagnostics,
    GenerationOptions,
    GenerationResult,
    ModelConfig,
    Text2SQLGenerator,
    Text2SQLParseError,
    VLLMModel,
    load_config,
)
from datamate.b0.b03.diagnostics import exception_diagnostics, diagnostics_dict
from datamate.b0.b03.errors import InferenceError, ModelLoadError
from datamate.b0.b05.contracts import Decision, QuestionMeta


def test_generation_options_thinking_budget_validation():
    """Verify thinking_token_budget invariants."""
    # 1. Default None is valid
    opts = GenerationOptions(max_new_tokens=1000)
    assert opts.thinking_token_budget is None

    # 2. Valid positive integer below max_new_tokens
    opts_valid = GenerationOptions(max_new_tokens=1000, thinking_token_budget=500)
    assert opts_valid.thinking_token_budget == 500

    # 3. Invalid cases: 0, negative, equal, greater, floats, booleans
    for bad_budget in (0, -10, 1000, 1500, 500.5, True, False):
        with pytest.raises(ValueError, match="thinking_token_budget must be a positive integer below max_new_tokens"):
            GenerationOptions(max_new_tokens=1000, thinking_token_budget=bad_budget)  # type: ignore


def test_qwen_toml_config_loads_thinking_budget():
    """Verify configs/qwen3_5_9b.toml loads thinking_token_budget=4096 and enable_thinking=true."""
    toml_path = Path("configs/qwen3_5_9b.toml")
    assert toml_path.is_file()

    model_cfg, gen_opts = load_config(toml_path)
    assert model_cfg.max_model_len == 32768
    assert model_cfg.chat_template_kwargs.get("enable_thinking") is True
    assert gen_opts.max_new_tokens == 8192
    assert gen_opts.thinking_token_budget == 4096


def test_vllm_sampling_params_with_thinking_budget():
    """Verify VLLMModel passes thinking_token_budget to SamplingParams when reasoning is configured."""
    class FakeSamplingParams:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    config = ModelConfig(model_path=Path("/tmp/fake_model"))
    default_opts = GenerationOptions(max_new_tokens=8192, thinking_token_budget=4096)
    model = VLLMModel(config, default_options=default_opts)
    model._engine = object()
    model._sampling_params_class = FakeSamplingParams
    model._reasoning_configured = True

    params = model._sampling_params(None)
    assert params.kwargs["max_tokens"] == 8192
    assert params.kwargs["thinking_token_budget"] == 4096

    # If engine was NOT configured for reasoning at load time, request with budget raises InferenceError
    model_unconfigured = VLLMModel(config, default_options=GenerationOptions(max_new_tokens=8192))
    model_unconfigured._engine = object()
    model_unconfigured._sampling_params_class = FakeSamplingParams
    model_unconfigured._reasoning_configured = False

    with pytest.raises(InferenceError, match="Thinking budget requires loading the engine with a default"):
        model_unconfigured._sampling_params(GenerationOptions(max_new_tokens=8192, thinking_token_budget=4096))


def test_vllm_chat_template_error_with_thinking_budget():
    """When applying chat template fails with thinking budget enabled, raise InferenceError with diagnostics."""
    class BadTokenizer:
        def apply_chat_template(self, *args, **kwargs):
            raise RuntimeError("Template syntax error in thinking tags")

    class FakeEngine:
        def get_tokenizer(self):
            return BadTokenizer()

    config = ModelConfig(
        model_path=Path("/tmp/fake_model"),
        chat_template_kwargs={"enable_thinking": True},
    )
    opts = GenerationOptions(max_new_tokens=8192, thinking_token_budget=4096)
    model = VLLMModel(config, default_options=opts)
    model._engine = FakeEngine()

    with pytest.raises(InferenceError) as exc_info:
        model.count_chat_tokens([ChatMessage(role="user", content="Test")])

    err = exc_info.value
    assert hasattr(err, "diagnostics")
    diag = err.diagnostics
    assert diag.thinking_enabled is True
    assert diag.thinking_token_budget == 4096
    assert diag.error_type == "RuntimeError"
    assert "Template syntax error" in diag.error_message


class StubLLM(BaseLLM):
    def __init__(self, result: GenerationResult):
        self.result = result
        self.default_options = GenerationOptions(max_new_tokens=8192, thinking_token_budget=4096)
        self.config = ModelConfig(
            model_path=Path("/tmp/stub_model"),
            chat_template_kwargs={"enable_thinking": True},
        )

    def load(self) -> None:
        pass

    def generate(self, prompt: str, *, options: GenerationOptions | None = None) -> GenerationResult:
        return self.result

    def chat(self, messages: list[ChatMessage], *, options: GenerationOptions | None = None) -> GenerationResult:
        return self.result

    def generate_batch(self, prompts: list[str], *, options: GenerationOptions | None = None) -> list[GenerationResult]:
        return [self.result for _ in prompts]


def test_text2sql_generator_attaches_diagnostics_on_success():
    """Text2SQLGenerator attaches complete GenerationDiagnostics to Text2SQLResult on successful parse."""
    raw = (
        "<think>Reasoning step</think>\n"
        '{"status": "answerable", "answer_type": "number", "sql": "SELECT 1"}'
    )
    res = GenerationResult(
        text=raw,
        input_tokens=150,
        output_tokens=45,
        finish_reason="stop",
        diagnostics=GenerationDiagnostics(
            thinking_enabled=True,
            thinking_token_budget=4096,
            max_new_tokens=8192,
        ),
    )
    generator = Text2SQLGenerator(StubLLM(res))
    parsed = generator.generate(context={}, question="Test?", as_of_date="2026-04-01")

    assert parsed.status == "answerable"
    assert parsed.diagnostics is not None
    assert parsed.diagnostics.parse_success is True
    assert parsed.diagnostics.raw_response == raw
    assert parsed.diagnostics.input_tokens == 150
    assert parsed.diagnostics.output_tokens == 45
    assert parsed.diagnostics.finish_reason == "stop"
    assert parsed.diagnostics.thinking_token_budget == 4096


def test_text2sql_generator_attaches_diagnostics_on_parse_failure():
    """Text2SQLGenerator attaches diagnostics to Text2SQLParseError distinguishing normal vs length limit."""
    # 1. Normal parse error
    bad_raw = "<think>Too much thinking</think>\nInvalid output without json or sql"
    res_normal = GenerationResult(
        text=bad_raw,
        input_tokens=100,
        output_tokens=50,
        finish_reason="stop",
    )
    generator_normal = Text2SQLGenerator(StubLLM(res_normal))
    with pytest.raises(Text2SQLParseError) as exc_info1:
        generator_normal.generate(context={}, question="Test?", as_of_date="2026-04-01")
    diag1 = exc_info1.value.diagnostics
    assert diag1 is not None
    assert diag1.parse_success is False
    assert diag1.failure_kind == "parse_error"
    assert diag1.raw_response == bad_raw

    # 2. Parse error after reaching output length limit
    res_length = GenerationResult(
        text=bad_raw,
        input_tokens=100,
        output_tokens=8192,
        finish_reason="length",
    )
    generator_length = Text2SQLGenerator(StubLLM(res_length))
    with pytest.raises(Text2SQLParseError) as exc_info2:
        generator_length.generate(context={}, question="Test?", as_of_date="2026-04-01")
    diag2 = exc_info2.value.diagnostics
    assert diag2 is not None
    assert diag2.parse_success is False
    assert diag2.failure_kind == "parse_error_after_length_limit"
    assert diag2.finish_reason == "length"


def test_pipeline_e2e_records_generation_diagnostics(tmp_path: Path):
    """B0Pipeline records generation_diagnostics and batch_fallback_error into detailed_logs and audit."""
    biz = tmp_path / "in" / "biz_diag"
    biz.mkdir(parents=True)
    (biz / "orders.csv").write_text("id,amount\n1,100\n", encoding="utf-8")
    (biz / "README.md").write_text("# Biz Diag\n", encoding="utf-8")

    from datamate.b0.b01.ingestion import prepare_business
    artifacts = prepare_business(biz, tmp_path / "out")
    context = json.loads((artifacts.bundle_dir / "business_context.json").read_text(encoding="utf-8"))
    table = next(t["name"] for t in context["schema_catalog"]["tables"] if t["name"].startswith("orders"))

    raw = f'{{"status": "answerable", "answer_type": "number", "sql": "SELECT SUM(amount) FROM {table}"}}'
    res = GenerationResult(
        text=raw,
        input_tokens=80,
        output_tokens=25,
        finish_reason="stop",
        diagnostics=GenerationDiagnostics(
            thinking_enabled=True,
            thinking_token_budget=4096,
            max_new_tokens=8192,
        ),
    )
    pipeline = B0Pipeline(generator=Text2SQLGenerator(StubLLM(res)))
    out_dir = tmp_path / "pipe_out"

    questions = [
        {"id": "q_diag", "business_id": "biz_diag", "question": "Total?", "as_of_date": "2026-04-01"},
    ]
    outcomes = pipeline.run_questions(
        questions=questions,
        bundles={"biz_diag": artifacts.bundle_dir},
        output_dir=out_dir,
    )
    assert len(outcomes) == 1
    assert outcomes[0].decision == Decision.ANSWER

    detailed_log_file = out_dir / "detailed_logs.jsonl"
    assert detailed_log_file.is_file()
    entry = json.loads(detailed_log_file.read_text(encoding="utf-8").strip())
    assert entry["id"] == "q_diag"
    assert len(entry["attempts"]) == 1
    attempt_log = entry["attempts"][0]
    assert "generation_diagnostics" in attempt_log
    diag_data = attempt_log["generation_diagnostics"]
    assert diag_data["thinking_token_budget"] == 4096
    assert diag_data["parse_success"] is True
    assert diag_data["finish_reason"] == "stop"
