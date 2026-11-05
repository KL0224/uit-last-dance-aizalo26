"""Tests for GateRequest contract adapter and input validation."""

import pytest
from datamate.b05.adapters import adapt_gate_request
from datamate.b05.contracts import AnswerType, ExecutionStatus, GateRequest
from datamate.b05.errors import ContractError, ErrorCode


def test_valid_gate_request():
    raw = {
        "contract_version": "b05.v1",
        "question": {
            "id": "q_001",
            "business_id": "biz_1",
            "question": "Có bao nhiêu đơn?",
            "as_of_date": "2026-03-04"
        },
        "generation": {
            "answer_type": "number",
            "sql": "SELECT COUNT(*) FROM orders",
            "tables_used": ["orders"],
            "answer_semantics": {"numeric_kind": "count"}
        },
        "execution": {
            "status": "success",
            "columns": ["count"],
            "rows": [[10]],
            "row_count": 1,
            "truncated": False
        },
        "attempt": 0
    }
    req = adapt_gate_request(raw)
    assert isinstance(req, GateRequest)
    assert req.question.id == "q_001"
    assert req.generation.answer_type == AnswerType.NUMBER
    assert req.execution.status == ExecutionStatus.SUCCESS


def test_invalid_contract_version():
    raw = {
        "contract_version": "v2_unknown",
        "question": {"id": "q_1", "business_id": "b", "question": "?", "as_of_date": "2026-03-04"},
        "execution": {"status": "success", "columns": [], "rows": []},
        "attempt": 0
    }
    with pytest.raises(ContractError):
        adapt_gate_request(raw)


def test_invalid_as_of_date_calendar():
    raw = {
        "contract_version": "b05.v1",
        "question": {"id": "q_bad", "business_id": "b", "question": "?", "as_of_date": "2026-02-30"},
        "execution": {"status": "success", "columns": ["n"], "rows": [[10]]},
        "attempt": 0
    }
    with pytest.raises(ContractError) as exc_info:
        adapt_gate_request(raw)
    assert "as_of_date" in str(exc_info.value)


def test_invalid_attempt():
    raw = {
        "contract_version": "b05.v1",
        "question": {"id": "q_1", "business_id": "b", "question": "?", "as_of_date": "2026-03-04"},
        "execution": {"status": "success", "columns": [], "rows": []},
        "attempt": 5  # only 0 or 1 allowed
    }
    with pytest.raises(ContractError):
        adapt_gate_request(raw)
