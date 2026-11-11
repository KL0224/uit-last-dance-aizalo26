"""Tests for canonical, atomic B0.5 submission finalization."""

import hashlib
import json
from pathlib import Path

import pytest

from datamate.gate.contracts import AnswerType, FinalAnswer, GateAction, GateOutcome
from datamate.gate.errors import OutputWriteError
from datamate.gate.finalizer import SubmissionFinalizer


def _outcome(question_id: str, answer: int) -> GateOutcome:
    return GateOutcome(
        action=GateAction.FINAL,
        question_id=question_id,
        decision="answer",
        final_answer=FinalAnswer(id=question_id, type=AnswerType.NUMBER, answer=answer),
        reason_code="VALID_RESULT",
    )


def test_finalizer_writes_manifest_order_atomically_and_deterministically(tmp_path: Path):
    finalizer = SubmissionFinalizer(tmp_path)
    outcomes = [_outcome("q_b", 2), _outcome("q_a", 1)]

    first = finalizer.finalize(outcomes, expected_ids=["q_a", "q_b"])
    first_bytes = (tmp_path / "submission.jsonl").read_bytes()
    second = finalizer.finalize(reversed(outcomes), expected_ids=["q_a", "q_b"])

    assert (tmp_path / "submission.jsonl").read_bytes() == first_bytes
    assert first["sha256"] == second["sha256"] == hashlib.sha256(first_bytes).hexdigest()
    assert first["record_count"] == 2
    assert not (tmp_path / "submission.jsonl.tmp").exists()
    records = [json.loads(line) for line in first_bytes.decode().splitlines()]
    assert [record["id"] for record in records] == ["q_a", "q_b"]


@pytest.mark.parametrize(
    ("outcomes", "expected_ids", "message"),
    [
        ([_outcome("q_a", 1), _outcome("q_a", 2)], ["q_a"], "Duplicate"),
        ([_outcome("q_a", 1)], ["q_a", "q_b"], "missing"),
        ([_outcome("q_a", 1), _outcome("q_b", 2)], ["q_a"], "extra"),
    ],
)
def test_finalizer_rejects_noncanonical_question_sets(
    tmp_path: Path, outcomes, expected_ids, message: str
):
    with pytest.raises(OutputWriteError, match=message):
        SubmissionFinalizer(tmp_path).finalize(outcomes, expected_ids=expected_ids)

    assert not (tmp_path / "submission.jsonl").exists()

def test_finalizer_rejects_invalid_type_before_writing(tmp_path: Path):
    outcome = _outcome("q_bad", 1)
    outcome.final_answer.type = "ubstain"

    with pytest.raises(OutputWriteError, match="Invalid answer type"):
        SubmissionFinalizer(tmp_path).finalize([outcome], expected_ids=["q_bad"])

    assert not (tmp_path / "submission.jsonl").exists()


def test_finalizer_rejects_artifact_mismatch_before_writing(tmp_path: Path):
    outcomes = [_outcome("q_a", 1)]
    corrupted_reference = [{"id": "q_a", "type": "ananswerable"}]

    with pytest.raises(OutputWriteError, match="Artifact mismatch"):
        SubmissionFinalizer(tmp_path).finalize(
            outcomes,
            expected_ids=["q_a"],
            reference_records=corrupted_reference,
        )

    assert not (tmp_path / "submission.jsonl").exists()
