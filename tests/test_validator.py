"""Tests for Execution Validator."""

import pytest
from datamate.b05.adapters import adapt_gate_request
from datamate.b05.errors import ErrorCode
from datamate.b05.validators import validate_execution


def make_request(answer_type: str, status: str, columns: list, rows: list, truncated: bool = False, error: dict = None, semantics: dict = None):
    raw = {
        "contract_version": "b05.v1",
        "question": {"id": "q_test", "business_id": "biz", "question": "test", "as_of_date": "2026-03-04"},
        "generation": {
            "answer_type": answer_type,
            "sql": "SELECT ...",
            "tables_used": [],
            "answer_semantics": semantics or {}
        },
        "execution": {
            "status": status,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "error": error
        },
        "attempt": 0
    }
    return adapt_gate_request(raw)


def test_validator_scalar_success():
    req = make_request("number", "success", ["count"], [[125]])
    res = validate_execution(req)
    assert res.passed is True
    assert res.normalized_candidate == 125


def test_validator_scalar_null():
    req = make_request("number", "success", ["count"], [[None]])
    res = validate_execution(req)
    assert res.passed is False
    assert res.error_code == ErrorCode.NULL_RESULT


def test_validator_scalar_empty():
    req = make_request("number", "success", ["count"], [])
    res = validate_execution(req)
    assert res.passed is False
    assert res.error_code == ErrorCode.EMPTY_RESULT


def test_validator_scalar_shape_mismatch():
    req = make_request("number", "success", ["count"], [[1], [2]])
    res = validate_execution(req)
    assert res.passed is False
    assert res.error_code == ErrorCode.SCALAR_SHAPE_MISMATCH


def test_validator_truncated_result():
    req = make_request("list", "success", ["item"], [["A"], ["B"]], truncated=True)
    res = validate_execution(req)
    assert res.passed is False
    assert res.error_code == ErrorCode.TRUNCATED_RESULT


def test_validator_table_shape():
    # Row width mismatch
    req = make_request("table", "success", ["c1", "c2"], [["A"]])
    res = validate_execution(req)
    assert res.passed is False
    assert res.error_code == ErrorCode.TABLE_SHAPE_ERROR

