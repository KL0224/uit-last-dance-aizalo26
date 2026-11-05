"""Tests for SubmissionWriter and AuditLogger."""

import json
from pathlib import Path
import pytest
from datamate.b05.contracts import AnswerType, FinalAnswer, GateAction, GateOutcome
from datamate.b05.writer import SubmissionWriter


def test_writer_creates_valid_jsonl(tmp_path: Path):
    result_dir = tmp_path / "result"
    writer = SubmissionWriter(result_dir=result_dir)

    outcome = GateOutcome(
        action=GateAction.FINAL,
        question_id="q_001",
        decision="answer",
        final_answer=FinalAnswer(id="q_001", type=AnswerType.NUMBER, answer=125),
        reason_code="VALID_RESULT",
    )

    writer.write_final(outcome)

    submission_file = result_dir / "submission.jsonl"
    assert submission_file.exists()

    with open(submission_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record == {"id": "q_001", "type": "number", "answer": 125}

    # Verify per-question audit log exists
    log_files = list((result_dir / "logs").glob("*.json"))
    assert len(log_files) == 1


def test_writer_deduplication(tmp_path: Path):
    result_dir = tmp_path / "result"
    writer = SubmissionWriter(result_dir=result_dir)

    outcome1 = GateOutcome(
        action=GateAction.FINAL,
        question_id="q_dup",
        decision="answer",
        final_answer=FinalAnswer(id="q_dup", type=AnswerType.NUMBER, answer=10),
        reason_code="VALID_RESULT",
    )
    outcome2 = GateOutcome(
        action=GateAction.FINAL,
        question_id="q_dup",
        decision="answer",
        final_answer=FinalAnswer(id="q_dup", type=AnswerType.NUMBER, answer=20),
        reason_code="VALID_RESULT",
    )

    writer.write_final(outcome1)
    writer.write_final(outcome2)  # Duplicate ID

    submission_file = result_dir / "submission.jsonl"
    with open(submission_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    # Exactly 1 final line
    assert len(lines) == 1
    assert json.loads(lines[0])["answer"] == 10


def test_writer_abstain_has_no_answer_field(tmp_path: Path):
    result_dir = tmp_path / "result"
    writer = SubmissionWriter(result_dir=result_dir)

    outcome = GateOutcome(
        action=GateAction.FINAL,
        question_id="q_abs",
        decision="abstain",
        final_answer=FinalAnswer(id="q_abs", type=AnswerType.ABSTAIN),
        reason_code="RETRY_EXHAUSTED",
    )
    writer.write_final(outcome)

    submission_file = result_dir / "submission.jsonl"
    with open(submission_file, "r", encoding="utf-8") as f:
        line = f.readline().strip()

    record = json.loads(line)
    assert record == {"id": "q_abs", "type": "abstain"}
    assert "answer" not in record

