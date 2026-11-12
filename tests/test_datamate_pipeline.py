"""Integration tests for DataMatePipeline (Tasks 2 & 3)."""

from pathlib import Path
from typing import Any
import pytest

from datamate.gate.contracts import (
    AnswerType,
    Decision,
    ExecutionErrorDetail,
    GateAction,
    GateOutcome,
    QuestionMeta,
)
from datamate.grounding.contracts import (
    AnswerTypeHint,
    CoverageStatus,
    GroundedQuestion,
    MissingEvidenceProof,
    OperationKind,
    QuestionIntent,
    QuestionRequest,
    SelectedSchema,
)
from datamate.grounding.protocols import BusinessContextProtocol
from datamate.pipeline import B0Pipeline, DataMatePipeline, Pipeline
from datamate.planner.base import BaseLLM
from datamate.planner.generator import Text2SQLGenerator
from datamate.planner.types import ChatMessage, GenerationOptions, GenerationResult


class SpyLLM(BaseLLM):
    """Spy LLM recording calls."""

    def __init__(self, sql_to_return: str = "SELECT 42 AS ans") -> None:
        self.sql_to_return = sql_to_return
        self.generate_calls: list[list[ChatMessage]] = []
        self.repair_calls: list[list[ChatMessage]] = []

    def load(self) -> None:
        pass

    def generate(self, prompt: str, *, options: GenerationOptions | None = None) -> GenerationResult:
        return GenerationResult(text=self.sql_to_return, input_tokens=10, output_tokens=10, finish_reason="stop")

    def chat(self, messages: list[ChatMessage], *, options: GenerationOptions | None = None) -> GenerationResult:
        self.generate_calls.append(messages)
        json_output = (
            f'```json\n{{"status": "answerable", "answer_type": "number", "sql": "{self.sql_to_return}"}}\n```'
        )
        return GenerationResult(text=json_output, input_tokens=10, output_tokens=10, finish_reason="stop")

    def generate_batch(
        self, prompts: list[str], *, options: GenerationOptions | None = None
    ) -> list[GenerationResult]:
        return [self.generate(p, options=options) for p in prompts]

    def chat_batch(
        self, messages_batch: list[list[ChatMessage]], *, options: GenerationOptions | None = None
    ) -> list[GenerationResult]:
        return [self.chat(msgs, options=options) for msgs in messages_batch]


class FakeGroundingEngine:
    """Mock Grounding Engine for pipeline testing."""

    def __init__(self, mode: str = "supported") -> None:
        self.mode = mode
        self.call_count = 0

    def ground(self, request: QuestionRequest, context: BusinessContextProtocol) -> GroundedQuestion:
        self.call_count += 1
        if self.mode == "unsupported":
            return GroundedQuestion(
                question_id=request.question_id,
                business_id=request.business_id,
                question=request.question,
                as_of_date=request.as_of_date,
                intent=QuestionIntent(operation=OperationKind.LOOKUP, normalized_question=request.question),
                resolved_time_ranges=(),
                selected_schema=SelectedSchema(tables=(), join_paths=(), primary_table=None),
                matched_values=(),
                answer_type_hint=AnswerTypeHint.UNANSWERABLE,
                evidence_requirements=(),
                coverage_status=CoverageStatus.UNSUPPORTED,
                missing_evidence_proof=MissingEvidenceProof(
                    capability_key="cost",
                    missing_fields=("gia_von", "chi_phi"),
                    checked_tables=("orders",),
                    checked_all_sources=True,
                    reason="Dữ liệu không có thông tin chi phí và giá vốn",
                ),
            )
        return GroundedQuestion(
            question_id=request.question_id,
            business_id=request.business_id,
            question=request.question,
            as_of_date=request.as_of_date,
            intent=QuestionIntent(
                operation=OperationKind.SUM,
                target_metrics=("revenue",),
                normalized_question=request.question,
            ),
            resolved_time_ranges=(),
            selected_schema=SelectedSchema(tables=(), join_paths=(), primary_table="orders"),
            matched_values=(),
            answer_type_hint=AnswerTypeHint.NUMBER,
            evidence_requirements=(),
            coverage_status=CoverageStatus.SUPPORTED,
        )


def test_naming_and_subclass_compatibility() -> None:
    """DataMatePipeline is canonical; B0Pipeline and Pipeline are aliases."""
    assert issubclass(DataMatePipeline, object)
    assert B0Pipeline is DataMatePipeline
    assert Pipeline is DataMatePipeline


def test_grounding_fast_path_unanswerable(tmp_path: Path) -> None:
    """When question is directly unanswerable in Grounding, skip LLM and return unanswerable outcome."""
    spy_llm = SpyLLM()
    gen = Text2SQLGenerator(model=spy_llm)
    pipeline = DataMatePipeline(generator=gen, enable_grounding=True)

    fake_engine = FakeGroundingEngine(mode="unsupported")
    pipeline.grounding_runtime._engine = fake_engine  # inject mock engine

    # Mock bundle directory with business_context.json
    biz_dir = tmp_path / "bundle_test"
    biz_dir.mkdir()
    ctx_file = biz_dir / "business_context.json"
    ctx_file.write_text(
        '{"contract_version": "1.0", "business_id": "biz_001", "schema_catalog": {"tables": []}, "rule_catalog": {"rules": []}}',
        encoding="utf-8",
    )

    q = QuestionMeta(
        id="q_ua_1",
        business_id="biz_001",
        question="Chi phí giá vốn tháng này là bao nhiêu?",
        as_of_date="2026-08-27",
    )

    outcome = pipeline.answer_question(q, bundle_dir=biz_dir)

    assert outcome.decision == Decision.UNANSWERABLE
    assert outcome.final_answer is not None
    assert outcome.final_answer.type == AnswerType.UNANSWERABLE
    # LLM must NOT have been called!
    assert len(spy_llm.generate_calls) == 0
    assert fake_engine.call_count == 1


def test_grounding_hints_injected_when_supported(tmp_path: Path) -> None:
    """When question is supported, Grounding hints are injected into LLM prompt."""
    spy_llm = SpyLLM()
    gen = Text2SQLGenerator(model=spy_llm)
    pipeline = DataMatePipeline(generator=gen, enable_grounding=True)

    fake_engine = FakeGroundingEngine(mode="supported")
    pipeline.grounding_runtime._engine = fake_engine

    biz_dir = tmp_path / "bundle_test_supported"
    biz_dir.mkdir()
    ctx_file = biz_dir / "business_context.json"
    ctx_file.write_text(
        '{"contract_version": "1.0", "business_id": "biz_001", "schema_catalog": {"tables": []}, "rule_catalog": {"rules": []}}',
        encoding="utf-8",
    )

    q = QuestionMeta(
        id="q_sup_1",
        business_id="biz_001",
        question="Tổng doanh thu hôm nay là bao nhiêu?",
        as_of_date="2026-08-27",
    )

    outcome = pipeline.answer_question(q, bundle_dir=biz_dir)

    # LLM must have been called with grounding hints
    assert len(spy_llm.generate_calls) == 1
    call_content = spy_llm.generate_calls[0][1].content
    assert "GROUNDING HINTS" in call_content
    assert fake_engine.call_count == 1


def test_pipeline_enable_grounding_toggle(tmp_path: Path) -> None:
    """When enable_grounding=False, runs legacy path without calling grounding engine."""
    spy_llm = SpyLLM()
    gen = Text2SQLGenerator(model=spy_llm)
    pipeline = DataMatePipeline(generator=gen, enable_grounding=False)

    fake_engine = FakeGroundingEngine(mode="supported")
    pipeline.grounding_runtime._engine = fake_engine

    biz_dir = tmp_path / "bundle_test_legacy"
    biz_dir.mkdir()
    ctx_file = biz_dir / "business_context.json"
    ctx_file.write_text(
        '{"contract_version": "1.0", "business_id": "biz_001", "schema_catalog": {"tables": []}, "rule_catalog": {"rules": []}}',
        encoding="utf-8",
    )

    q = QuestionMeta(
        id="q_leg_1",
        business_id="biz_001",
        question="Doanh thu hôm nay?",
        as_of_date="2026-08-27",
    )

    outcome = pipeline.answer_question(q, bundle_dir=biz_dir)

    assert len(spy_llm.generate_calls) == 1
    call_content = spy_llm.generate_calls[0][1].content
    assert "GROUNDING HINTS" not in call_content
    assert fake_engine.call_count == 0


def test_batch_execution_with_grounding_and_telemetry(tmp_path: Path) -> None:
    """Batch execution handles mixed fast-path unanswerable and supported questions, writing grounding_trace."""
    spy_llm = SpyLLM()
    gen = Text2SQLGenerator(model=spy_llm)
    pipeline = DataMatePipeline(generator=gen, enable_grounding=True)

    class DynamicEngine:
        def ground(self, req: QuestionRequest, ctx: BusinessContextProtocol) -> GroundedQuestion:
            if "chi phí" in req.question.lower():
                return GroundedQuestion(
                    question_id=req.question_id,
                    business_id=req.business_id,
                    question=req.question,
                    as_of_date=req.as_of_date,
                    intent=QuestionIntent(operation=OperationKind.LOOKUP, normalized_question=req.question),
                    resolved_time_ranges=(),
                    selected_schema=SelectedSchema(tables=(), join_paths=(), primary_table=None),
                    matched_values=(),
                    answer_type_hint=AnswerTypeHint.UNANSWERABLE,
                    evidence_requirements=(),
                    coverage_status=CoverageStatus.UNSUPPORTED,
                    missing_evidence_proof=MissingEvidenceProof(
                        capability_key="cost",
                        missing_fields=("chi_phi",),
                        checked_tables=(),
                        checked_all_sources=True,
                        reason="Missing cost data",
                    ),
                )
            return GroundedQuestion(
                question_id=req.question_id,
                business_id=req.business_id,
                question=req.question,
                as_of_date=req.as_of_date,
                intent=QuestionIntent(
                    operation=OperationKind.SUM,
                    target_metrics=("revenue",),
                    normalized_question=req.question,
                ),
                resolved_time_ranges=(),
                selected_schema=SelectedSchema(tables=(), join_paths=(), primary_table="orders"),
                matched_values=(),
                answer_type_hint=AnswerTypeHint.NUMBER,
                evidence_requirements=(),
                coverage_status=CoverageStatus.SUPPORTED,
            )

    pipeline.grounding_runtime._engine = DynamicEngine()

    biz_dir = tmp_path / "bundle_batch"
    biz_dir.mkdir()
    ctx_file = biz_dir / "business_context.json"
    ctx_file.write_text(
        '{"contract_version": "1.0", "business_id": "biz_001", "schema_catalog": {"tables": []}, "rule_catalog": {"rules": []}}',
        encoding="utf-8",
    )

    questions = [
        QuestionMeta(id="q1", business_id="biz_001", question="Tổng doanh thu?", as_of_date="2026-08-27"),
        QuestionMeta(id="q2", business_id="biz_001", question="Chi phí?", as_of_date="2026-08-27"),
        QuestionMeta(id="q3", business_id="biz_001", question="Doanh thu hôm nay?", as_of_date="2026-08-27"),
    ]

    out_dir = tmp_path / "output_batch"
    outcomes = pipeline.run_questions(
        questions=questions,
        bundles={"biz_001": biz_dir},
        output_dir=out_dir,
        batch_size=2,
    )

    assert len(outcomes) == 3
    assert [o.question_id for o in outcomes] == ["q1", "q2", "q3"]
    assert outcomes[1].decision == Decision.UNANSWERABLE

    # Check that grounding_trace.jsonl was generated and has 3 records
    trace_file = out_dir / "grounding_trace.jsonl"
    assert trace_file.exists()
    import json
    traces = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(traces) == 3
    assert [t["question_id"] for t in traces] == ["q1", "q2", "q3"]
    assert traces[1]["is_directly_unanswerable"] is True


def test_run_pipeline_cli_with_grounding_llm(tmp_path: Path, monkeypatch) -> None:
    """Test run_pipeline_cli loads both Grounding 3B and Planner 9B when enable_grounding_llm=True."""
    from scripts.run_pipeline import run_pipeline_cli
    from datamate.grounding.llm_fallback import StructuredLLMParser

    # Mock Fake LLM for Generator (9B)
    spy_llm = SpyLLM()
    monkeypatch.setattr("scripts.run_pipeline.VLLMModel", lambda _cfg, default_options=None: spy_llm)

    # Mock create_qwen3b_vllm_parser for Grounding (3B)
    fake_3b_called = []
    fake_parser = StructuredLLMParser(
        chat_fn=lambda _s, _u: '{"operation":"sum","target_metrics":["revenue"],"entities":[],"filters":[],"group_by":[],"top_k":null,"sort_order":"desc","answer_type_hint":"number"}'
    )
    def mock_create_3b(cfg_path, model_path_override=None):
        fake_3b_called.append((cfg_path, model_path_override))
        return fake_parser

    monkeypatch.setattr("datamate.grounding.llm_fallback.create_qwen3b_vllm_parser", mock_create_3b)

    # Mock DataMatePipeline.prepare_bundle
    from unittest.mock import MagicMock
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "business_context.json").write_text(
        '{"contract_version": "1.0", "business_id": "b1", "schema_catalog": {"tables": []}, "rule_catalog": {"rules": []}}',
        encoding="utf-8",
    )
    prep_mock = MagicMock(bundle_dir=bundle_dir)
    monkeypatch.setattr("datamate.pipeline.DataMatePipeline.prepare_bundle", lambda **kwargs: prep_mock)

    # Create dummy split
    split_dir = tmp_path / "split"
    split_dir.mkdir()
    biz_dir = split_dir / "b1"
    biz_dir.mkdir()
    q_file = split_dir / "questions.jsonl"
    q_file.write_text('{"id": "q1", "business_id": "b1", "question": "Doanh thu?", "as_of_date": "2026-08-27"}\n', encoding="utf-8")

    out_dir = tmp_path / "cli_out"
    config_file = tmp_path / "qwen3_5_9b.toml"
    config_file.write_text("""
[model]
model_path = "mock_9b"
dtype = "bfloat16"
max_model_len = 32768
gpu_memory_utilization = 0.68
tensor_parallel_size = 1
max_num_seqs = 16
trust_remote_code = false

[generation]
max_new_tokens = 512
temperature = 0.0
top_p = 1.0
top_k = -1
repetition_penalty = 1.0
presence_penalty = 0.0
stop = []
""", encoding="utf-8")

    grounding_config_file = tmp_path / "qwen2_5_3b.toml"
    grounding_config_file.write_text("""
[model]
model_path = "mock_3b"
dtype = "bfloat16"
max_model_len = 4096
gpu_memory_utilization = 0.22
tensor_parallel_size = 1
max_num_seqs = 8
trust_remote_code = false

[generation]
max_new_tokens = 256
temperature = 0.0
top_p = 1.0
top_k = -1
repetition_penalty = 1.0
presence_penalty = 0.0
stop = []
""", encoding="utf-8")

    summary = run_pipeline_cli(
        split_dir=split_dir,
        bundles_dir=tmp_path / "bundles",
        output_dir=out_dir,
        config_path=config_file,
        grounding_config_path=grounding_config_file,
        enable_grounding=True,
        enable_grounding_llm=True,
        verbose=False,
    )

    assert summary["total_questions"] == 1
    assert len(fake_3b_called) == 1
    assert (out_dir / "submission.jsonl").exists()

