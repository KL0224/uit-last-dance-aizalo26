"""Unit and integration tests for two-round execution-result voting."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from datamate.gate import evaluate_gate
from datamate.gate.adapters import adapt_gate_request
from datamate.gate.contracts import (
    AnswerType,
    Decision,
    ExecutionResult,
    FinalAnswer,
    GateAction,
    GateOutcome,
    GateRequest,
    QuestionMeta,
)
from datamate.gate.errors import ContractError, ErrorCode
from datamate.grounding import QuestionGroundingRuntime
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
from datamate.pipeline import DataMatePipeline
from datamate.planner import (
    BaseLLM,
    ChatMessage,
    GenerationDiagnostics,
    GenerationOptions,
    GenerationResult,
    ModelConfig,
    Text2SQLGenerator,
    VLLMModel,
)
from datamate.voting import VotingConfig, vote


def _make_answer_outcome(qid: str, answer_type: str, value) -> GateOutcome:
    return GateOutcome(
        action=GateAction.FINAL,
        question_id=qid,
        decision=Decision.ANSWER,
        final_answer=FinalAnswer(id=qid, type=answer_type, answer=value),
        reason_code=ErrorCode.VALID_RESULT,
    )


def _make_unanswerable_outcome(qid: str, reason: str = "missing") -> GateOutcome:
    return GateOutcome(
        action=GateAction.FINAL,
        question_id=qid,
        decision=Decision.UNANSWERABLE,
        final_answer=FinalAnswer(id=qid, type=AnswerType.UNANSWERABLE, reason=reason),
        reason_code=ErrorCode.CONFIRMED_MISSING_EVIDENCE,
    )


def _make_abstain_outcome(qid: str) -> GateOutcome:
    return GateOutcome(
        action=GateAction.FINAL,
        question_id=qid,
        decision=Decision.ABSTAIN,
        final_answer=FinalAnswer(id=qid, type=AnswerType.ABSTAIN),
        reason_code=ErrorCode.RETRY_EXHAUSTED,
    )


def test_voting_config_defaults_and_validation() -> None:
    """VotingConfig validates candidates, threshold, temperature and defaults to temperature=0.7."""
    cfg = VotingConfig()
    assert cfg.enabled is False
    assert cfg.initial_candidates == 4
    assert cfg.threshold == 0.5
    assert cfg.temperature == 0.7

    with pytest.raises(ValueError, match="initial_candidates"):
        VotingConfig(initial_candidates=6)
    with pytest.raises(ValueError, match="threshold"):
        VotingConfig(threshold=1.0)
    with pytest.raises(ValueError, match="threshold"):
        VotingConfig(threshold=-0.1)
    with pytest.raises(ValueError, match="temperature"):
        VotingConfig(temperature=0.0)

    base = GenerationOptions(max_new_tokens=8192, thinking_token_budget=4096, seed=10)
    r1 = cfg.options(base, 1)
    r2 = cfg.options(base, 2)
    assert r1.enable_thinking is False
    assert r1.thinking_token_budget is None
    assert r1.seed == 10
    assert r2.enable_thinking is True
    assert r2.thinking_token_budget == 4096
    assert r2.seed == 100010


def test_vote_inclusive_threshold_tie_abstain_denominator_and_canonical() -> None:
    """vote() handles inclusive >= threshold via Decimal, tie-breaks, abstains, and canonical values."""
    # 1. Exact threshold boundary (2/4 == 0.5) with unique leader -> wins lowest candidate_id
    cands = [
        {"candidate_id": 3, "outcome": _make_answer_outcome("q1", "number", 1.0)},
        {"candidate_id": 1, "outcome": _make_answer_outcome("q1", "number", 1)},
        {"candidate_id": 0, "outcome": _make_answer_outcome("q1", "number", 2)},
        {"candidate_id": 2, "outcome": _make_abstain_outcome("q1")},
    ]
    winner, summary = vote(cands, threshold=0.5)
    assert winner is not None
    assert summary["winner_candidate_id"] == 1
    assert summary["total_candidates"] == 4

    # 2. Tie at top (2 vs 2) -> no winner
    tie_cands = [
        {"candidate_id": 0, "outcome": _make_answer_outcome("q1", "number", 10)},
        {"candidate_id": 1, "outcome": _make_answer_outcome("q1", "number", 20)},
        {"candidate_id": 2, "outcome": _make_answer_outcome("q1", "number", 10)},
        {"candidate_id": 3, "outcome": _make_answer_outcome("q1", "number", 20)},
    ]
    winner_tie, summary_tie = vote(tie_cands, threshold=0.5)
    assert winner_tie is None
    assert summary_tie["winner_candidate_id"] is None

    # 3. Boolean vs number are not merged; list order matters
    mixed = [
        {"candidate_id": 0, "outcome": _make_answer_outcome("q1", "boolean", True)},
        {"candidate_id": 1, "outcome": _make_answer_outcome("q1", "number", 1)},
    ]
    _, summary_mixed = vote(mixed, threshold=0.5)
    assert len(summary_mixed["groups"]) == 2

    lists = [
        {"candidate_id": 0, "outcome": _make_answer_outcome("q1", "list", ["A", "B"])},
        {"candidate_id": 1, "outcome": _make_answer_outcome("q1", "list", ["B", "A"])},
    ]
    _, summary_lists = vote(lists, threshold=0.5)
    assert len(summary_lists["groups"]) == 2

    # 4. Unanswerable candidates share one group regardless of reason
    ua_cands = [
        {"candidate_id": 0, "outcome": _make_unanswerable_outcome("q1", "reason a")},
        {"candidate_id": 1, "outcome": _make_unanswerable_outcome("q1", "reason b")},
        {"candidate_id": 2, "outcome": _make_answer_outcome("q1", "number", 5)},
        {"candidate_id": 3, "outcome": _make_abstain_outcome("q1")},
    ]
    ua_winner, ua_summary = vote(ua_cands, threshold=0.5)
    assert ua_winner is not None
    assert ua_winner.decision == Decision.UNANSWERABLE
    assert ua_summary["winner_candidate_id"] == 0


def test_gate_supports_max_retries_2_for_v1_and_v2() -> None:
    """GateRequest.max_retries=2 permits attempt=0->1->2 repairs and rejects invalid bounds."""
    raw = {
        "contract_version": "b05.v1",
        "question": {"id": "q1", "business_id": "b1", "question": "Total?", "as_of_date": "2025-08-01"},
        "generation": {"answer_type": "number", "sql": "SELECT bad FROM t"},
        "execution": {"status": "error", "error": {"type": "BinderError", "message": "Column bad not found"}},
        "attempt": 1,
        "max_retries": 2,
    }
    req = adapt_gate_request(raw)
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.RETRY
    assert outcome.repair_request is not None
    assert outcome.repair_request.attempt == 2

    req_final = adapt_gate_request({**raw, "attempt": 2})
    outcome_final = evaluate_gate(req_final)
    assert outcome_final.action == GateAction.FINAL
    assert outcome_final.decision == Decision.ABSTAIN
    assert outcome_final.reason_code == ErrorCode.RETRY_EXHAUSTED

    with pytest.raises(ContractError):
        adapt_gate_request({**raw, "attempt": 3, "max_retries": 2})


def test_vllm_model_per_request_enable_thinking_and_token_count() -> None:
    """VLLMModel overrides enable_thinking per request without mutating ModelConfig."""
    seen_template_kwargs: list[dict] = []
    seen_seeds: list[int | None] = []

    class FakeTokenizer:
        def apply_chat_template(self, payload, **kwargs):
            seen_template_kwargs.append(dict(kwargs))
            if kwargs.get("tokenize"):
                return [1, 2, 3] if kwargs.get("enable_thinking") else [1, 2]
            return f"thinking={kwargs.get('enable_thinking')}"

    class FakeSamplingParams:
        def __init__(self, **kwargs):
            seen_seeds.append(kwargs.get("seed"))
            self.kwargs = kwargs

    class FakeEngine:
        def get_tokenizer(self):
            return FakeTokenizer()

        def generate(self, prompts, sampling_params=None, use_tqdm=False):
            return [
                SimpleNamespace(
                    prompt_token_ids=[1, 2],
                    outputs=[SimpleNamespace(text='{"status":"answerable","answer_type":"number","sql":"SELECT 1"}', token_ids=[3], finish_reason="stop")],
                )
                for _ in prompts
            ]

    cfg = ModelConfig(model_path=Path("/tmp/fake"), chat_template_kwargs={"enable_thinking": True})
    default_opts = GenerationOptions(max_new_tokens=8192, thinking_token_budget=4096, seed=100)
    vm = VLLMModel(cfg, default_options=default_opts)
    vm._engine = FakeEngine()
    vm._sampling_params_class = FakeSamplingParams
    vm._reasoning_configured = True

    vc = VotingConfig(enabled=True)
    r1_opts = vc.options(default_opts, 1)
    r2_opts = vc.options(default_opts, 2)

    msgs = [ChatMessage(role="user", content="hi")]
    assert vm.count_chat_tokens(msgs, options=r1_opts) == 2
    assert vm.count_chat_tokens(msgs, options=r2_opts) == 3

    res_batch = vm.chat_batch([msgs, msgs], options=r1_opts)
    assert len(res_batch) == 2
    assert res_batch[0].diagnostics.thinking_enabled is False
    assert seen_seeds == [None, 100, 101] or seen_seeds[-2:] == [100, 101]
    assert cfg.chat_template_kwargs["enable_thinking"] is True

    gen = Text2SQLGenerator(vm)
    parsed = gen.generate(context={}, question="hi", as_of_date="2025-08-01", options=r2_opts)
    assert parsed.diagnostics.thinking_enabled is True
    assert parsed.diagnostics.thinking_token_budget == 4096


def test_voting_pipeline_single_batch_parity_repair2_and_fallback(tmp_path: Path) -> None:
    """Integration: voting handles 2 repairs, round-2 tie->abstain, fallback, and single/batch parity."""
    biz_dir = tmp_path / "biz_v"
    biz_dir.mkdir()
    (biz_dir / "orders.csv").write_text("id,amount\n1,100\n2,200\n", encoding="utf-8")
    artifacts = prepare_business(biz_dir, tmp_path / "bundles")
    ctx = json.loads((artifacts.bundle_dir / "business_context.json").read_text(encoding="utf-8"))
    tbl = ctx["schema_catalog"]["tables"][0]["name"]

    class ScriptedLLM(BaseLLM):
        def __init__(self, mode: str):
            self.mode = mode
            self.default_options = GenerationOptions(max_new_tokens=8192, thinking_token_budget=4096)

        def load(self) -> None:
            pass

        def generate(self, prompt: str, *, options=None) -> GenerationResult:
            raise NotImplementedError

        def generate_batch(self, prompts, *, options=None):
            raise NotImplementedError

        def chat(self, messages, *, options=None) -> GenerationResult:
            user_msg = messages[-1].content
            if self.mode == "repair2":
                if "attempt2_marker" in user_msg:
                    sql = f"SELECT SUM(amount) FROM {tbl}"
                elif "attempt1_marker" in user_msg:
                    sql = f"SELECT attempt2_marker FROM {tbl}"
                else:
                    sql = f"SELECT attempt1_marker FROM {tbl}"
                return GenerationResult(
                    text=f'```json\n{{"status":"answerable","answer_type":"number","sql":"{sql}"}}\n```',
                    input_tokens=100,
                    output_tokens=20,
                    finish_reason="stop",
                    diagnostics=GenerationDiagnostics(
                        thinking_enabled=options.enable_thinking if options else None,
                        thinking_token_budget=options.thinking_token_budget if options else None,
                        max_new_tokens=8192,
                    ),
                )
            if self.mode == "fallback_parse":
                return GenerationResult(
                    text=f'```json\n{{"status":"answerable","answer_type":"number","sql":"SELECT SUM(amount) FROM {tbl}"}}\n```',
                    input_tokens=80,
                    output_tokens=15,
                    finish_reason="stop",
                    diagnostics=GenerationDiagnostics(
                        thinking_enabled=options.enable_thinking if options else None,
                        max_new_tokens=8192,
                    ),
                )
            raise AssertionError(f"Unexpected mode {self.mode}")

        def chat_batch(self, messages_batch, *, options=None):
            if self.mode == "fallback_parse":
                raise RuntimeError("Simulated batch crash")
            if self.mode == "tie":
                out = []
                for idx, _ in enumerate(messages_batch):
                    val = 100 if idx % 2 == 0 else 200
                    out.append(
                        GenerationResult(
                            text=f'```json\n{{"status":"answerable","answer_type":"number","sql":"SELECT {val}"}}\n```',
                            input_tokens=50,
                            output_tokens=10,
                            finish_reason="stop",
                            diagnostics=GenerationDiagnostics(
                                thinking_enabled=options.enable_thinking if options else None,
                                thinking_token_budget=options.thinking_token_budget if options else None,
                                max_new_tokens=8192,
                            ),
                        )
                    )
                return out
            return [self.chat(m, options=options) for m in messages_batch]

    q1 = {"id": "q1", "business_id": "biz_v", "question": "Total?", "as_of_date": "2025-08-01"}

    # 1. Single vs Batch parity with repair up to attempt=2
    for bsize in (1, 2):
        pipe = DataMatePipeline(
            Text2SQLGenerator(ScriptedLLM("repair2")),
            enable_grounding=False,
            voting=VotingConfig(enabled=True, initial_candidates=4, threshold=0.5),
            options=GenerationOptions(max_new_tokens=8192, thinking_token_budget=4096),
        )
        out = pipe.run_questions([q1], {"biz_v": artifacts.bundle_dir}, tmp_path / f"r2_{bsize}", batch_size=bsize)
        assert len(out) == 1
        assert out[0].decision == Decision.ANSWER
        assert out[0].final_answer.answer == 300
        assert out[0].retry_count == 2
        log_files = list((tmp_path / f"r2_{bsize}" / "logs").glob("*.json"))
        log_payload = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert log_payload["voting"]["total_repairs"] == 8
        assert log_payload["code"] == f"SELECT SUM(amount) FROM {tbl}"

    # 2. Tie across round 1 and round 2 -> ABSTAIN VOTING_THRESHOLD_NOT_MET
    pipe_tie = DataMatePipeline(
        Text2SQLGenerator(ScriptedLLM("tie")),
        enable_grounding=False,
        voting=VotingConfig(enabled=True, initial_candidates=4, threshold=0.5),
        options=GenerationOptions(max_new_tokens=8192, thinking_token_budget=4096),
    )
    out_tie = pipe_tie.run_questions([q1], {"biz_v": artifacts.bundle_dir}, tmp_path / "tie", batch_size=2)
    assert out_tie[0].decision == Decision.ABSTAIN
    assert out_tie[0].reason_code == "VOTING_THRESHOLD_NOT_MET"
    assert len(out_tie[0].voting["rounds"]) == 2
    assert out_tie[0].voting["rounds"][0]["thinking_enabled"] is False
    assert out_tie[0].voting["rounds"][1]["thinking_enabled"] is True

    # 3. Batch failure falls back cleanly and marks tokens_complete=False
    pipe_fb = DataMatePipeline(
        Text2SQLGenerator(ScriptedLLM("fallback_parse")),
        enable_grounding=False,
        voting=VotingConfig(enabled=True, initial_candidates=4, threshold=0.5),
        options=GenerationOptions(max_new_tokens=8192, thinking_token_budget=4096),
    )
    out_fb = pipe_fb.run_questions([q1], {"biz_v": artifacts.bundle_dir}, tmp_path / "fb", batch_size=2)
    assert out_fb[0].decision == Decision.ANSWER
    assert out_fb[0].final_answer.answer == 300
    assert out_fb[0].voting["tokens_complete"] is False


def test_voting_one_round_always_off_mode(tmp_path: Path) -> None:
    """Task 1: rounds=1 with thinking_mode='always_off' stops after round 1 on tie without thinking."""
    cfg = VotingConfig(
        enabled=True,
        initial_candidates=4,
        threshold=0.5,
        temperature=0.5,
        rounds=1,
        thinking_mode="always_off",
    )
    assert cfg.rounds == 1
    assert cfg.thinking_mode == "always_off"

    with pytest.raises(ValueError, match="rounds"):
        VotingConfig(rounds=3)
    with pytest.raises(ValueError, match="rounds"):
        VotingConfig(rounds=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="thinking_mode"):
        VotingConfig(thinking_mode="invalid")  # type: ignore[arg-type]

    base = GenerationOptions(max_new_tokens=2048, thinking_token_budget=1024, seed=42)
    r1_opts = cfg.options(base, 1)
    assert r1_opts.enable_thinking is False
    assert r1_opts.thinking_token_budget is None
    assert r1_opts.temperature == 0.5
    assert r1_opts.seed == 42

    cfg_inherit = VotingConfig(thinking_mode="inherit")
    assert cfg_inherit.options(GenerationOptions(enable_thinking=None, thinking_token_budget=512), 1).enable_thinking is None
    cfg_on = VotingConfig(thinking_mode="always_on")
    assert cfg_on.options(base, 1).enable_thinking is True
    assert cfg_on.options(base, 1).thinking_token_budget == 1024

    biz_dir = tmp_path / "biz_1r"
    biz_dir.mkdir()
    (biz_dir / "orders.csv").write_text("id,amount\n1,100\n", encoding="utf-8")
    artifacts = prepare_business(biz_dir, tmp_path / "bundles")

    observed_options: list[GenerationOptions | None] = []

    class Tie1RoundLLM(BaseLLM):
        def __init__(self):
            self.default_options = base

        def load(self) -> None:
            pass

        def generate(self, prompt: str, *, options=None):
            raise NotImplementedError

        def generate_batch(self, prompts, *, options=None):
            raise NotImplementedError

        def chat(self, messages, *, options=None):
            raise NotImplementedError

        def chat_batch(self, messages_batch, *, options=None):
            observed_options.append(options)
            return [
                GenerationResult(
                    text=f'```json\n{{"status":"answerable","answer_type":"number","sql":"SELECT {100 if i % 2 == 0 else 200}"}}\n```',
                    input_tokens=40,
                    output_tokens=15,
                    finish_reason="stop",
                    diagnostics=GenerationDiagnostics(
                        thinking_enabled=options.enable_thinking if options else None,
                        max_new_tokens=2048,
                    ),
                )
                for i in range(len(messages_batch))
            ]

    q1 = {"id": "q1", "business_id": "biz_1r", "question": "Total?", "as_of_date": "2025-08-01"}
    pipe = DataMatePipeline(
        Text2SQLGenerator(Tie1RoundLLM()),
        enable_grounding=False,
        voting=cfg,
        options=base,
    )
    outcomes = pipe.run_questions([q1], {"biz_1r": artifacts.bundle_dir}, tmp_path / "out_1r", batch_size=1)
    assert len(outcomes) == 1
    assert outcomes[0].decision == Decision.ABSTAIN
    assert outcomes[0].reason_code == "VOTING_THRESHOLD_NOT_MET"
    assert len(observed_options) == 1
    assert observed_options[0].enable_thinking is False
    assert len(outcomes[0].voting["rounds"]) == 1
    assert outcomes[0].voting["rounds"][0]["total_candidates"] == 4
    assert outcomes[0].voting["rounds"][0]["next_action"] == "abstain"
    assert isinstance(outcomes[0].voting["rounds"][0]["elapsed_ms"], float)
    assert outcomes[0].voting["rounds"][0]["elapsed_ms"] >= 0
    assert len(outcomes[0].voting["candidates"]) == 4
