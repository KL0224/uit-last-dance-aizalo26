"""Tests for pre-seeded abstain submissions, business-balanced sharding, and multi-GPU execution."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from datamate.gate import (
    merge_shard_artifacts,
    partition_questions_by_business,
    seed_abstain_submission,
    upsert_submission_records,
)
from datamate.ingestion.ingestion import prepare_business
from datamate.pipeline import DataMatePipeline
from datamate.planner import BaseLLM, GenerationResult, Text2SQLGenerator
from datamate.voting import VotingConfig


def test_partition_questions_by_business_is_disjoint_and_balanced() -> None:
    questions = [
        {"id": "q1", "business_id": "b_big", "question": "1", "as_of_date": "2026-01-01"},
        {"id": "q2", "business_id": "b_big", "question": "2", "as_of_date": "2026-01-01"},
        {"id": "q3", "business_id": "b_big", "question": "3", "as_of_date": "2026-01-01"},
        {"id": "q4", "business_id": "b_mid1", "question": "4", "as_of_date": "2026-01-01"},
        {"id": "q5", "business_id": "b_mid1", "question": "5", "as_of_date": "2026-01-01"},
        {"id": "q6", "business_id": "b_mid2", "question": "6", "as_of_date": "2026-01-01"},
        {"id": "q7", "business_id": "b_mid2", "question": "7", "as_of_date": "2026-01-01"},
    ]
    s0_q, s0_b = partition_questions_by_business(questions, num_shards=2, shard_index=0)
    s1_q, s1_b = partition_questions_by_business(questions, num_shards=2, shard_index=1)

    assert set(s0_b).isdisjoint(set(s1_b))
    assert {q["id"] for q in s0_q} | {q["id"] for q in s1_q} == {f"q{i}" for i in range(1, 8)}
    assert len(s0_q) == 3 and len(s1_q) == 4  # balanced LPT: b_big (3) vs b_mid1+b_mid2 (4)

    # Edge case: fewer businesses than shards
    only_one = [{"id": "q1", "business_id": "solo", "question": "1", "as_of_date": "2026-01-01"}]
    q_s0, _ = partition_questions_by_business(only_one, num_shards=2, shard_index=0)
    q_s1, _ = partition_questions_by_business(only_one, num_shards=2, shard_index=1)
    assert len(q_s0) == 1
    assert len(q_s1) == 0


def test_seed_abstain_and_live_upsert_preserve_order_and_uncompleted_abstain(tmp_path: Path) -> None:
    questions = [
        {"id": "q3", "business_id": "b2"},
        {"id": "q1", "business_id": "b1"},
        {"id": "q2", "business_id": "b1"},
    ]
    out_dir = tmp_path / "out"
    manifest = seed_abstain_submission(out_dir, questions)
    assert manifest["record_count"] == 3

    seeded_lines = [
        json.loads(line)
        for line in (out_dir / "submission.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert seeded_lines == [
        {"id": "q3", "type": "abstain"},
        {"id": "q1", "type": "abstain"},
        {"id": "q2", "type": "abstain"},
    ]

    # Shard 1 completes q3 only; Shard 0 is interrupted before q2 -> q1 has real answer, q2 stays abstain!
    upsert_submission_records(
        out_dir,
        {"q3": {"id": "q3", "type": "number", "answer": 99}},
        expected_ids=["q3", "q1", "q2"],
    )
    upsert_submission_records(
        out_dir,
        {"q1": {"id": "q1", "type": "number", "answer": 42}},
        expected_ids=["q3", "q1", "q2"],
    )

    updated_lines = [
        json.loads(line)
        for line in (out_dir / "submission.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert updated_lines == [
        {"id": "q3", "type": "number", "answer": 99},
        {"id": "q1", "type": "number", "answer": 42},
        {"id": "q2", "type": "abstain"},
    ]


def test_crash_mid_run_keeps_completed_answers_and_abstain_remainder(tmp_path: Path) -> None:
    import scripts.run_pipeline as rp

    split_dir = tmp_path / "split"
    b_dir = split_dir / "b1"
    b_dir.mkdir(parents=True)
    (b_dir / "orders.csv").write_text("id,amount\n1,100\n", encoding="utf-8")
    (split_dir / "questions.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"id": "q1", "business_id": "b1", "question": "Q1?", "as_of_date": "2026-01-01"}),
                json.dumps({"id": "q2", "business_id": "b1", "question": "Q2?", "as_of_date": "2026-01-01"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    class FailOnSecondQuestionLLM(BaseLLM):
        def __init__(self) -> None:
            self.calls = 0

        def load(self) -> None:
            pass

        def generate(self, prompt: str, *, options=None):
            raise NotImplementedError

        def generate_batch(self, prompts, *, options=None):
            raise NotImplementedError

        def chat(self, messages, *, options=None) -> GenerationResult:
            self.calls += 1
            if self.calls >= 2:
                raise KeyboardInterrupt("Simulated GPU preemption mid-run")
            payload = json.loads(messages[1].content)
            tbl = next(t["table"] for t in payload["context"]["schema"] if "orders" in t["table"])
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
                input_tokens=20,
                output_tokens=10,
                finish_reason="stop",
            )

    out_dir = tmp_path / "crash_out"
    bundles_dir = tmp_path / "bundles"
    art = prepare_business(b_dir, bundles_dir / "b1")
    assert art.bundle_dir.is_dir()

    all_qs = rp._load_and_filter_questions(split_dir)
    rp.seed_abstain_submission(out_dir, all_qs)
    expected_ids = ["q1", "q2"]

    pipeline = DataMatePipeline(
        Text2SQLGenerator(FailOnSecondQuestionLLM(), prompt_format="v1_2"),
        voting=VotingConfig(enabled=False),
        enable_grounding=False,
    )
    work_dir = out_dir / "_work"
    with pytest.raises(KeyboardInterrupt):
        try:
            pipeline.run_questions(
                questions=all_qs,
                bundles={"b1": art.bundle_dir},
                output_dir=work_dir,
                batch_size=1,
                on_outcomes_flushed=lambda chunk: upsert_submission_records(
                    out_dir,
                    {str(o.question_id): o.final_answer.to_submission_dict() for o in chunk if o.final_answer},
                    expected_ids=expected_ids,
                ),
            )
        finally:
            merge_shard_artifacts(out_dir, [work_dir], expected_ids=expected_ids)

    lines = [
        json.loads(line)
        for line in (out_dir / "submission.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines == [
        {"id": "q1", "type": "number", "answer": 100},
        {"id": "q2", "type": "abstain"},
    ]


def test_multi_gpu_orchestrator_spawns_parallel_shards_and_recovers_on_partial_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.run_pipeline as rp

    split_dir = tmp_path / "split"
    split_dir.mkdir()
    questions = [
        {"id": "q1", "business_id": "b1", "question": "Q1?", "as_of_date": "2026-01-01"},
        {"id": "q2", "business_id": "b2", "question": "Q2?", "as_of_date": "2026-01-01"},
    ]
    (split_dir / "questions.jsonl").write_text(
        "\n".join(json.dumps(q) for q in questions) + "\n", encoding="utf-8"
    )
    (split_dir / "answers.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"id": "q1", "type": "number", "answer": 10}),
                json.dumps({"id": "q2", "type": "number", "answer": 20}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    assert rp._resolve_gpu_ids(num_gpus=None, gpu_ids=None) == ["0", "1"]

    spawned: list[tuple[list[str], dict[str, str]]] = []

    class FakePopen:
        def __init__(self, cmd: list[str], env: dict[str, str], fail_shard1: bool = False) -> None:
            self.cmd = list(cmd)
            self.env = dict(env)
            spawned.append((self.cmd, self.env))
            shard_idx = int(self.cmd[self.cmd.index("--shard-index") + 1])
            shard_out = Path(self.cmd[self.cmd.index("--output-dir") + 1])
            shard_out.mkdir(parents=True, exist_ok=True)
            merge_dir = Path(self.cmd[self.cmd.index("--merge-target-dir") + 1])
            if shard_idx == 0:
                (shard_out / "submission.jsonl").write_text(
                    json.dumps({"id": "q1", "type": "number", "answer": 10}) + "\n",
                    encoding="utf-8",
                )
                (shard_out / "detailed_logs.jsonl").write_text(
                    json.dumps({"id": "q1", "decision": "answer"}) + "\n",
                    encoding="utf-8",
                )
                upsert_submission_records(
                    merge_dir,
                    {"q1": {"id": "q1", "type": "number", "answer": 10}},
                    expected_ids=["q1", "q2"],
                )
                self._rc = 0
            elif not fail_shard1:
                (shard_out / "submission.jsonl").write_text(
                    json.dumps({"id": "q2", "type": "number", "answer": 20}) + "\n",
                    encoding="utf-8",
                )
                (shard_out / "detailed_logs.jsonl").write_text(
                    json.dumps({"id": "q2", "decision": "answer"}) + "\n",
                    encoding="utf-8",
                )
                upsert_submission_records(
                    merge_dir,
                    {"q2": {"id": "q2", "type": "number", "answer": 20}},
                    expected_ids=["q1", "q2"],
                )
                self._rc = 0
            else:
                self._rc = 1

        def wait(self, timeout=None) -> int:
            return self._rc

        def poll(self) -> int:
            return self._rc

    # Success case: both GPUs succeed and merge
    out_ok = tmp_path / "out_ok"
    monkeypatch.setattr(
        "scripts.run_pipeline.subprocess.Popen",
        lambda cmd, env=None: FakePopen(cmd, env or {}, fail_shard1=False),
    )
    summary_ok = rp.run_pipeline_cli(
        split_dir=split_dir,
        bundles_dir=tmp_path / "bundles",
        output_dir=out_ok,
        config_path=Path("configs/qwen3_5_9b_ft_v1_2.toml"),
        grounding_engine="neo",
        two_phase=True,
        num_gpus=2,
        verbose=False,
    )
    assert summary_ok["phase"] == "multi_gpu"
    assert summary_ok["evaluation"]["correct"] == 2
    assert len(spawned) == 2
    assert spawned[0][1]["CUDA_VISIBLE_DEVICES"] == "0"
    assert spawned[1][1]["CUDA_VISIBLE_DEVICES"] == "1"
    assert spawned[0][1]["B04_DUCKDB_TEMP_DIR"] != spawned[1][1]["B04_DUCKDB_TEMP_DIR"]
    merged_subs = [
        json.loads(line)
        for line in (out_ok / "submission.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert merged_subs == [
        {"id": "q1", "type": "number", "answer": 10},
        {"id": "q2", "type": "number", "answer": 20},
    ]
    assert not (out_ok / "_shards").exists()
    assert not (out_ok / ".submission.lock").exists()
    assert not (out_ok / "_work").exists()
    assert not any(
        d.name.startswith("datamate_shards_out_ok_")
        for d in Path(rp.tempfile.gettempdir()).iterdir()
        if d.is_dir()
    )

    # Partial failure case: shard 1 fails, yet shard 0's answer + shard 1's abstain are preserved!
    out_partial = tmp_path / "out_partial"
    monkeypatch.setattr(
        "scripts.run_pipeline.subprocess.Popen",
        lambda cmd, env=None: FakePopen(cmd, env or {}, fail_shard1=True),
    )
    with pytest.raises(RuntimeError, match="Multi-GPU workers failed"):
        rp.run_pipeline_cli(
            split_dir=split_dir,
            bundles_dir=tmp_path / "bundles",
            output_dir=out_partial,
            config_path=Path("configs/qwen3_5_9b_ft_v1_2.toml"),
            grounding_engine="neo",
            two_phase=True,
            num_gpus=2,
            verbose=False,
        )
    partial_subs = [
        json.loads(line)
        for line in (out_partial / "submission.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert partial_subs == [
        {"id": "q1", "type": "number", "answer": 10},
        {"id": "q2", "type": "abstain"},
    ]
    assert not (out_partial / "_shards").exists()
    assert not (out_partial / ".submission.lock").exists()


def test_predict_sh_multi_gpu_flags_and_syntax() -> None:
    res = subprocess.run(["bash", "-n", "predict.sh"], capture_output=True, text=True, check=False)
    assert res.returncode == 0, res.stderr
    text = Path("predict.sh").read_text(encoding="utf-8")
    assert "qwen2_5_3b_neo_grounding.toml" in text
    assert "--num-gpus" in text
    assert "--gpu-ids" in text
