"""Compatibility tests between B0.4 (b1-4-executor_minh), B0.3, B0.5 Gate, and B0Pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from datamate.pipeline import B0Pipeline, Pipeline
from datamate.ingestion.ingestion import prepare_business
from datamate.planner import Text2SQLGenerator
from datamate.planner.types import GenerationResult as LLMGenerationResult, Text2SQLResult
from datamate.execution import ExecutionRequest, execute_query
from datamate.gate import evaluate_gate
from datamate.gate.contracts import (
    AnswerType,
    Decision,
    ExecutionErrorDetail,
    GateAction,
    GateRequest,
    GenerationResult as B05GenerationResult,
    QuestionMeta,
)
from datamate.gate.errors import ErrorCode
from datamate.gate.retry import classify_error


def _create_sample_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "compat.duckdb")
    con = duckdb.connect(db_path)
    con.execute(
        """
        CREATE TABLE customers (
            customer_id VARCHAR,
            customer_name VARCHAR,
            status VARCHAR,
            total_spent DOUBLE
        );
        INSERT INTO customers VALUES
            ('C1', 'Nguyen Van A', 'update record', 150000.0),
            ('C2', 'Tran Thi B', 'active', 250000.0);
        """
    )
    con.close()
    return db_path


def test_b04_empty_result_warning_triggers_b05_bounded_retry(tmp_path: Path):
    """B0.4 EmptyResultWarning on attempt 0 must trigger GateAction.RETRY in B0.5 Gate."""
    db_path = _create_sample_db(tmp_path)
    sql = "SELECT SUM(total_spent) AS total FROM customers WHERE status = 'non_existent'"

    req_0 = ExecutionRequest(
        question_id="q_null_agg",
        db_path=db_path,
        sql_query=sql,
        answer_type="number",
        retry_count=0,
        max_retries=1,
    )
    res_0 = execute_query(req_0)
    assert res_0.is_valid is False
    assert res_0.route == "recoverable"
    assert res_0.error_type == "EmptyResultWarning"

    gate_req_0 = GateRequest(
        contract_version="b05.v1",
        question=QuestionMeta("q_null_agg", "biz1", "Tổng chi tiêu?", "2026-04-01"),
        generation=B05GenerationResult(answer_type=AnswerType.NUMBER, sql=sql),
        execution=res_0.to_b05_execution_result(),
        attempt=0,
    )
    outcome_0 = evaluate_gate(gate_req_0)
    assert outcome_0.action == GateAction.RETRY
    assert outcome_0.decision == Decision.RETRY
    assert outcome_0.reason_code == ErrorCode.NULL_RESULT
    assert outcome_0.repair_request is not None
    assert outcome_0.repair_request.error_type == "EmptyResultWarning"
    assert "all NULL values" in outcome_0.repair_request.error_message

    # On attempt 1, if still all NULL, B0.4 passes rows=[{"total": None}] and B0.5 abstains with RETRY_EXHAUSTED
    req_1 = ExecutionRequest(
        question_id="q_null_agg",
        db_path=db_path,
        sql_query=sql,
        answer_type="number",
        retry_count=1,
        max_retries=1,
    )
    res_1 = execute_query(req_1)
    assert res_1.is_valid is True
    gate_req_1 = GateRequest(
        contract_version="b05.v1",
        question=QuestionMeta("q_null_agg", "biz1", "Tổng chi tiêu?", "2026-04-01"),
        generation=B05GenerationResult(answer_type=AnswerType.NUMBER, sql=sql),
        execution=res_1.to_b05_execution_result(),
        attempt=1,
    )
    outcome_1 = evaluate_gate(gate_req_1)
    assert outcome_1.action == GateAction.FINAL
    assert outcome_1.decision == Decision.ABSTAIN
    assert outcome_1.reason_code == ErrorCode.RETRY_EXHAUSTED


def test_b05_binder_error_with_sensitive_sql_literal_is_not_blocked_as_security(tmp_path: Path):
    """A BinderError whose echoed SQL contains 'update ' or 'delete ' must remain retryable SCHEMA_ERROR."""
    db_path = _create_sample_db(tmp_path)
    sql = "SELECT wrong_column FROM customers WHERE status = 'update record'"

    req = ExecutionRequest(
        question_id="q_binder_update",
        db_path=db_path,
        sql_query=sql,
        answer_type="number",
        retry_count=0,
        max_retries=1,
    )
    res = execute_query(req)
    assert res.is_valid is False
    assert res.route == "recoverable"
    assert res.error_type in ("BinderError", "CatalogError")
    assert "[Gợi ý Schema thực tế trong DB]:" in (res.error_message or "")

    b05_exec = res.to_b05_execution_result()
    classification = classify_error(b05_exec.error, None)
    assert classification.code == ErrorCode.SCHEMA_ERROR
    assert classification.retryable is True


def test_b04_conversion_error_with_column_mention_maps_to_sql_type_error():
    """ConversionError enriched with schema hints or mentioning column names maps to SQL_TYPE_ERROR."""
    err = ExecutionErrorDetail(
        type="ConversionError",
        message=(
            'Conversion Error: Could not convert string "abc" to INT64 in column "total_spent"\n'
            '[Gợi ý Schema thực tế trong DB]:\n  * Bảng "customers": "total_spent" (DOUBLE)'
        ),
    )
    classification = classify_error(err, None)
    assert classification.code == ErrorCode.SQL_TYPE_ERROR
    assert classification.retryable is True


def test_b04_from_b03_normalizes_answer_type_aliases_for_all_null_check(tmp_path: Path):
    """ExecutionRequest.from_b03 normalizes aliases like 'money' or 'int' to 'number'."""
    db_path = _create_sample_db(tmp_path)
    b03_res = Text2SQLResult(
        status="answerable",
        answer_type="money",
        sql="SELECT SUM(total_spent) FROM customers WHERE status = 'non_existent'",
        tables_used=("customers",),
    )
    req = ExecutionRequest.from_b03(
        b03_result=b03_res,
        question_id="q_alias",
        db_path=db_path,
        retry_count=0,
    )
    assert req.answer_type == "number"
    res = execute_query(req)
    assert res.is_valid is False
    assert res.error_type == "EmptyResultWarning"


class _ScriptedLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list] = []

    def chat(self, messages, options=None):
        self.calls.append(messages)
        text = self._responses.pop(0)
        return LLMGenerationResult(text=text, input_tokens=10, output_tokens=10, finish_reason="stop")


def test_b0_pipeline_e2e_recovers_from_all_null_aggregate_and_schema_hints(tmp_path: Path):
    """End-to-end B0Pipeline test verifying EmptyResultWarning retry and Schema Hint propagation."""
    biz = tmp_path / "in" / "biz_compat"
    biz.mkdir(parents=True)
    (biz / "don_hang.csv").write_text(
        "Mã đơn,Mã khách,Trạng thái,Thành tiền\n"
        "D1,K1,update,100000\n"
        "D2,K2,completed,250000\n",
        encoding="utf-8",
    )
    (biz / "README.md").write_text("# Biz Compat\n", encoding="utf-8")
    artifacts = prepare_business(biz, tmp_path / "out")
    context = json.loads((artifacts.bundle_dir / "business_context.json").read_text(encoding="utf-8"))
    table = next(t["name"] for t in context["schema_catalog"]["tables"] if t["name"].startswith("don_hang"))

    scripted = _ScriptedLLM(
        [
            # Q1 Attempt 0: Wrong WHERE filter produces 1 row with [None] -> EmptyResultWarning
            json.dumps(
                {
                    "status": "answerable",
                    "answer_type": "number",
                    "sql": f"SELECT SUM(thanh_tien) FROM {table} WHERE ma_khach = 'KH_SAI'",
                }
            ),
            # Q2 Attempt 0: Wrong column name with 'update' literal -> BinderError + Schema Hint
            json.dumps(
                {
                    "status": "answerable",
                    "answer_type": "number",
                    "sql": f"SELECT SUM(cot_sai) FROM {table} WHERE trang_thai = 'update'",
                }
            ),
            # Q1 Attempt 1: Repaired WHERE filter after EmptyResultWarning
            json.dumps(
                {
                    "status": "answerable",
                    "answer_type": "number",
                    "sql": f"SELECT SUM(thanh_tien) FROM {table} WHERE ma_khach = 'K1'",
                }
            ),
            # Q2 Attempt 1: Repaired column name using Schema Hint
            json.dumps(
                {
                    "status": "answerable",
                    "answer_type": "number",
                    "sql": f"SELECT SUM(thanh_tien) FROM {table} WHERE trang_thai = 'update'",
                }
            ),
        ]
    )

    pipeline = B0Pipeline(generator=Text2SQLGenerator(scripted))
    out_dir = tmp_path / "pipeline_out"
    questions = [
        {"id": "q1", "business_id": "biz_compat", "question": "Tổng tiền khách K1?", "as_of_date": "2026-04-01"},
        {"id": "q2", "business_id": "biz_compat", "question": "Tổng tiền đơn update?", "as_of_date": "2026-04-01"},
    ]

    outcomes = pipeline.run_questions(
        questions=questions,
        bundles={"biz_compat": artifacts.bundle_dir},
        output_dir=out_dir,
        batch_size=2,
    )
    assert len(outcomes) == 2
    assert outcomes[0].decision == Decision.ANSWER
    assert outcomes[0].retry_count == 1
    assert outcomes[0].final_answer.to_submission_dict() == {"id": "q1", "type": "number", "answer": 100000}

    assert outcomes[1].decision == Decision.ANSWER
    assert outcomes[1].retry_count == 1
    assert outcomes[1].final_answer.to_submission_dict() == {"id": "q2", "type": "number", "answer": 100000}

    # Verify repair prompt sent to LLM contained EmptyResultWarning and Schema Hint without __dm_ columns
    repair_Prompts = [call[-1].content for call in scripted.calls[2:]]
    assert any("EmptyResultWarning" in p and "all NULL values" in p for p in repair_Prompts)
    assert any("[Gợi ý Schema thực tế trong DB]:" in p and "thanh_tien" in p and "__dm_" not in p for p in repair_Prompts)
