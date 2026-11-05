"""Tests for B0.5 Determinism (Rerun gives same output)."""

from pathlib import Path
from datamate.b05.adapters import adapt_gate_request
from datamate.b05.gate import evaluate_gate
from datamate.b05.writer import SubmissionWriter


def test_gate_determinism(tmp_path: Path):
    raw_fixture = {
        "contract_version": "b05.v1",
        "question": {"id": "q_det", "business_id": "biz", "question": "Total?", "as_of_date": "2026-03-04"},
        "generation": {
            "answer_type": "number",
            "sql": "SELECT 100",
            "tables_used": [],
            "answer_semantics": {"numeric_kind": "count"}
        },
        "execution": {
            "status": "success",
            "columns": ["val"],
            "rows": [[100]],
            "row_count": 1,
            "truncated": False
        },
        "attempt": 0
    }

    # Run 1
    dir1 = tmp_path / "run1"
    writer1 = SubmissionWriter(result_dir=dir1)
    req1 = adapt_gate_request(raw_fixture)
    outcome1 = evaluate_gate(req1)
    writer1.write_final(outcome1)

    # Run 2
    dir2 = tmp_path / "run2"
    writer2 = SubmissionWriter(result_dir=dir2)
    req2 = adapt_gate_request(raw_fixture)
    outcome2 = evaluate_gate(req2)
    writer2.write_final(outcome2)

    # Compare outputs byte-by-byte
    bytes1 = (dir1 / "submission.jsonl").read_bytes()
    bytes2 = (dir2 / "submission.jsonl").read_bytes()
    assert bytes1 == bytes2

