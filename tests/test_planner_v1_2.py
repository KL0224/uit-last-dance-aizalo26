"""Tests for planner.v1.2 prompt contract, output parser, LoRA config, and integration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from datamate.gate.contracts import Decision
from datamate.ingestion.ingestion import prepare_business
from datamate.pipeline import DataMatePipeline
from datamate.planner.base import BaseLLM
from datamate.planner.generator import Text2SQLGenerator
from datamate.planner.parser import parse_text2sql_response
from datamate.planner.types import (
    ChatMessage,
    GenerationOptions,
    GenerationResult,
    Text2SQLResult,
)


def test_v1_2_system_prompt_matches_manifest_sha256() -> None:
    """Task 2: SYSTEM_PROMPT_V1_2 must match manifest.json system_prompt_sha256 byte-for-byte."""
    from datamate.planner.prompt_v1_2 import SYSTEM_PROMPT_V1_2

    manifest = json.loads(Path("data/finetuning/manifest.json").read_text(encoding="utf-8"))
    actual_sha = hashlib.sha256(SYSTEM_PROMPT_V1_2.encode("utf-8")).hexdigest()
    assert actual_sha == manifest["system_prompt_sha256"]


def test_v1_2_user_payload_matches_training_contract(tmp_path: Path) -> None:
    """Task 2: build_v1_2_user_payload builds exact planner.v1.2-input.1 JSON from runtime context."""
    from datamate.planner.prompt_v1_2 import (
        SYSTEM_PROMPT_V1_2,
        build_v1_2_messages,
        build_v1_2_repair_messages,
        build_v1_2_user_payload,
    )

    biz_dir = tmp_path / "biz_p"
    biz_dir.mkdir()
    (biz_dir / "orders.csv").write_text(
        "ma_don,ngay_ban,trang_thai,tong_tien\n"
        "D1,2025-07-01,completed,100\n"
        "D2,2025-07-15,cancelled,50\n",
        encoding="utf-8",
    )
    cal = tmp_path / "calendar.csv"
    cal.write_text(
        "date,weekday,lunar_day,lunar_month,lunar_year,lunar_leap,holiday\n"
        "2025-07-01,2,7,6,2025,false,\n",
        encoding="utf-8",
    )
    art = prepare_business(biz_dir, tmp_path / "bundles", calendar=cal)
    ctx = DataMatePipeline.load_context(art.bundle_dir)

    payload_str = build_v1_2_user_payload(
        context=ctx,
        question="Doanh thu tháng này?",
        as_of_date="2025-07-20",
        industry="Cà phê",
        grounded_hint=None,
    )
    payload = json.loads(payload_str)

    assert list(payload.keys()) == [
        "question",
        "as_of_date",
        "context",
        "industry",
        "grounded_hint",
        "retry",
    ]
    assert payload["question"] == "Doanh thu tháng này?"
    assert payload["as_of_date"] == "2025-07-20"
    assert payload["industry"] == "Cà phê"
    assert payload["retry"] is None
    assert list(payload["context"].keys()) == ["schema", "relations", "rules", "date_context"]
    dc = payload["context"]["date_context"]
    assert dc["as_of_weekday"] == "Chủ Nhật"
    assert dc["calendar_table"] == "calendar"
    orders_tbl = next(t for t in payload["context"]["schema"] if t["table"].startswith("orders"))
    assert any(c["name"] == "trang_thai" and c.get("values") == ["cancelled", "completed"] for c in orders_tbl["columns"])
    assert any(k.endswith(".ngay_ban") and v == ["2025-07-01", "2025-07-15"] for k, v in dc["date_coverage"].items())

    msgs = build_v1_2_messages(context=ctx, question="Q?", as_of_date="2025-07-20")
    assert len(msgs) == 2
    assert msgs[0] == ChatMessage(role="system", content=SYSTEM_PROMPT_V1_2)

    repair_msgs = build_v1_2_repair_messages(
        context=ctx,
        question="Q?",
        as_of_date="2025-07-20",
        previous_sql="SELECT bad FROM orders",
        error_message="[BinderError] Column bad not found",
        previous_plan={"grain": "order"},
        error_code="SCHEMA_ERROR",
        failed_checks=["SCHEMA_ERROR"],
    )
    repair_payload = json.loads(repair_msgs[1].content)
    assert repair_payload["retry"] == {
        "previous_plan": {"grain": "order"},
        "previous_sql": "SELECT bad FROM orders",
        "error_code": "SCHEMA_ERROR",
        "error_message": "[BinderError] Column bad not found",
        "failed_checks": ["SCHEMA_ERROR"],
    }


def test_model_config_and_vllm_lora_support(tmp_path: Path, monkeypatch) -> None:
    """Task 5: ModelConfig, load_config, and VLLMModel resolve and wire LoRA + prompt_format."""
    import sys
    from types import ModuleType, SimpleNamespace
    from datamate.planner import ModelConfig, VLLMModel, load_config
    from datamate.planner.errors import ModelLoadError

    with pytest.raises(ValueError, match="prompt_format"):
        ModelConfig(model_path=tmp_path, prompt_format="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="max_lora_rank"):
        ModelConfig(model_path=tmp_path, max_lora_rank=0)

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    model_dir = tmp_path / "base_model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    lora_dir = tmp_path / "adapter"
    lora_dir.mkdir()
    (lora_dir / "adapter_config.json").write_text("{}", encoding="utf-8")

    toml_file = cfg_dir / "ft.toml"
    toml_file.write_text(
        '[model]\n'
        'model_path = "../base_model"\n'
        'lora_path = "../adapter"\n'
        'max_lora_rank = 16\n'
        'prompt_format = "v1_2"\n'
        '[model.chat_template_kwargs]\n'
        'enable_thinking = false\n'
        '[generation]\n'
        'max_new_tokens = 2048\n'
        'temperature = 0.5\n'
        'seed = 42\n',
        encoding="utf-8",
    )

    model_cfg, gen_opts = load_config(toml_file)
    assert model_cfg.prompt_format == "v1_2"
    assert model_cfg.lora_path == lora_dir.resolve()
    assert model_cfg.max_lora_rank == 16
    assert gen_opts.temperature == 0.5
    assert gen_opts.seed == 42

    # Missing adapter_config.json raises ModelLoadError
    bad_cfg = ModelConfig(model_path=model_dir, lora_path=tmp_path / "missing_adapter")
    with pytest.raises(ModelLoadError, match="LoRA"):
        VLLMModel(bad_cfg).load()

    # Valid LoRA wires enable_lora=True and lora_request into fake vLLM
    captured: dict = {}

    class FakeLoRARequest:
        def __init__(self, lora_name: str, lora_int_id: int, lora_path: str):
            self.lora_name = lora_name
            self.lora_int_id = lora_int_id
            self.lora_path = lora_path

    class FakeLLM:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs

        def get_tokenizer(self):
            return SimpleNamespace(apply_chat_template=lambda *a, **k: "prompt")

        def generate(self, prompts, sampling_params=None, use_tqdm=False, **kwargs):
            captured["generate_kwargs"] = kwargs
            return [
                SimpleNamespace(
                    prompt_token_ids=[1, 2],
                    outputs=[SimpleNamespace(text="ok", token_ids=[3], finish_reason="stop")],
                )
                for _ in prompts
            ]

    class FakeSamplingParams:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_vllm = ModuleType("vllm")
    fake_vllm.LLM = FakeLLM
    fake_vllm.SamplingParams = FakeSamplingParams
    fake_lora_pkg = ModuleType("vllm.lora")
    fake_lora_req_mod = ModuleType("vllm.lora.request")
    fake_lora_req_mod.LoRARequest = FakeLoRARequest
    monkeypatch.setitem(sys.modules, "vllm", fake_vllm)
    monkeypatch.setitem(sys.modules, "vllm.lora", fake_lora_pkg)
    monkeypatch.setitem(sys.modules, "vllm.lora.request", fake_lora_req_mod)

    vm = VLLMModel(model_cfg, default_options=gen_opts)
    vm.load()
    assert captured["init_kwargs"]["enable_lora"] is True
    assert captured["init_kwargs"]["max_lora_rank"] == 16
    vm.chat([ChatMessage(role="user", content="hi")])
    assert captured["generate_kwargs"]["lora_request"].lora_path == str(lora_dir.resolve())


def test_v1_2_config_and_default_runner_defaults(tmp_path: Path, monkeypatch) -> None:
    """Task 6: both configs coexist; CLI, Modal, and predict.sh default to v1.2 + 1-round k=4 voting."""
    from datamate.planner import load_pipeline_config
    from scripts import run_pipeline as rp

    base_cfg, base_opts, base_voting = load_pipeline_config("configs/qwen3_5_9b.toml")
    assert base_cfg.model_path == Path("models/Qwen3.5-9B").resolve()
    assert base_cfg.prompt_format == "legacy"
    assert base_cfg.lora_path is None
    assert base_cfg.chat_template_kwargs.get("enable_thinking") is True
    assert base_opts.thinking_token_budget == 4096
    assert base_voting.enabled is True
    assert base_voting.rounds == 2
    assert base_voting.thinking_mode == "two_round"

    g_cfg, _, _ = load_pipeline_config("configs/qwen2_5_3b_grounding.toml")
    assert g_cfg.model_path == Path("models/Qwen2.5-3B-Instruct").resolve()
    neo_g_cfg, _, _ = load_pipeline_config("configs/qwen2_5_3b_neo_grounding.toml")
    assert neo_g_cfg.model_path == Path("models/Qwen2.5-3B-Instruct").resolve()

    ft_path = Path("configs/qwen3_5_9b_ft_v1_2.toml")
    assert ft_path.is_file()
    ft_cfg, ft_opts, ft_voting = load_pipeline_config(ft_path)
    assert ft_cfg.model_path == Path("models/Qwen3.5-9B").resolve()
    assert ft_cfg.prompt_format == "v1_2"
    assert ft_cfg.grounded_hint_mode == "compact_json"
    assert ft_cfg.lora_path == Path("models/adapters/qwen3_5_9b_v1_2").resolve()
    assert ft_cfg.chat_template_kwargs.get("enable_thinking") is False
    assert ft_opts.thinking_token_budget is None
    assert ft_opts.temperature == 0.5
    assert ft_opts.seed == 42
    assert ft_voting.enabled is True
    assert ft_voting.rounds == 1
    assert ft_voting.initial_candidates == 4
    assert ft_voting.threshold == 0.5
    assert ft_voting.temperature == 0.5
    assert ft_voting.thinking_mode == "always_off"

    monkeypatch.setattr("sys.argv", ["run_pipeline.py"])
    args = rp.parse_args()
    assert args.config == Path("configs/qwen3_5_9b_ft_v1_2.toml")
    assert args.voting is None
    assert args.voting_rounds is None
    assert args.voting_candidates is None
    assert args.voting_threshold is None
    assert args.voting_temperature is None
    assert args.voting_thinking_mode is None
    assert args.grounded_hint_mode is None
    assert args.enable_thinking is None

    # Verify Modal runner signature defaults delegate to TOML [voting] & mount models/adapters/qwen3_5_9b_v1_2
    import inspect
    from scripts import modal_run_pipeline as mrp

    modal_sig = inspect.signature(mrp.main.info.raw_f).parameters
    assert modal_sig["config"].default == "configs/qwen3_5_9b_ft_v1_2.toml"
    assert modal_sig["voting"].default is None
    assert modal_sig["voting_rounds"].default is None
    assert modal_sig["voting_candidates"].default is None
    assert modal_sig["voting_threshold"].default is None
    assert modal_sig["voting_temperature"].default is None
    assert modal_sig["voting_thinking_mode"].default is None
    assert modal_sig["grounded_hint_mode"].default is None
    assert modal_sig["enable_thinking"].default is None
    modal_src = Path("scripts/modal_run_pipeline.py").read_text(encoding="utf-8")
    assert "qwen3_5_9b_v1_2" in modal_src
    assert "adapter-final" not in modal_src

    # Verify CLI can override back to base config + --no-lora + explicit voting overrides cleanly
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_pipeline.py",
            "--config",
            "configs/qwen3_5_9b.toml",
            "--no-lora",
            "--voting-rounds",
            "2",
            "--voting-thinking-mode",
            "two_round",
        ],
    )
    base_args = rp.parse_args()
    assert base_args.config == Path("configs/qwen3_5_9b.toml")
    assert base_args.no_lora is True
    assert base_args.voting_rounds == 2
    assert base_args.voting_thinking_mode == "two_round"

    # Verify predict.sh and entrypoint.sh default to v1.2 config without hardcoding --voting-rounds unconditionally
    predict_sh = Path("predict.sh").read_text(encoding="utf-8")
    assert "qwen3_5_9b_ft_v1_2.toml" in predict_sh
    assert "qwen3_5_9b_v1_2" in predict_sh
    assert "--voting-rounds" in predict_sh
    entrypoint_sh = Path("entrypoint.sh").read_text(encoding="utf-8")
    assert "qwen3_5_9b_ft_v1_2.toml" in entrypoint_sh

    # End-to-end run_pipeline_cli with default voting & v1.2 config via mocked VLLMModel
    biz_dir = tmp_path / "split" / "b1"
    biz_dir.mkdir(parents=True)
    (biz_dir / "orders.csv").write_text("id,amount\n1,100\n", encoding="utf-8")
    (tmp_path / "split" / "questions.jsonl").write_text(
        '{"id":"q1","business_id":"b1","question":"Total?","as_of_date":"2025-08-01"}\n',
        encoding="utf-8",
    )

    seen_calls: list[tuple[list[ChatMessage], GenerationOptions | None]] = []

    class FakeRunnerLLM(BaseLLM):
        def __init__(self, cfg, default_options=None):
            self.config = cfg
            self.default_options = default_options

        def load(self) -> None:
            pass

        def generate(self, prompt: str, *, options=None):
            raise NotImplementedError

        def generate_batch(self, prompts, *, options=None):
            raise NotImplementedError

        def chat(self, messages, *, options=None) -> GenerationResult:
            seen_calls.append((messages, options))
            # Extract real hashed table name from v1.2 JSON user payload
            user_obj = json.loads(messages[1].content)
            tbl = next(t["table"] for t in user_obj["context"]["schema"] if t["table"].startswith("orders"))
            return GenerationResult(
                text=json.dumps(
                    {
                        "status": "answerable",
                        "structured_plan": {"grain": "order", "source_tables": [tbl]},
                        "sql": f"SELECT SUM(amount) FROM {tbl}",
                        "answer_type": "number",
                        "reason": None,
                    }
                ),
                input_tokens=100,
                output_tokens=25,
                finish_reason="stop",
                diagnostics=GenerationDiagnostics(
                    thinking_enabled=options.enable_thinking if options else None,
                    max_new_tokens=2048,
                ),
            )

        def chat_batch(self, messages_batch, *, options=None):
            return [self.chat(m, options=options) for m in messages_batch]

    from datamate.planner.types import GenerationDiagnostics

    loaded_cfgs: list = []

    class TrackRunnerLLM(FakeRunnerLLM):
        def __init__(self, cfg, default_options=None):
            super().__init__(cfg, default_options)
            loaded_cfgs.append(cfg)

    monkeypatch.setattr("scripts.run_pipeline.VLLMModel", TrackRunnerLLM)
    out_dir = tmp_path / "out"
    summary = rp.run_pipeline_cli(
        split_dir=tmp_path / "split",
        bundles_dir=tmp_path / "bundles",
        output_dir=out_dir,
        config_path=ft_path,
        enable_grounding=False,
        verbose=False,
    )
    assert summary["total_questions"] == 1
    assert loaded_cfgs[-1].lora_path == Path("models/adapters/qwen3_5_9b_v1_2").resolve()
    assert len(seen_calls) == 4  # 1 round, k=4 from TOML [voting]
    assert all(opts.enable_thinking is False and opts.temperature == 0.5 and opts.seed == 42 for _, opts in seen_calls)
    sub = json.loads((out_dir / "submission.jsonl").read_text(encoding="utf-8").strip())
    assert sub == {"id": "q1", "type": "number", "answer": 100}

    # Explicit CLI override --no-voting overrides TOML [voting]
    seen_calls.clear()
    rp.run_pipeline_cli(
        split_dir=tmp_path / "split",
        bundles_dir=tmp_path / "bundles",
        output_dir=tmp_path / "out_novote",
        config_path=ft_path,
        voting=False,
        enable_grounding=False,
        verbose=False,
    )
    assert len(seen_calls) == 1

    # Switching to base config reads base TOML [voting] (two_round, temp=0.7) & lora_path=None
    seen_calls.clear()

    class TrackBaseLLM(TrackRunnerLLM):
        def chat(self, messages, *, options=None) -> GenerationResult:
            seen_calls.append((messages, options))
            return GenerationResult(
                text=json.dumps({"status": "answerable", "answer_type": "number", "sql": "SELECT 42"}),
                input_tokens=40,
                output_tokens=15,
                finish_reason="stop",
            )

    monkeypatch.setattr("scripts.run_pipeline.VLLMModel", TrackBaseLLM)
    rp.run_pipeline_cli(
        split_dir=tmp_path / "split",
        bundles_dir=tmp_path / "bundles",
        output_dir=tmp_path / "out_base",
        config_path=Path("configs/qwen3_5_9b.toml"),
        enable_grounding=False,
        verbose=False,
    )
    assert loaded_cfgs[-1].lora_path is None
    assert loaded_cfgs[-1].prompt_format == "legacy"
    assert len(seen_calls) == 4
    assert all(opts.temperature == 0.7 and opts.enable_thinking is False for _, opts in seen_calls)


def test_parse_v1_2_outputs_including_structured_plan_and_needs_more_context() -> None:
    """Task 3: parser supports structured_plan, needs_more_context, and real SFT completion rows."""
    raw_answerable = json.dumps(
        {
            "status": "answerable",
            "structured_plan": {
                "metric": {"name": "revenue", "aggregation": "sum", "column": "orders.amount", "formula": None},
                "grain": "order",
                "source_tables": ["orders"],
                "joins": [],
                "filters": [],
                "time_range": None,
                "group_by": [],
                "order_by": [],
                "limit": None,
                "output_shape": "scalar",
                "rule_refs": ["r1"],
            },
            "sql": "SELECT SUM(amount) FROM orders",
            "answer_type": "number",
            "reason": None,
        },
        ensure_ascii=False,
    )
    res = parse_text2sql_response(raw_answerable, question="Total?")
    assert res.status == "answerable"
    assert res.answer_type == "number"
    assert res.tables_used == ("orders",)
    assert isinstance(res.structured_plan, dict)
    assert res.structured_plan["grain"] == "order"

    raw_needs = json.dumps(
        {
            "status": "needs_more_context",
            "structured_plan": None,
            "sql": None,
            "answer_type": None,
            "requested_context": ["relation: a.id -> b.id"],
            "reason": "Missing join key",
        },
        ensure_ascii=False,
    )
    res_needs = parse_text2sql_response(raw_needs)
    assert res_needs.status == "needs_more_context"
    assert res_needs.requested_context == ("relation: a.id -> b.id",)
    assert res_needs.reason == "Missing join key"

    # Verify parsing on first 20 actual SFT assistant completions from train_v1_2.jsonl
    train_path = Path("data/finetuning/train_v1_2.jsonl")
    if train_path.is_file():
        with train_path.open(encoding="utf-8") as handle:
            for idx, line in enumerate(handle):
                if idx >= 20:
                    break
                row = json.loads(line)
                q = json.loads(row["messages"][1]["content"])["question"]
                parsed = parse_text2sql_response(row["messages"][2]["content"], question=q)
                assert parsed.status in {"answerable", "unanswerable"}


def test_pipeline_handles_needs_more_context_with_retry_and_abstain(tmp_path: Path) -> None:
    """Task 3: needs_more_context retries once within budget, then abstains safely if unresolved."""
    biz_dir = tmp_path / "biz_nmc"
    biz_dir.mkdir()
    (biz_dir / "orders.csv").write_text("id,amount\n1,100\n", encoding="utf-8")
    art = prepare_business(biz_dir, tmp_path / "bundles")
    tbl = DataMatePipeline.load_context(art.bundle_dir)["schema_catalog"]["tables"][0]["name"]

    class NeedsContextThenAnswerLLM(BaseLLM):
        def __init__(self, always_needs: bool = False):
            self.always_needs = always_needs
            self.calls = 0

        def load(self) -> None:
            pass

        def generate(self, prompt: str, *, options=None):
            raise NotImplementedError

        def generate_batch(self, prompts, *, options=None):
            raise NotImplementedError

        def chat(self, messages, *, options=None) -> GenerationResult:
            self.calls += 1
            if self.always_needs or self.calls == 1:
                text = json.dumps(
                    {
                        "status": "needs_more_context",
                        "structured_plan": None,
                        "sql": None,
                        "answer_type": None,
                        "requested_context": ["rule: revenue"],
                        "reason": "Need rule",
                    }
                )
            else:
                text = json.dumps(
                    {
                        "status": "answerable",
                        "structured_plan": {"grain": "order"},
                        "sql": f"SELECT SUM(amount) FROM {tbl}",
                        "answer_type": "number",
                        "reason": None,
                    }
                )
            return GenerationResult(text=text, input_tokens=50, output_tokens=20, finish_reason="stop")

        def chat_batch(self, messages_batch, *, options=None):
            return [self.chat(m, options=options) for m in messages_batch]

    # 1. Recovers on retry
    p_ok = DataMatePipeline(Text2SQLGenerator(NeedsContextThenAnswerLLM(False)), enable_grounding=False)
    out_ok = p_ok.answer_question(
        {"id": "q1", "business_id": "biz_nmc", "question": "Total?", "as_of_date": "2025-08-01"},
        art.bundle_dir,
    )
    assert out_ok.decision == Decision.ANSWER
    assert out_ok.final_answer.answer == 100
    assert out_ok.retry_count == 1

    # 2. Exhausts retry -> ABSTAIN cleanly (no crash)
    p_abstain = DataMatePipeline(Text2SQLGenerator(NeedsContextThenAnswerLLM(True)), enable_grounding=False)
    out_ab = p_abstain.answer_question(
        {"id": "q2", "business_id": "biz_nmc", "question": "Total?", "as_of_date": "2025-08-01"},
        art.bundle_dir,
    )
    assert out_ab.decision == Decision.ABSTAIN


def test_generator_v1_2_and_voting_retry_object_propagation(tmp_path: Path) -> None:
    """Task 4: Text2SQLGenerator(prompt_format='v1_2') emits v1.2 prompts and carries retry metadata."""
    from datamate.planner.prompt_v1_2 import SYSTEM_PROMPT_V1_2
    from datamate.voting import VotingConfig

    biz_dir = tmp_path / "biz_g4"
    biz_dir.mkdir()
    (biz_dir / "orders.csv").write_text("id,amount\n1,100\n2,250\n", encoding="utf-8")
    art = prepare_business(biz_dir, tmp_path / "bundles")
    tbl = DataMatePipeline.load_context(art.bundle_dir)["schema_catalog"]["tables"][0]["name"]

    seen_messages: list[list[ChatMessage]] = []

    class CaptureV12LLM(BaseLLM):
        def __init__(self):
            self.default_options = GenerationOptions(max_new_tokens=2048, temperature=0.5, seed=42)

        def load(self) -> None:
            pass

        def generate(self, prompt: str, *, options=None):
            raise NotImplementedError

        def generate_batch(self, prompts, *, options=None):
            raise NotImplementedError

        def chat(self, messages, *, options=None) -> GenerationResult:
            seen_messages.append(messages)
            payload = json.loads(messages[1].content)
            if payload["retry"] is None:
                text = json.dumps(
                    {
                        "status": "answerable",
                        "structured_plan": {"grain": "order", "source_tables": [tbl]},
                        "sql": f"SELECT bad_col FROM {tbl}",
                        "answer_type": "number",
                        "reason": None,
                    }
                )
            else:
                text = json.dumps(
                    {
                        "status": "answerable",
                        "structured_plan": {"grain": "order", "source_tables": [tbl]},
                        "sql": f"SELECT SUM(amount) FROM {tbl}",
                        "answer_type": "number",
                        "reason": None,
                    }
                )
            return GenerationResult(text=text, input_tokens=100, output_tokens=30, finish_reason="stop")

        def chat_batch(self, messages_batch, *, options=None):
            return [self.chat(m, options=options) for m in messages_batch]

    gen = Text2SQLGenerator(CaptureV12LLM(), prompt_format="v1_2")
    pipe = DataMatePipeline(
        gen,
        enable_grounding=False,
        voting=VotingConfig(
            enabled=True,
            initial_candidates=4,
            threshold=0.5,
            temperature=0.5,
            rounds=1,
            thinking_mode="always_off",
        ),
    )
    outcomes = pipe.run_questions(
        [{"id": "q1", "business_id": "biz_g4", "question": "Total?", "as_of_date": "2025-08-01"}],
        {"biz_g4": art.bundle_dir},
        tmp_path / "out_g4",
        batch_size=1,
    )
    assert len(outcomes) == 1
    assert outcomes[0].decision == Decision.ANSWER
    assert outcomes[0].final_answer.answer == 350

    assert len(seen_messages) == 8  # 4 attempt-0 + 4 attempt-1 repairs
    assert all(msgs[0].content == SYSTEM_PROMPT_V1_2 for msgs in seen_messages)
    repair_payload = json.loads(seen_messages[-1][1].content)
    assert repair_payload["retry"]["previous_plan"] == {"grain": "order", "source_tables": [tbl]}
    assert repair_payload["retry"]["previous_sql"] == f"SELECT bad_col FROM {tbl}"
    assert repair_payload["retry"]["error_code"] == "SCHEMA_ERROR"


def test_load_pipeline_config_with_voting_and_grounded_hint_mode(tmp_path: Path) -> None:
    """Task 2 & 3: TOML supports [voting] section, grounded_hint_mode, and preserves load_config 2-tuple."""
    from datamate.planner import ModelConfig, load_config, load_pipeline_config
    from datamate.voting import VotingConfig

    with pytest.raises(ValueError, match="grounded_hint_mode"):
        ModelConfig(model_path=tmp_path, grounded_hint_mode="unknown_mode")  # type: ignore[arg-type]

    toml_with_voting = tmp_path / "with_voting.toml"
    toml_with_voting.write_text(
        '[model]\n'
        'model_path = "./w"\n'
        'prompt_format = "v1_2"\n'
        'grounded_hint_mode = "compact_json"\n'
        '[generation]\n'
        'temperature = 0.5\n'
        '[voting]\n'
        'enabled = true\n'
        'rounds = 1\n'
        'initial_candidates = 4\n'
        'threshold = 0.5\n'
        'temperature = 0.5\n'
        'top_p = 0.8\n'
        'top_k = 20\n'
        'thinking_mode = "always_off"\n',
        encoding="utf-8",
    )
    m_legacy, g_legacy = load_config(toml_with_voting)
    assert m_legacy.grounded_hint_mode == "compact_json"
    assert g_legacy.temperature == 0.5

    m_cfg, g_opts, v_cfg = load_pipeline_config(toml_with_voting)
    assert m_cfg.prompt_format == "v1_2"
    assert g_opts.temperature == 0.5
    assert v_cfg == VotingConfig(
        enabled=True,
        rounds=1,
        initial_candidates=4,
        threshold=0.5,
        temperature=0.5,
        top_p=0.8,
        top_k=20,
        thinking_mode="always_off",
    )

    toml_no_voting = tmp_path / "no_voting.toml"
    toml_no_voting.write_text('[model]\nmodel_path = "./w"\n', encoding="utf-8")
    fallback_voting = VotingConfig(enabled=True, rounds=1, temperature=0.5, thinking_mode="always_off")
    _, _, v_fallback = load_pipeline_config(toml_no_voting, default_voting=fallback_voting)
    assert v_fallback == fallback_voting

    toml_bad_voting = tmp_path / "bad_voting.toml"
    toml_bad_voting.write_text('[model]\nmodel_path = "./w"\n[voting]\nrounds = 99\n', encoding="utf-8")
    with pytest.raises(ValueError, match="rounds"):
        load_config(toml_bad_voting)


def test_v1_2_enriches_semantic_catalog_and_constraints_within_contract() -> None:
    """Task 4: semantic_catalog & constraints enrich context.relations and context.rules without changing top keys."""
    from datamate.planner.prompt_v1_2 import build_v1_2_user_payload

    context = {
        "schema_catalog": {
            "tables": [
                {
                    "name": "orders",
                    "grain": "order",
                    "row_count": 10,
                    "columns": [
                        {"name": "order_id", "data_type": "VARCHAR"},
                        {"name": "worker_name", "data_type": "VARCHAR"},
                        {"name": "amount", "data_type": "BIGINT"},
                    ],
                },
                {
                    "name": "workers",
                    "grain": "worker",
                    "row_count": 3,
                    "columns": [{"name": "full_name", "data_type": "VARCHAR"}],
                },
            ],
            "join_graph": [
                {
                    "left_table": "orders",
                    "left_column": "order_id",
                    "right_table": "orders",
                    "right_column": "order_id",
                    "cardinality": "one_to_one",
                    "status": "valid",
                }
            ],
        },
        "rule_catalog": {"rules": [{"rule_id": "R1", "text": "Doanh thu loại bỏ đơn hủy", "scope": "split_default", "precedence": 5}]},
        "semantic_catalog": {
            "metrics": [
                {
                    "metric_id": "commission",
                    "name": "Hoa hồng thợ",
                    "preferred_table": "orders",
                    "required_columns": ["amount", "worker_name"],
                    "formula_hint": "SUM(amount) * 0.1",
                    "unit": "VND",
                }
            ],
            "suggested_joins": [
                {
                    "left_table": "orders",
                    "left_column": "worker_name",
                    "right_table": "workers",
                    "right_column": "full_name",
                    "join_type": "name_suffix_match",
                    "description": "Khớp tên gọi tắt và họ tên đầy đủ",
                },
                {
                    "left_table": "orders",
                    "left_column": "order_id",
                    "right_table": "orders",
                    "right_column": "order_id",
                    "join_type": "exact",
                    "description": "Duplicate should not be added twice",
                },
            ],
            "unit_conversions": [
                {"item_name": "Bia", "from_unit": "thùng", "to_unit": "lon", "factor": 24}
            ],
            "unsupported_capabilities": ["đánh giá thái độ phục vụ"],
        },
        "answerability_constraints": {"no_customer_phone": "Không có cột số điện thoại khách hàng"},
    }

    payload = json.loads(
        build_v1_2_user_payload(
            context=context,
            question="Tính hoa hồng thợ",
            as_of_date="2025-08-01",
            industry="Sửa xe",
        )
    )
    assert list(payload.keys()) == ["question", "as_of_date", "context", "industry", "grounded_hint", "retry"]
    assert list(payload["context"].keys()) == ["schema", "relations", "rules", "date_context"]

    relations = payload["context"]["relations"]
    assert len(relations) == 2
    assert relations[1]["left"] == "orders.worker_name"
    assert relations[1]["right"] == "workers.full_name"
    assert relations[1]["status"] == "suggested"

    rules_by_id = {r["id"]: r["text"] for r in payload["context"]["rules"]}
    assert "R1" in rules_by_id
    assert "SEM_METRIC_commission" in rules_by_id
    assert "SUM(amount) * 0.1" in rules_by_id["SEM_METRIC_commission"]
    assert any(k.startswith("SEM_JOIN_SUFFIX_") for k in rules_by_id)
    assert "SEM_UNIT_CONVERSIONS" in rules_by_id
    assert "1 thùng = 24 lon" in rules_by_id["SEM_UNIT_CONVERSIONS"]
    assert "CONSTRAINT_UNSUPPORTED" in rules_by_id
    assert "CONSTRAINT_ANSWERABILITY" in rules_by_id


def test_v1_2_compact_json_grounded_hint_and_mode_switching(tmp_path: Path) -> None:
    """Task 5: GroundingToPlannerAdapter produces compact half-open JSON hint and honors grounded_hint_mode."""
    from datamate.grounding.adapters import GroundingToPlannerAdapter
    from datamate.grounding.contracts import (
        AnswerTypeHint,
        CandidateJoinPath,
        CoverageStatus,
        DateRole,
        GroundedQuestion,
        MatchedValue,
        OperationKind,
        QuestionIntent,
        ResolvedTimeRange,
        SchemaCandidate,
        SelectedSchema,
    )
    from datamate.planner.types import ModelConfig

    grounded = GroundedQuestion(
        question_id="q1",
        business_id="biz_h",
        question="Doanh thu thay nhớt hôm nay?",
        as_of_date="2025-08-01",
        intent=QuestionIntent(
            operation=OperationKind.SUM,
            target_metrics=("revenue",),
            answer_type_hint=AnswerTypeHint.NUMBER,
        ),
        resolved_time_ranges=(
            ResolvedTimeRange(
                raw_expression="hôm nay",
                start_date="2025-08-01",
                end_date="2025-08-01",
                date_role=DateRole.ORDER_DATE,
                inclusive=True,
            ),
        ),
        selected_schema=SelectedSchema(
            primary_table="orders",
            tables=(SchemaCandidate(table_name="orders", relevant_columns=("amount", "service")),),
            join_paths=(
                CandidateJoinPath(
                    left_table="orders",
                    left_column="id",
                    right_table="items",
                    right_column="order_id",
                    cardinality="one_to_many",
                    fanout_warning=True,
                ),
            ),
        ),
        matched_values=(
            MatchedValue(
                raw_text="thay nhớt",
                table_name="orders",
                column_name="service",
                matched_db_value="Thay nhớt xe máy",
            ),
        ),
        answer_type_hint=AnswerTypeHint.NUMBER,
        evidence_requirements=(),
        coverage_status=CoverageStatus.SUPPORTED,
    )

    compact_str = GroundingToPlannerAdapter.format_grounded_hint_for_v1_2(grounded)
    compact_obj = json.loads(compact_str)
    assert compact_obj["operation"] == "sum"
    assert compact_obj["primary_table"] == "orders"
    assert compact_obj["time_ranges"][0]["start_inclusive"] == "2025-08-01"
    assert compact_obj["time_ranges"][0]["end_exclusive"] == "2025-08-02"
    assert compact_obj["matched_values"][0]["value"] == "Thay nhớt xe máy"
    assert compact_obj["join_warnings"][0]["flags"] == ["fanout_1_n"]

    # Wire through DataMatePipeline with auto/compact_json vs off
    biz_dir = tmp_path / "biz_h"
    biz_dir.mkdir()
    (biz_dir / "orders.csv").write_text("ngay,service,amount\n2025-08-01,Thay nhớt xe máy,150\n", encoding="utf-8")
    cal = tmp_path / "calendar.csv"
    cal.write_text("date,weekday,lunar_day,lunar_month,lunar_year,lunar_leap,holiday\n2025-08-01,6,8,6,2025,false,\n", encoding="utf-8")
    art = prepare_business(biz_dir, tmp_path / "bundles", calendar=cal)

    seen_payloads: list[dict] = []

    class CaptureHintLLM(BaseLLM):
        def __init__(self, mode: str):
            self.config = ModelConfig(model_path=tmp_path, prompt_format="v1_2", grounded_hint_mode=mode)  # type: ignore[arg-type]
            self.default_options = GenerationOptions()

        def load(self) -> None:
            pass

        def generate(self, prompt: str, *, options=None):
            raise NotImplementedError

        def generate_batch(self, prompts, *, options=None):
            raise NotImplementedError

        def chat(self, messages, *, options=None) -> GenerationResult:
            payload = json.loads(messages[1].content)
            seen_payloads.append(payload)
            tbl = next(t["table"] for t in payload["context"]["schema"] if t["table"].startswith("orders"))
            return GenerationResult(
                text=json.dumps(
                    {
                        "status": "answerable",
                        "structured_plan": {"grain": "order", "source_tables": [tbl]},
                        "sql": f"SELECT SUM(amount) FROM {tbl}",
                        "answer_type": "number",
                        "reason": None,
                    }
                ),
                input_tokens=50,
                output_tokens=20,
                finish_reason="stop",
            )

        def chat_batch(self, messages_batch, *, options=None):
            return [self.chat(m, options=options) for m in messages_batch]

    class StubGroundingRuntime:
        def ground_question(self, **_kwargs):
            return grounded

    p_compact = DataMatePipeline(
        Text2SQLGenerator(CaptureHintLLM("auto")),
        enable_grounding=True,
        grounding_runtime=StubGroundingRuntime(),  # type: ignore[arg-type]
    )
    out1 = p_compact.run_questions(
        [{"id": "q1", "business_id": "biz_h", "question": "Doanh thu thay nhớt hôm nay?", "as_of_date": "2025-08-01"}],
        {"biz_h": art.bundle_dir},
        tmp_path / "out1",
        batch_size=2,
    )
    assert out1[0].decision == Decision.ANSWER
    assert isinstance(seen_payloads[-1]["grounded_hint"], dict)
    assert seen_payloads[-1]["grounded_hint"]["time_ranges"][0]["end_exclusive"] == "2025-08-02"

    p_off = DataMatePipeline(
        Text2SQLGenerator(CaptureHintLLM("off")),
        enable_grounding=True,
        grounding_runtime=StubGroundingRuntime(),  # type: ignore[arg-type]
    )
    out2 = p_off.run_questions(
        [{"id": "q2", "business_id": "biz_h", "question": "Doanh thu thay nhớt hôm nay?", "as_of_date": "2025-08-01"}],
        {"biz_h": art.bundle_dir},
        tmp_path / "out2",
        batch_size=1,
    )
    assert out2[0].decision == Decision.ANSWER
    assert seen_payloads[-1]["grounded_hint"] is None
