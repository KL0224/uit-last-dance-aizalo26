"""Tests for coercing single-date LIST results to DATE on singular date questions."""

import datetime

from datamate.gate.contracts import (
    AnswerType,
    ExecutionResult,
    ExecutionStatus,
    GateAction,
    GateRequest,
    GenerationResult,
    QuestionMeta,
)
from datamate.gate.gate import evaluate_gate


def _make_request(question_text: str, rows: list, *, answer_type: str = AnswerType.LIST) -> GateRequest:
    return GateRequest(
        contract_version="b05.v1",
        question=QuestionMeta(
            id="q_065aa2aac90c",
            business_id="biz_111",
            question=question_text,
            as_of_date="2026-02-28",
        ),
        generation=GenerationResult(
            answer_type=answer_type,
            sql="SELECT d, total FROM t ORDER BY total DESC LIMIT 1",
        ),
        execution=ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["d", "total"] if rows and len(rows[0]) > 1 else ["d"],
            rows=rows,
        ),
    )


def test_single_date_list_coerced_to_date_for_singular_date_question() -> None:
    req = _make_request(
        "thang 2/2026 ngay nao cua hang ban dc nhiu tien nhat",
        rows=[["2026-02-05", 1000000]],
    )
    outcome = evaluate_gate(req)
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer is not None
    assert outcome.final_answer.type == AnswerType.DATE
    assert outcome.final_answer.answer == "2026-02-05"


def test_single_month_and_python_date_coerced_to_date() -> None:
    req_date = _make_request(
        "Ngày nào có doanh thu cao nhất?",
        rows=[[datetime.date(2026, 2, 5)]],
    )
    outcome_date = evaluate_gate(req_date)
    assert outcome_date.final_answer is not None
    assert outcome_date.final_answer.type == AnswerType.DATE
    assert outcome_date.final_answer.answer == "2026-02-05"

    req_month = _make_request(
        "Tháng nào cửa hàng bán tốt nhất?",
        rows=[["2026-02"]],
    )
    outcome_month = evaluate_gate(req_month)
    assert outcome_month.final_answer is not None
    assert outcome_month.final_answer.type == AnswerType.DATE
    assert outcome_month.final_answer.answer == "2026-02"


def test_plural_or_multi_row_or_non_date_remains_list() -> None:
    plural_req = _make_request(
        "các ngày nào bán nhiều nhất",
        rows=[["2026-02-05"]],
    )
    plural_out = evaluate_gate(plural_req)
    assert plural_out.final_answer is not None
    assert plural_out.final_answer.type == AnswerType.LIST
    assert plural_out.final_answer.answer == ["2026-02-05"]

    multi_req = _make_request(
        "thang 2/2026 ngay nao ban nhieu nhat",
        rows=[["2026-02-05"], ["2026-02-06"]],
    )
    multi_out = evaluate_gate(multi_req)
    assert multi_out.final_answer is not None
    assert multi_out.final_answer.type == AnswerType.LIST
    assert multi_out.final_answer.answer == ["2026-02-05", "2026-02-06"]

    non_date_req = _make_request(
        "khi nào hết hàng thì nhập món nào?",
        rows=[["Cà phê sữa"]],
    )
    non_date_out = evaluate_gate(non_date_req)
    assert non_date_out.final_answer is not None
    assert non_date_out.final_answer.type == AnswerType.LIST
    assert non_date_out.final_answer.answer == ["Cà phê sữa"]
