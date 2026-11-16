"""Tests for Neo Grounding v3 integration, v1.2 compact hint adapter, and 2-phase execution."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
import subprocess
import sys

import duckdb
import pytest

from datamate.grounding import (
    CachedGroundingRuntime,
    GroundingContextIndex,
    GroundingToPlannerAdapter,
    NeoGroundingEngine,
    QuestionRequest,
    load_grounding_cache,
    save_grounding_cache,
    serialize_grounded_question,
)
from datamate.ingestion.ingestion import prepare_business
from datamate.pipeline import DataMatePipeline
from datamate.planner import (
    BaseLLM,
    GenerationOptions,
    GenerationResult,
    Text2SQLGenerator,
    load_pipeline_config,
)
from datamate.planner.prompt_v1_2 import build_v1_2_user_payload
from datamate.voting import VotingConfig


def _write_minimal_split(tmp_path: Path, *, with_calendar_and_rules: bool = True) -> tuple[Path, Path]:
    split_dir = tmp_path / "split"
    biz_dir = split_dir / "b1"
    biz_dir.mkdir(parents=True)
    (biz_dir / "orders.csv").write_text(
        "order_id,order_date,amount,status\n1,2026-02-01,100,completed\n2,2026-02-15,250,completed\n",
        encoding="utf-8",
    )
    (biz_dir / "README.md").write_text(
        "# Quy đổi đơn vị\n- Nước: 1 thùng = 24 chai\n",
        encoding="utf-8",
    )
    (split_dir / "questions.jsonl").write_text(
        json.dumps(
            {
                "id": "q1",
                "business_id": "b1",
                "question": "Doanh thu tháng này là bao nhiêu?",
                "as_of_date": "2026-02-20",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (split_dir / "answers.jsonl").write_text(
        json.dumps({"id": "q1", "type": "number", "answer": 350}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if with_calendar_and_rules:
        (split_dir / "rulebook.md").write_text(
            "## Thời gian\n- Tuần bắt đầu từ thứ Hai.\n## Doanh thu\n- Chỉ tính đơn completed.\n",
            encoding="utf-8",
        )
        cal_lines = ["date,weekday,lunar_day,lunar_month,lunar_year,lunar_leap,holiday"]
        for day in range(1, 29):
            d_str = f"2026-02-{day:02d}"
            cal_lines.append(f"{d_str},{(day % 7) + 1},{day},1,2026,false,")
        (split_dir / "calendar.csv").write_text("\n".join(cal_lines) + "\n", encoding="utf-8")
    bundles_dir = tmp_path / "bundles"
    return split_dir, bundles_dir


def _minimal_proposal_json(*, unresolved: list[str] | None = None) -> str:
    return json.dumps(
        {
            "metric_mentions": [{"id": "m1", "text": "Doanh thu"}],
            "entity_mentions": [],
            "condition_mentions": [],
            "temporal_intent": "single_period",
            "time": [
                {
                    "id": "t1",
                    "raw_expression": "tháng này",
                    "calendar": "gregorian",
                    "kind": "month",
                    "relative": "this",
                    "period_extent": "to_as_of",
                    "comparison": "none",
                    "role": "primary",
                    "applies_to": ["m1"],
                }
            ],
            "unresolved": unresolved or [],
        },
        ensure_ascii=False,
    )


def test_format_grounded_hint_for_v1_2_handles_neo_v3(tmp_path: Path) -> None:
    split_dir, bundles_dir = _write_minimal_split(tmp_path)
    art = prepare_business(
        split_dir / "b1",
        bundles_dir / "b1",
        rulebook=split_dir / "rulebook.md",
        calendar=split_dir / "calendar.csv",
    )
    idx = GroundingContextIndex(
        art.bundle_dir,
        rulebook=split_dir / "rulebook.md",
        calendar=split_dir / "calendar.csv",
    )
    engine = NeoGroundingEngine(
        lambda _s, _u: _minimal_proposal_json(unresolved=["Thiếu chi tiết phụ"]),
        {"b1": idx},
        token_count_fn=lambda s, u: len((s + u).split()),
    )
    rt = DataMatePipeline.load_runtime_context(art.bundle_dir, expected_business_id="b1")
    grounded = engine.ground(
        QuestionRequest(
            question_id="q1",
            business_id="b1",
            question="Doanh thu tháng này là bao nhiêu?",
            as_of_date="2026-02-20",
        ),
        rt.grounding_context,
    )

    compact_str = GroundingToPlannerAdapter.format_grounded_hint_for_v1_2(grounded)
    compact_obj = json.loads(compact_str)

    assert compact_obj["contract_version"] == "3.0"
    assert compact_obj["temporal_intent"] == "single_period"
    assert compact_obj["metric_mentions"][0]["text"] == "Doanh thu"
    assert compact_obj["resolved_windows"][0]["start_inclusive"] == "2026-02-01"
    assert compact_obj["resolved_windows"][0]["end_exclusive"] == "2026-02-21"
    assert "calendar_sha256" not in compact_obj["resolved_windows"][0]
    # Negative 3B diagnostics must NOT leak into Planner v1.2 prompt
    assert "validation_status" not in compact_obj
    assert "temporal_completeness" not in compact_obj
    assert "unresolved" not in compact_obj
    assert "warnings" not in compact_obj

    user_json = json.loads(
        build_v1_2_user_payload(
            context=rt.planner_context,
            question="Doanh thu tháng này là bao nhiêu?",
            as_of_date="2026-02-20",
            grounded_hint=compact_str,
        )
    )
    assert user_json["grounded_hint"]["contract_version"] == "3.0"
    assert user_json["grounded_hint"]["resolved_windows"][0]["end_exclusive"] == "2026-02-21"


def test_format_grounded_hint_for_v1_2_drops_unresolved_errors_and_empty_hints(tmp_path: Path) -> None:
    split_dir, bundles_dir = _write_minimal_split(tmp_path)
    art = prepare_business(
        split_dir / "b1",
        bundles_dir / "b1",
        rulebook=split_dir / "rulebook.md",
        calendar=split_dir / "calendar.csv",
    )
    idx = GroundingContextIndex(
        art.bundle_dir,
        rulebook=split_dir / "rulebook.md",
        calendar=split_dir / "calendar.csv",
    )
    bad_proposal = json.dumps(
        {
            "metric_mentions": [],
            "entity_mentions": [],
            "condition_mentions": [],
            "temporal_intent": "single_period",
            "time": [],
            "unresolved": ["MISSING_TEMPORAL_WINDOW"],
        },
        ensure_ascii=False,
    )
    engine = NeoGroundingEngine(
        lambda _s, _u: bad_proposal,
        {"b1": idx},
        token_count_fn=lambda s, u: len((s + u).split()),
    )
    rt = DataMatePipeline.load_runtime_context(art.bundle_dir, expected_business_id="b1")
    grounded = engine.ground(
        QuestionRequest(
            question_id="q1",
            business_id="b1",
            question="Doanh thu tháng này là bao nhiêu?",
            as_of_date="2026-02-20",
        ),
        rt.grounding_context,
    )
    # No mentions, no resolved_windows, no matched_values -> omit hint completely (None) rather than poisoning 9B
    assert GroundingToPlannerAdapter.format_grounded_hint_for_v1_2(grounded) is None


def test_grounding_cache_round_trip_and_pipeline_trace(tmp_path: Path) -> None:
    split_dir, bundles_dir = _write_minimal_split(tmp_path)
    art = prepare_business(
        split_dir / "b1",
        bundles_dir / "b1",
        rulebook=split_dir / "rulebook.md",
        calendar=split_dir / "calendar.csv",
    )
    idx = GroundingContextIndex(
        art.bundle_dir,
        rulebook=split_dir / "rulebook.md",
        calendar=split_dir / "calendar.csv",
    )
    engine = NeoGroundingEngine(
        lambda _s, _u: _minimal_proposal_json(),
        {"b1": idx},
        token_count_fn=lambda s, u: len((s + u).split()),
    )
    rt = DataMatePipeline.load_runtime_context(art.bundle_dir, expected_business_id="b1")
    grounded = engine.ground(
        QuestionRequest(
            question_id="q1",
            business_id="b1",
            question="Doanh thu tháng này là bao nhiêu?",
            as_of_date="2026-02-20",
        ),
        rt.grounding_context,
    )

    cache_file = tmp_path / "grounding_cache.jsonl"
    save_grounding_cache(
        cache_file,
        [serialize_grounded_question(grounded, elapsed_ms=42.5, index_fingerprint=idx.fingerprint)],
    )
    loaded = load_grounding_cache(cache_file)
    restored, cached_ms = loaded["q1"]
    assert cached_ms == 42.5
    assert restored.grounding_source == "llm_verified"
    assert restored.planner_input["request"]["contract_version"] == "3.0"

    seen_hints: list[dict] = []

    class DummyV12LLM(BaseLLM):
        def load(self) -> None:
            pass

        def generate(self, prompt: str, *, options=None):
            raise NotImplementedError

        def generate_batch(self, prompts, *, options=None):
            raise NotImplementedError

        def chat(self, messages, *, options=None) -> GenerationResult:
            payload = json.loads(messages[1].content)
            seen_hints.append(payload["grounded_hint"])
            tbl = next(t["table"] for t in payload["context"]["schema"] if "orders" in t["table"])
            return GenerationResult(
                text=json.dumps(
                    {
                        "status": "answerable",
                        "structured_plan": {
                            "metric": {"name": "Doanh thu", "aggregation": "sum", "column": f"{tbl}.amount", "formula": None},
                            "grain": "order",
                            "source_tables": [tbl],
                            "joins": [],
                            "filters": [],
                            "time_range": {"column": f"{tbl}.order_date", "start_inclusive": "2026-02-01", "end_exclusive": "2026-02-21"},
                            "group_by": [],
                            "order_by": [],
                            "limit": None,
                            "output_shape": "scalar",
                            "rule_refs": [],
                        },
                        "sql": f"SELECT SUM(amount) FROM {tbl}",
                        "answer_type": "number",
                        "reason": None,
                    }
                ),
                input_tokens=50,
                output_tokens=20,
                finish_reason="stop",
            )

    out_dir = tmp_path / "run_out"
    pipeline = DataMatePipeline(
        Text2SQLGenerator(DummyV12LLM(), prompt_format="v1_2", grounded_hint_mode="compact_json"),
        voting=VotingConfig(enabled=False),
        grounding_runtime=CachedGroundingRuntime(loaded),
        grounded_hint_mode="compact_json",
    )
    outcomes = pipeline.run_questions(
        questions=[
            {
                "id": "q1",
                "business_id": "b1",
                "question": "Doanh thu tháng này là bao nhiêu?",
                "as_of_date": "2026-02-20",
            }
        ],
        bundles={"b1": art.bundle_dir},
        output_dir=out_dir,
        batch_size=1,
        verbose=False,
    )
    assert len(outcomes) == 1
    assert outcomes[0].decision == "answer", (outcomes[0].reason_code, outcomes[0].validation)
    assert seen_hints[0]["contract_version"] == "3.0"
    assert seen_hints[0]["resolved_windows"][0]["start_inclusive"] == "2026-02-01"

    trace_line = json.loads((out_dir / "grounding_trace.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert trace_line["grounding_source"] == "llm_verified"
    assert trace_line["contract_version"] == "3.0"
    assert trace_line["grounding_elapsed_ms"] == 42.5
    assert trace_line["resolved_windows"][0]["end_exclusive"] == "2026-02-21"


def test_run_pipeline_cli_two_phase_and_split_phases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.run_pipeline as rp

    split_dir, bundles_dir = _write_minimal_split(tmp_path)
    out_dir = tmp_path / "two_phase_out"
    cache_path = out_dir / "grounding_cache.jsonl"
    cfg_9b = Path("configs/qwen3_5_9b_ft_v1_2.toml").resolve()
    cfg_3b = Path("configs/qwen2_5_3b_neo_grounding.toml").resolve()

    # Check CLI parser defaults switched to neo + two-phase
    monkeypatch.setattr("sys.argv", ["run_pipeline.py"])
    cli_defaults = rp.parse_args()
    assert cli_defaults.grounding_engine == "neo"
    assert cli_defaults.phase == "all"
    assert cli_defaults.two_phase is True
    assert cli_defaults.grounding_config is None

    # Mock NeoGroundingEngine.from_qwen so Phase 1 runs Semantic Discovery + Grounding WITHOUT loading 9B
    vllm_9b_calls: list[Path] = []
    neo_3b_calls: list[Path] = []

    def fake_from_qwen(config_path, indexes, *, model_path_override=None, debug_model_output=False):
        neo_3b_calls.append(Path(config_path))
        sem_json = json.dumps(
            {
                "metrics": [{"metric_id": "revenue", "preferred_table": "orders"}],
                "unit_conversions": [
                    {"item_name": "Nước", "from_unit": "thùng", "to_unit": "chai", "factor": 24.0}
                ],
                "suggested_joins": [],
            },
            ensure_ascii=False,
        )
        return NeoGroundingEngine(
            lambda _s, _u: _minimal_proposal_json(),
            indexes,
            token_count_fn=lambda s, u: len((s + u).split()),
            unstructured_chat_fn=lambda _s, _u: sem_json,
        )

    class Fake9BVLLM(BaseLLM):
        def load(self) -> None:
            vllm_9b_calls.append(Path("loaded"))

        def generate(self, prompt: str, *, options=None):
            raise NotImplementedError

        def generate_batch(self, prompts, *, options=None):
            raise NotImplementedError

        def chat(self, messages, *, options=None) -> GenerationResult:
            payload = json.loads(messages[1].content)
            assert payload["grounded_hint"]["contract_version"] == "3.0"
            assert any(t["table"] == "unit_conversions" for t in payload["context"]["schema"])
            assert any(
                str(r.get("id", "")).startswith("SEM_JOIN") or str(r.get("id", "")).startswith("SEM_METRIC")
                for r in payload["context"]["rules"]
            )
            tbl = next(t["table"] for t in payload["context"]["schema"] if t["table"].startswith("orders"))
            return GenerationResult(
                text=json.dumps(
                    {
                        "status": "answerable",
                        "structured_plan": {
                            "metric": {"name": "Doanh thu", "aggregation": "sum", "column": f"{tbl}.amount", "formula": None},
                            "grain": "order",
                            "source_tables": [tbl],
                            "joins": [],
                            "filters": [],
                            "time_range": {"column": f"{tbl}.order_date", "start_inclusive": "2026-02-01", "end_exclusive": "2026-02-21"},
                            "group_by": [],
                            "order_by": [],
                            "limit": None,
                            "output_shape": "scalar",
                            "rule_refs": [],
                        },
                        "sql": f"SELECT SUM(amount) FROM {tbl}",
                        "answer_type": "number",
                        "reason": None,
                    }
                ),
                input_tokens=50,
                output_tokens=20,
                finish_reason="stop",
            )

    monkeypatch.setattr("datamate.grounding.NeoGroundingEngine.from_qwen", staticmethod(fake_from_qwen))
    monkeypatch.setattr("scripts.run_pipeline.VLLMModel", lambda cfg, default_options=None: Fake9BVLLM())

    # Phase 1: grounding only
    summary_p1 = rp.run_pipeline_cli(
        split_dir=split_dir,
        bundles_dir=bundles_dir,
        output_dir=out_dir,
        config_path=cfg_9b,
        grounding_engine="neo",
        grounding_config_path=cfg_3b,
        grounding_cache_path=cache_path,
        phase="grounding",
        two_phase=False,
        verbose=False,
    )
    assert summary_p1["phase"] == "grounding"
    assert summary_p1["cached_questions"] == 1
    assert len(neo_3b_calls) == 1
    assert len(vllm_9b_calls) == 0
    assert cache_path.is_file()

    # Verify Semantic Discovery synced bidirectional unit_conversions to DuckDB BEFORE GroundingContextIndex
    duck_files = list((bundles_dir / "b1").rglob("data.duckdb"))
    assert len(duck_files) == 1
    with duckdb.connect(str(duck_files[0]), read_only=True) as conn:
        rows = conn.execute("SELECT from_unit, to_unit, factor FROM unit_conversions ORDER BY from_unit").fetchall()
    assert len(rows) == 2

    # Missing cache in Phase 2 fails fast when engine == 'neo'
    with pytest.raises(FileNotFoundError):
        rp.run_pipeline_cli(
            split_dir=split_dir,
            bundles_dir=bundles_dir,
            output_dir=out_dir,
            config_path=cfg_9b,
            grounding_engine="neo",
            grounding_cache_path=tmp_path / "does_not_exist.jsonl",
            phase="planner",
            two_phase=False,
            verbose=False,
        )

    # Phase 2: planner only (must NOT reload 3B and must reuse Phase-1 enriched bundle without corrupt-* wipes)
    prep_calls: list[Path] = []
    orig_prepare = DataMatePipeline.prepare_bundle

    def spy_prepare(*args, **kwargs):
        prep_calls.append(Path(kwargs["output_dir"]))
        return orig_prepare(*args, **kwargs)

    monkeypatch.setattr("datamate.pipeline.DataMatePipeline.prepare_bundle", staticmethod(spy_prepare))

    summary_p2 = rp.run_pipeline_cli(
        split_dir=split_dir,
        bundles_dir=bundles_dir,
        output_dir=out_dir,
        config_path=cfg_9b,
        grounding_engine="neo",
        grounding_cache_path=cache_path,
        phase="planner",
        two_phase=False,
        voting=False,
        verbose=False,
    )
    assert summary_p2["evaluation"]["correct"] == 1
    assert len(prep_calls) == 0  # reused nested Phase-1 enriched bundle without re-ingesting!
    assert not list((bundles_dir / "b1").rglob("corrupt-*"))
    assert len(neo_3b_calls) == 1  # unchanged — 3B was NOT loaded in Phase 2!
    assert len(vllm_9b_calls) == 1
    assert (out_dir / "submission.jsonl").is_file()

    # Verify --two-phase orchestrator spawns grounding then planner subprocesses
    spawned: list[list[str]] = []

    def fake_subprocess_run(cmd, check=True):
        spawned.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("scripts.run_pipeline.subprocess.run", fake_subprocess_run)
    summary_two = rp.run_pipeline_cli(
        split_dir=split_dir,
        bundles_dir=bundles_dir,
        output_dir=out_dir,
        config_path=cfg_9b,
        grounding_engine="neo",
        grounding_cache_path=cache_path,
        phase="all",
        two_phase=True,
        voting=False,
        verbose=False,
    )
    assert summary_two["phase"] == "two_phase"
    assert len(spawned) == 2
    assert "--phase" in spawned[0] and spawned[0][spawned[0].index("--phase") + 1] == "grounding"
    assert "--phase" in spawned[1] and spawned[1][spawned[1].index("--phase") + 1] == "planner"


def test_rtx5090_configs_predict_sh_and_modal_sync() -> None:
    neo_cfg, _, _ = load_pipeline_config("configs/qwen2_5_3b_neo_grounding.toml")
    assert neo_cfg.gpu_memory_utilization == 0.70
    assert neo_cfg.max_model_len == 8192

    ft_cfg, _, ft_voting = load_pipeline_config("configs/qwen3_5_9b_ft_v1_2.toml")
    assert ft_cfg.gpu_memory_utilization == 0.85
    assert ft_cfg.max_model_len == 24576
    assert ft_cfg.max_num_seqs == 8
    assert ft_voting.enabled is True
    assert ft_voting.initial_candidates == 4

    syntax = subprocess.run(["bash", "-n", "predict.sh"], check=False, capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr

    predict_text = Path("predict.sh").read_text(encoding="utf-8")
    assert "--grounding-engine" in predict_text
    assert "--two-phase" in predict_text

    from scripts import modal_run_pipeline as mrp

    modal_sig = inspect.signature(mrp.main.info.raw_f).parameters
    assert modal_sig["grounding_engine"].default == "neo"
    assert modal_sig["two_phase"].default is True
    assert modal_sig["batch_size"].default == 8
