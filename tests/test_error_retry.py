"""Tests for Error Classifier and Bounded Retry Controller."""

import pytest
from datamate.gate.adapters import adapt_gate_request
from datamate.gate.contracts import ExecutionErrorDetail, GateAction, GateRequest
from datamate.gate.errors import ErrorCode
from datamate.gate.retry import classify_error, decide_retry


def make_error_request(error_type: str, error_msg: str, attempt: int = 0) -> GateRequest:
    raw = {
        "contract_version": "b05.v1",
        "question": {"id": "q_err", "business_id": "biz", "question": "test", "as_of_date": "2026-03-04"},
        "generation": {
            "answer_type": "number",
            "sql": "SELECT order_code FROM orders",
            "tables_used": ["orders"],
            "answer_semantics": {"numeric_kind": "count"}
        },
        "execution": {
            "status": "error",
            "columns": [],
            "rows": [],
            "error": {"type": error_type, "message": error_msg}
        },
        "attempt": attempt
    }
    return adapt_gate_request(raw)


def test_classify_schema_error():
    err = ExecutionErrorDetail(type="BinderException", message="Column order_code not found")
    classification = classify_error(err, None)
    assert classification.code == ErrorCode.SCHEMA_ERROR
    assert classification.retryable is True


def test_classify_syntax_error():
    err = ExecutionErrorDetail(type="ParserException", message="syntax error at or near 'SELCT'")
    classification = classify_error(err, None)
    assert classification.code == ErrorCode.SQL_SYNTAX
    assert classification.retryable is True


def test_classify_security_violation():
    err = ExecutionErrorDetail(type="SecurityException", message="DROP TABLE forbidden in read-only mode")
    classification = classify_error(err, None)
    assert classification.code == ErrorCode.SECURITY_VIOLATION
    assert classification.retryable is False


def test_bounded_retry_attempt_0_to_1():
    req = make_error_request("BinderException", "Column order_code not found", attempt=0)
    classification = classify_error(req.execution.error, None)
    repair = decide_retry(req, classification)
    assert repair is not None
    assert repair.attempt == 1
    assert repair.error_code == ErrorCode.SCHEMA_ERROR


def test_bounded_retry_exhausted_at_attempt_1():
    req = make_error_request("BinderException", "Column order_code not found", attempt=1)
    classification = classify_error(req.execution.error, None)
    repair = decide_retry(req, classification)
    assert repair is None  # No more retry!

