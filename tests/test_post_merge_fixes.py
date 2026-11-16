"""Regression tests for bugs identified in POST_MERGE_VOTING_FINETUNING_REVIEW.md."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import duckdb

from datamate.gate.contracts import Decision
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
from datamate.ingestion.ingestion import prepare_business
from datamate.ingestion.ingestion.readers import _family
from datamate.pipeline import DataMatePipeline
from datamate.planner import (
    BaseLLM,
    ChatMessage,
    GenerationOptions,
    GenerationResult,
    Text2SQLGenerator,
)
from datamate.voting import VotingConfig
from scripts.run_pipeline import OpenAICompatibleLLM


def test_prepare_business_with_unit_conversions_registers_table(tmp_path: Path) -> None:
    """C1: prepare_business must handle tuple schema_catalog['tables'] when unit_conversions exist."""
    biz_dir = tmp_path / "biz_units"
    biz_dir.mkdir(parents=True)
    (biz_dir / "orders.csv").write_text(
        "ma_don,san_pham,so_luong\nD1,Banh,2\n", encoding="utf-8"
    )
    (biz_dir / "README.md").write_text(
        "# Quy đổi đơn vị\n- Banh: 1 hop = 10 cai\n", encoding="utf-8"
    )

    artifacts = prepare_business(biz_dir, tmp_path / "bundles")
    ctx = json.loads((artifacts.bundle_dir / "business_context.json").read_text(encoding="utf-8"))

    table_names = [t["name"] for t in ctx["schema_catalog"]["tables"]]
    assert "unit_conversions" in table_names
    assert ctx["semantic_catalog"]["unit_conversions"]

    with duckdb.connect(str(artifacts.bundle_dir / "data.duckdb"), read_only=True) as con:
        rows = con.execute("SELECT item_name, from_unit, to_unit, factor FROM main.unit_conversions").fetchall()
    assert len(rows) == 2
    by_pair = {(r[1], r[2]): float(r[3]) for r in rows}
    assert by_pair[("hop", "cai")] == 10.0
    assert by_pair[("cai", "hop")] == 0.1


def test_main_py_has_no_debug_thinking_dump() -> None:
    """C3: main.py must not dump hardcoded LLM thinking traces to stdout."""
    proc = subprocess.run(
        [sys.executable, "main.py"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Thinking Process:" not in proc.stdout
    assert proc.stdout.strip() == "Hello from uit-last-dance-aizalo26!"


def test_openai_compatible_llm_forwards_sampling_without_thinking_override() -> None:
    """R2: OpenAICompatibleLLM.chat must pass sampling params even when enable_thinking is None."""
    recorded: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            recorded.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"status":"answerable"}'),
                        finish_reason="stop",
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            )

    llm = OpenAICompatibleLLM.__new__(OpenAICompatibleLLM)
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    llm.model_name = "Qwen/Qwen3.5-9B"
    llm.default_options = GenerationOptions(
        max_new_tokens=4096,
        temperature=0.0,
        top_p=0.95,
        top_k=40,
        presence_penalty=0.2,
        repetition_penalty=1.05,
        thinking_token_budget=None,
        enable_thinking=None,
    )
    llm.chat_template_kwargs = {"enable_thinking": True}

    llm.chat([ChatMessage(role="user", content="hello")], options=llm.default_options)
    assert len(recorded) == 1
    call = recorded[0]
    assert call.get("top_p") == 0.95 or call["extra_body"].get("top_p") == 0.95
    assert call["extra_body"]["top_k"] == 40
    assert call["extra_body"]["presence_penalty"] == 0.2
    assert call["extra_body"]["repetition_penalty"] == 1.05


def test_readers_family_distinguishes_month_sheets_from_other_year_sheets() -> None:
    """R3: _family must fold true monthly sheets to stem without matching Q1_2025/Part1_2025/Sheet2_2025."""
    # True monthly sheets -> collapsed to base stem
    for sheet in ("Tháng 01-2025", "Thang 12_2025", "T1_2025", "T01-2025", "01/2025", "2025-01", "BanHang_01_2025"):
        assert _family(Path("ban_hang.xlsx"), sheet, 0) == "ban_hang", f"Expected 'ban_hang' for {sheet!r}"

    # Non-monthly sheets containing a year -> keep sheet name
    for sheet in ("Q1_2025", "Part1_2025", "Test1_2025", "Sheet2_2025", "Doanh_thu_2025", "Chi_tiet_T1"):
        assert _family(Path("ban_hang.xlsx"), sheet, 0) == f"ban_hang_{sheet}", f"Expected 'ban_hang_{sheet}' for {sheet!r}"


def test_grounding_trace_written_for_batch_size_1_and_voting(tmp_path: Path) -> None:
    """Consider #1: run_questions(batch_size=1) must write grounding_trace.jsonl once per question."""
    biz_dir = tmp_path / "biz_gt"
    biz_dir.mkdir()
    (biz_dir / "orders.csv").write_text("id,amount\n1,100\n", encoding="utf-8")
    artifacts = prepare_business(biz_dir, tmp_path / "bundles")
    ctx = json.loads((artifacts.bundle_dir / "business_context.json").read_text(encoding="utf-8"))
    tbl = ctx["schema_catalog"]["tables"][0]["name"]

    class StubLLM(BaseLLM):
        def __init__(self):
            self.default_options = GenerationOptions(max_new_tokens=1024)

        def load(self) -> None:
            pass

        def generate(self, prompt: str, *, options=None) -> GenerationResult:
            raise NotImplementedError

        def generate_batch(self, prompts, *, options=None):
            raise NotImplementedError

        def chat(self, messages, *, options=None) -> GenerationResult:
            return GenerationResult(
                text=f'```json\n{{"status":"answerable","answer_type":"number","sql":"SELECT SUM(amount) FROM {tbl}"}}\n```',
                input_tokens=50,
                output_tokens=20,
                finish_reason="stop",
            )

        def chat_batch(self, messages_batch, *, options=None):
            return [self.chat(m, options=options) for m in messages_batch]

    class FakeGrounding:
        def ground(self, request: QuestionRequest, context) -> GroundedQuestion:
            if request.question_id == "q_ua":
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
                        missing_fields=("gia_von",),
                        checked_tables=(tbl,),
                        checked_all_sources=True,
                        reason="Missing cost column",
                    ),
                )
            return GroundedQuestion(
                question_id=request.question_id,
                business_id=request.business_id,
                question=request.question,
                as_of_date=request.as_of_date,
                intent=QuestionIntent(operation=OperationKind.SUM, normalized_question=request.question),
                resolved_time_ranges=(),
                selected_schema=SelectedSchema(tables=(), join_paths=(), primary_table=tbl),
                matched_values=(),
                answer_type_hint=AnswerTypeHint.NUMBER,
                evidence_requirements=(),
                coverage_status=CoverageStatus.SUPPORTED,
            )

    from datamate.grounding import QuestionGroundingRuntime

    questions = [
        {"id": "q_ok", "business_id": "biz_gt", "question": "Total?", "as_of_date": "2025-08-01"},
        {"id": "q_ua", "business_id": "biz_gt", "question": "Profit?", "as_of_date": "2025-08-01"},
    ]

    for voting_enabled in (False, True):
        out_dir = tmp_path / f"out_v_{voting_enabled}"
        pipeline = DataMatePipeline(
            Text2SQLGenerator(StubLLM()),
            enable_grounding=True,
            grounding_runtime=QuestionGroundingRuntime(engine=FakeGrounding()),
            voting=VotingConfig(enabled=voting_enabled, initial_candidates=4, threshold=0.5),
        )
        outcomes = pipeline.run_questions(
            questions, {"biz_gt": artifacts.bundle_dir}, out_dir, batch_size=1
        )
        assert [o.decision for o in outcomes] == [Decision.ANSWER, Decision.UNANSWERABLE]
        trace_path = out_dir / "grounding_trace.jsonl"
        assert trace_path.is_file()
        trace_lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert [row["question_id"] for row in trace_lines] == ["q_ok", "q_ua"]
