"""Tests for the Qwen 3B grounding adapter backed by the shared vLLM layer."""

from __future__ import annotations

from pathlib import Path

from datamate.planner import ChatMessage, GenerationResult
from datamate.grounding.contracts import OperationKind, QuestionRequest
from datamate.grounding.engine import QuestionGroundingEngine
from datamate.grounding.llm_fallback import (
    StructuredLLMParser,
    create_qwen3b_vllm_parser,
)
from datamate.grounding.mock_provider import MockBusinessContextProvider


class FakeVLLMModel:
    """GPU-free substitute preserving the public VLLMModel contract."""

    instances: list["FakeVLLMModel"] = []

    def __init__(self, config, default_options=None) -> None:
        self.config = config
        self.default_options = default_options
        self.loaded = False
        self.messages: list[ChatMessage] = []
        self.options = None
        self.count_calls = 0
        self.__class__.instances.append(self)

    def load(self) -> None:
        self.loaded = True

    def count_chat_tokens(self, messages) -> int:
        self.count_calls += 1
        return sum(len(message.content.split()) for message in messages)

    def chat(self, messages, *, options=None) -> GenerationResult:
        self.messages = list(messages)
        self.options = options
        return GenerationResult(
            text=(
                '{"operation":"sum","target_metrics":["revenue"],'
                '"entities":[],"filters":[],"group_by":[],'
                '"top_k":null,"sort_order":"desc",'
                '"answer_type_hint":"number"}'
            ),
            input_tokens=30,
            output_tokens=20,
            finish_reason="stop",
        )


def test_create_qwen3b_vllm_parser_loads_model_and_calls_chat(
    tmp_path: Path, monkeypatch
) -> None:
    model_dir = tmp_path / "Qwen2.5-3B-Instruct"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    config_path = tmp_path / "grounding.toml"
    config_path.write_text(
        f"""
[model]
model_path = "{model_dir}"
dtype = "bfloat16"
max_model_len = 4096
gpu_memory_utilization = 0.35
tensor_parallel_size = 1
max_num_seqs = 8
trust_remote_code = false

[generation]
max_new_tokens = 512
temperature = 0.0
top_p = 1.0
top_k = -1
repetition_penalty = 1.0
presence_penalty = 0.0
stop = []
""".strip(),
        encoding="utf-8",
    )
    FakeVLLMModel.instances.clear()
    monkeypatch.setattr("datamate.planner.VLLMModel", FakeVLLMModel)

    parser = create_qwen3b_vllm_parser(config_path)
    intent = parser.extract_intent(
        question="Tổng doanh thu tháng này là bao nhiêu?",
        as_of_date="2026-08-27",
        available_metrics=("revenue",),
        available_tables=("orders",),
    )

    model = FakeVLLMModel.instances[0]
    assert model.loaded is True
    assert [message.role for message in model.messages] == ["system", "user"]
    assert model.options.temperature == 0.0
    assert model.count_calls >= 1
    assert intent.target_metrics == ("revenue",)
    assert intent.used_llm_fallback is True


def test_engine_factory_wires_qwen3b_parser(monkeypatch) -> None:
    response = (
        '{"operation":"ratio","target_metrics":["revenue"],'
        '"entities":[],"filters":[],"group_by":["customer"],'
        '"top_k":null,"sort_order":"desc",'
        '"answer_type_hint":"percent"}'
    )
    structured_parser = StructuredLLMParser(
        chat_fn=lambda _system, _user: response
    )
    monkeypatch.setattr(
        "datamate.grounding.llm_fallback.create_qwen3b_vllm_parser",
        lambda _config_path: structured_parser,
    )

    engine = QuestionGroundingEngine.from_qwen3b_vllm("grounding.toml")
    grounded = engine.ground(
        QuestionRequest(
            question_id="q-vllm",
            business_id="mock_fnb_003",
            question="Mức độ đóng góp tương đối của tệp VIP?",
            as_of_date="2026-08-27",
        ),
        MockBusinessContextProvider.create_fnb_context(),
    )

    assert grounded.intent.used_llm_fallback is True
    assert grounded.intent.operation == OperationKind.RATIO
