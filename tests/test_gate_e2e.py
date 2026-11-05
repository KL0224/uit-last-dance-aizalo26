"""End-to-End Tests for B0.5 Basic Output Gate using 36 mock cases (T01-T36)."""

import json
from pathlib import Path
import pytest
from datamate.b05.adapters import adapt_gate_request
from datamate.b05.cli import run_pipeline
from datamate.b05.contracts import AnswerType, Decision, GateAction
from datamate.b05.errors import ContractError, ErrorCode
from datamate.b05.gate import evaluate_gate


FIXTURES_FILE = Path(__file__).parent / "fixtures" / "b05_cases.jsonl"


def load_fixtures():
    fixtures = {}
    with open(FIXTURES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                data = json.loads(line)
                fixtures[data["question"]["id"]] = data
    return fixtures


FIXTURES = load_fixtures()


def test_t01_number_count():
    req = adapt_gate_request(FIXTURES["T01"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.decision == Decision.ANSWER
    assert outcome.final_answer.answer == 125


def test_t02_number_money_vnd_half_up():
    req = adapt_gate_request(FIXTURES["T02"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer == 1250001


def test_t03_number_average_nonmoney():
    req = adapt_gate_request(FIXTURES["T03"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer == 12.35


def test_t04_percent_points():
    req = adapt_gate_request(FIXTURES["T04"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer == -12.45


def test_t05_percent_fraction():
    req = adapt_gate_request(FIXTURES["T05"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer == 12.5


def test_t06_string_nfc():
    req = adapt_gate_request(FIXTURES["T06"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer == "Cà phê sữa"


def test_t07_date_iso():
    req = adapt_gate_request(FIXTURES["T07"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer == "2026-02-28"


def test_t08_month_iso():
    req = adapt_gate_request(FIXTURES["T08"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer == "2026-03"


def test_t09_boolean():
    req = adapt_gate_request(FIXTURES["T09"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer is True


def test_t10_list_ordered():
    req = adapt_gate_request(FIXTURES["T10"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer == ["A", "B"]


def test_t11_table():
    req = adapt_gate_request(FIXTURES["T11"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer == {
        "columns": ["ma", "qty"],
        "rows": [["SP01", 10], ["SP02", 20]]
    }


def test_t12_number_zero():
    req = adapt_gate_request(FIXTURES["T12"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer == 0


def test_t13_null_scalar_abstains():
    req = adapt_gate_request(FIXTURES["T13"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.decision == Decision.ABSTAIN
    assert outcome.reason_code == ErrorCode.NULL_RESULT


def test_t14_empty_scalar_abstains():
    req = adapt_gate_request(FIXTURES["T14"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.decision == Decision.ABSTAIN
    assert outcome.reason_code == ErrorCode.EMPTY_RESULT


def test_t15_multi_row_scalar_retries():
    req = adapt_gate_request(FIXTURES["T15"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.RETRY
    assert outcome.decision == Decision.RETRY
    assert outcome.reason_code == ErrorCode.SCALAR_SHAPE_MISMATCH


def test_t16_retry_exhausted_at_attempt_1():
    req = adapt_gate_request(FIXTURES["T16"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.decision == Decision.ABSTAIN
    assert outcome.reason_code == ErrorCode.RETRY_EXHAUSTED


def test_t17_binder_exception_retries():
    req = adapt_gate_request(FIXTURES["T17"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.RETRY
    assert outcome.reason_code == ErrorCode.SCHEMA_ERROR


def test_t18_binder_exception_attempt_1_exhausted():
    req = adapt_gate_request(FIXTURES["T18"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.reason_code == ErrorCode.RETRY_EXHAUSTED


def test_t19_parser_exception_retries():
    req = adapt_gate_request(FIXTURES["T19"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.RETRY
    assert outcome.reason_code == ErrorCode.SQL_SYNTAX


def test_t20_security_violation_never_retries():
    req = adapt_gate_request(FIXTURES["T20"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.decision == Decision.ABSTAIN
    assert outcome.reason_code == ErrorCode.SECURITY_VIOLATION


def test_t21_query_timeout():
    req = adapt_gate_request(FIXTURES["T21"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.decision == Decision.ABSTAIN
    assert outcome.reason_code == ErrorCode.QUERY_TIMEOUT


def test_t22_boolean_with_int_rejected():
    req = adapt_gate_request(FIXTURES["T22"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.RETRY  # output type error allows retry in attempt 0
    assert outcome.reason_code == ErrorCode.OUTPUT_TYPE_ERROR


def test_t23_nan_rejected():
    req = adapt_gate_request(FIXTURES["T23"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.RETRY
    assert outcome.reason_code == ErrorCode.OUTPUT_TYPE_ERROR


def test_t24_truncated_result():
    req = adapt_gate_request(FIXTURES["T24"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.decision == Decision.ABSTAIN
    assert outcome.reason_code == ErrorCode.TRUNCATED_RESULT


def test_t25_proven_unanswerable():
    req = adapt_gate_request(FIXTURES["T25"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.decision == Decision.UNANSWERABLE
    assert outcome.final_answer.type == AnswerType.UNANSWERABLE
    assert "cost_at_sale" in outcome.final_answer.reason


def test_t26_untrusted_unanswerable_claim_abstains():
    req = adapt_gate_request(FIXTURES["T26"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.decision == Decision.ABSTAIN
    assert outcome.reason_code == ErrorCode.MISSING_EVIDENCE


def test_t27_bad_calendar_date_contract_error():
    with pytest.raises(ContractError):
        adapt_gate_request(FIXTURES["T27"])


def test_t28_list_order_preserved():
    req = adapt_gate_request(FIXTURES["T28"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer == ["B", "A"]


def test_t31_not_executed_with_proven_missing():
    req = adapt_gate_request(FIXTURES["T31"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.decision == Decision.UNANSWERABLE


def test_t32_unknown_answer_type_contract_error():
    with pytest.raises(ContractError):
        adapt_gate_request(FIXTURES["T32"])


def test_t34_table_shape_mismatch():
    req = adapt_gate_request(FIXTURES["T34"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.decision == Decision.ABSTAIN
    assert outcome.reason_code == ErrorCode.TABLE_SHAPE_ERROR


def test_t35_allowed_empty_list():
    req = adapt_gate_request(FIXTURES["T35"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer == []


def test_t36_negative_percent_rounding_to_zero():
    req = adapt_gate_request(FIXTURES["T36"])
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.answer == 0


def test_cli_pipeline_run(tmp_path: Path):
    result_dir = tmp_path / "cli_run"
    summary = run_pipeline(FIXTURES_FILE, result_dir)

    assert summary["total"] == 36
    assert summary["answer"] > 0
    assert summary["unanswerable"] > 0
    assert summary["abstain"] > 0
    assert summary["retry_attempts"] > 0

    # Verify submission.jsonl exists and has rows matching unique questions
    sub_file = result_dir / "submission.jsonl"
    assert sub_file.exists()

    with open(sub_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    assert len(lines) == 36  # All 36 questions produced exactly 1 final line

