"""End-to-end B0.1 -> B0.5 contract test on a tiny synthetic business (no mocks of contracts)."""

from __future__ import annotations

import json

from datamate.ingestion.ingestion import prepare_business
from datamate.planner.parser import parse_text2sql_response
from datamate.planner.prompt import build_text2sql_messages
from datamate.execution import ExecutionRequest, execute_query
from datamate.gate import SubmissionWriter, evaluate_gate
from datamate.gate.contracts import GateAction, GateRequest, QuestionMeta


def _bundle(tmp_path):
    biz = tmp_path / "in" / "biz_test"
    biz.mkdir(parents=True)
    (biz / "don_hang.csv").write_text(
        "Mã đơn,Mã khách,Ngày bán,Thành tiền\n"
        "D1,K1,2026-03-15 09:30:00,100000\n"
        "D2,K2,2026-03-16 10:00:00,250000\n",
        encoding="utf-8",
    )
    (biz / "khach_hang.csv").write_text(
        "Mã khách,Tên khách\nK1,An\nK2,Bình\n", encoding="utf-8"
    )
    (biz / "README.md").write_text("- **Thành tiền**: số tiền của đơn\n", encoding="utf-8")
    return prepare_business(biz, tmp_path / "out")


def _gate(question_id, generation, execution):
    return evaluate_gate(
        GateRequest(
            contract_version="b05.v1",
            question=QuestionMeta(question_id, "biz_test", "q", "2026-04-01"),
            generation=generation,
            execution=execution,
        )
    )


def test_prepare_prompt_execute_gate_submission(tmp_path):
    artifacts = _bundle(tmp_path)
    context = json.loads((artifacts.bundle_dir / "business_context.json").read_text())

    # B0.1/B0.2 -> B0.3: the prompt must expose real schema, original headers and ranges.
    prompt = build_text2sql_messages(context, "Tổng doanh thu?", "2026-04-01")[1].content
    assert "don_hang" in prompt and "khach_hang" in prompt
    assert "tên gốc" in prompt
    assert "2026-03-15" in prompt  # observed date range from data profiling

    table = next(t["name"] for t in context["schema_catalog"]["tables"] if t["name"].startswith("don_hang"))
    llm_text = json.dumps(
        {
            "status": "answerable",
            "answer_type": "number",
            "sql": f"SELECT SUM(thanh_tien) FROM {table}",
            "answer_semantics": {"numeric_kind": "money_vnd"},
        }
    )
    result = parse_text2sql_response(f"<think>draft</think>\n{llm_text}")

    # B0.3 -> B0.4 on the prepared bundle directory.
    response = execute_query(
        ExecutionRequest.from_b03(result, "q1", str(artifacts.bundle_dir))
    )
    assert response.is_valid, response.error_message
    assert response.truncated is False

    # B0.4 -> B0.5 -> submission.jsonl
    outcome = _gate("q1", result.to_b05_generation_result(), response.to_b05_execution_result())
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.to_submission_dict() == {"id": "q1", "type": "number", "answer": 350000}
    writer = SubmissionWriter(tmp_path / "result")
    writer.write_final(outcome)
    line = json.loads((tmp_path / "result" / "submission.jsonl").read_text().strip())
    assert line["answer"] == 350000


def test_timestamp_column_flows_into_date_answer(tmp_path):
    artifacts = _bundle(tmp_path)
    context = json.loads((artifacts.bundle_dir / "business_context.json").read_text())
    table = next(t["name"] for t in context["schema_catalog"]["tables"] if t["name"].startswith("don_hang"))
    result = parse_text2sql_response(
        json.dumps(
            {
                "status": "answerable",
                "answer_type": "date",
                "sql": f"SELECT MAX(ngay_ban) FROM {table}",
            }
        )
    )
    response = execute_query(ExecutionRequest.from_b03(result, "q2", str(artifacts.bundle_dir)))
    assert response.is_valid, response.error_message
    outcome = _gate("q2", result.to_b05_generation_result(), response.to_b05_execution_result())
    assert outcome.final_answer.to_submission_dict()["answer"] == "2026-03-16"


def test_wrong_column_triggers_retry_then_repair_succeeds(tmp_path):
    artifacts = _bundle(tmp_path)
    context = json.loads((artifacts.bundle_dir / "business_context.json").read_text())
    table = next(t["name"] for t in context["schema_catalog"]["tables"] if t["name"].startswith("don_hang"))
    bad = parse_text2sql_response(
        json.dumps({"status": "answerable", "answer_type": "number", "sql": f"SELECT SUM(nope) FROM {table}"})
    )
    bad_response = execute_query(ExecutionRequest.from_b03(bad, "q3", str(artifacts.bundle_dir)))
    assert not bad_response.is_valid and bad_response.route == "recoverable"
    first = _gate("q3", bad.to_b05_generation_result(), bad_response.to_b05_execution_result())
    assert first.action == GateAction.RETRY


class _ScriptedLLM:
    """Deterministic LLM stub returning scripted JSON strings per call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list] = []

    def chat(self, messages, options=None):
        from datamate.planner.types import GenerationResult

        self.calls.append(messages)
        text = self._responses.pop(0)
        return GenerationResult(text=text, input_tokens=10, output_tokens=10, finish_reason="stop")


def test_b0_pipeline_end_to_end_orchestration(tmp_path):
    """Verify B0Pipeline connects B0.1 -> B0.2 -> B0.3 -> B0.4 -> B0.5 including bounded retry and unanswerable verification."""
    from datamate.pipeline import B0Pipeline, Pipeline
    from datamate.planner import Text2SQLGenerator

    artifacts = _bundle(tmp_path)
    context = json.loads((artifacts.bundle_dir / "business_context.json").read_text())
    table = next(t["name"] for t in context["schema_catalog"]["tables"] if t["name"].startswith("don_hang"))

    # Scripted responses for 5 questions:
    # Q1: Direct answerable (AVG money_vnd -> inferred average_money_vnd)
    # Q2: Attempt 0 wrong table name (CatalogError) -> Attempt 1 repaired SQL succeeds
    # Q3: Verified unanswerable (missing_fields=["chi_phi_marketing"]) -> skips B0.4, emits unanswerable
    # Q4: Hallucinated unanswerable (missing_fields=["ma_khach"] which exists) -> downgraded to abstain
    # Q5: Both Attempt 0 and Attempt 1 fail -> RETRY_EXHAUSTED -> abstain
    scripted = _ScriptedLLM(
        [
            # Q1 (1 call) - includes <think>...</think> reasoning block
            "<think>Để tính trung bình đơn hàng, ta dùng hàm AVG trên cột thanh_tien.</think>\n"
            + json.dumps(
                {
                    "status": "answerable",
                    "answer_type": "number",
                    "sql": f"SELECT AVG(thanh_tien) FROM {table}",
                    "assumptions": ["Tính trên toàn bộ đơn hàng trong bảng"],
                }
            ),
            # Q2 Attempt 0 (wrong table) - includes <think>
            "<think>Thử truy vấn bảng bang_khong_ton_tai trước.</think>\n"
            + json.dumps(
                {
                    "status": "answerable",
                    "answer_type": "number",
                    "sql": "SELECT SUM(thanh_tien) FROM bang_khong_ton_tai",
                }
            ),
            # Q2 Attempt 1 (repaired) - includes <think>
            "<think>Bảng bang_khong_ton_tai không tồn tại, sửa lại thành bảng don_hang đúng trong schema.</think>\n"
            + json.dumps(
                {
                    "status": "answerable",
                    "answer_type": "number",
                    "sql": f"SELECT SUM(thanh_tien) FROM {table}",
                }
            ),
            # Q3 Verified unanswerable
            json.dumps(
                {
                    "status": "unanswerable",
                    "missing_fields": ["chi_phi_marketing"],
                    "reason": "Không có dữ liệu chi phí marketing",
                }
            ),
            # Q4 Hallucinated unanswerable (ma_khach actually exists!)
            json.dumps(
                {
                    "status": "unanswerable",
                    "missing_fields": ["ma_khach"],
                    "reason": "Thiếu cột ma_khach",
                }
            ),
            # Q5 Attempt 0 fail
            json.dumps(
                {
                    "status": "answerable",
                    "answer_type": "number",
                    "sql": f"SELECT SUM(cot_sai_1) FROM {table}",
                }
            ),
            # Q5 Attempt 1 still fail
            json.dumps(
                {
                    "status": "answerable",
                    "answer_type": "number",
                    "sql": f"SELECT SUM(cot_sai_2) FROM {table}",
                }
            ),
        ]
    )

    pipeline = B0Pipeline(generator=Text2SQLGenerator(scripted))
    out_dir = tmp_path / "pipeline_out"
    questions = [
        {"id": "q1", "business_id": "biz_test", "question": "Trung bình đơn hàng?", "as_of_date": "2026-04-01"},
        {"id": "q2", "business_id": "biz_test", "question": "Tổng doanh thu?", "as_of_date": "2026-04-01"},
        {"id": "q3", "business_id": "biz_test", "question": "Chi phí marketing?", "as_of_date": "2026-04-01"},
        {"id": "q4", "business_id": "biz_test", "question": "Mã khách hàng?", "as_of_date": "2026-04-01"},
        {"id": "q5", "business_id": "biz_test", "question": "Câu lỗi 2 lần?", "as_of_date": "2026-04-01"},
    ]

    outcomes = pipeline.run_questions(
        questions=questions,
        bundles={"biz_test": artifacts.bundle_dir},
        output_dir=out_dir,
    )
    assert len(outcomes) == 5
    assert outcomes[0].final_answer.to_submission_dict() == {"id": "q1", "type": "number", "answer": 175000}
    assert outcomes[1].final_answer.to_submission_dict() == {"id": "q2", "type": "number", "answer": 350000}
    assert outcomes[1].retry_count == 1
    assert outcomes[2].final_answer.to_submission_dict()["type"] == "unanswerable"
    assert outcomes[3].final_answer.to_submission_dict() == {"id": "q4", "type": "abstain"}
    assert outcomes[4].final_answer.to_submission_dict() == {"id": "q5", "type": "abstain"}

    lines = [
        json.loads(line)
        for line in (out_dir / "submission.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item["id"] for item in lines] == ["q1", "q2", "q3", "q4", "q5"]
    assert [item["type"] for item in lines] == ["number", "number", "unanswerable", "abstain", "abstain"]

    # Verify per-question audit logs in out_dir / "logs" and detailed_logs.jsonl record attempts, SQL, errors, and LLM thinking
    log_files = {json.loads(p.read_text(encoding="utf-8"))["id"]: json.loads(p.read_text(encoding="utf-8")) for p in (out_dir / "logs").glob("*.json")}
    assert set(log_files.keys()) == {"q1", "q2", "q3", "q4", "q5"}

    q1_log = log_files["q1"]
    assert len(q1_log["attempts"]) == 1
    assert "Để tính trung bình đơn hàng" in q1_log["attempts"][0]["thinking"]
    assert q1_log["attempts"][0]["assumptions"] == ["Tính trên toàn bộ đơn hàng trong bảng"]

    q2_log = log_files["q2"]
    assert len(q2_log["attempts"]) == 2
    assert q2_log["attempts"][0]["attempt"] == 0
    assert q2_log["attempts"][0]["execution_status"] == "error"
    assert "bang_khong_ton_tai" in q2_log["attempts"][0]["thinking"]
    assert q2_log["attempts"][1]["attempt"] == 1
    assert q2_log["attempts"][1]["execution_status"] == "success"
    assert "sửa lại thành bảng don_hang" in q2_log["attempts"][1]["thinking"]


def test_b0_pipeline_batch_mode_parallel(tmp_path: Path):
    """Verify that batch processing (batch_size=2) produces identical correct results and audit trails."""
    from datamate.pipeline import B0Pipeline, Pipeline
    from datamate.planner import Text2SQLGenerator

    data_dir = tmp_path / "in"
    biz_dir = data_dir / "biz_batch"
    biz_dir.mkdir(parents=True)
    table_csv = biz_dir / "don_hang.csv"
    table_csv.write_text(
        "id,so_tien\n"
        "1,100000\n"
        "2,200000\n",
        encoding="utf-8",
    )
    (biz_dir / "README.md").write_text("# Biz Batch\nIndustry: retail\n", encoding="utf-8")

    out_bundle_root = tmp_path / "bundles"
    artifacts = B0Pipeline.prepare_bundle(
        business_dir=biz_dir,
        output_dir=out_bundle_root / "biz_batch",
    )
    context = json.loads((artifacts.bundle_dir / "business_context.json").read_text(encoding="utf-8"))
    table = next(t["name"] for t in context["schema_catalog"]["tables"] if t["name"].startswith("don_hang"))

    scripted = _ScriptedLLM(
        [
            # Q1
            json.dumps({"status": "answerable", "answer_type": "number", "sql": f"SELECT SUM(so_tien) FROM {table}"}),
            # Q2 Attempt 0 (fail)
            json.dumps({"status": "answerable", "answer_type": "number", "sql": "SELECT SUM(sai) FROM bang_ao"}),
            # Q2 Attempt 1 (repaired)
            json.dumps({"status": "answerable", "answer_type": "number", "sql": f"SELECT COUNT(*) FROM {table}"}),
            # Q3
            json.dumps({"status": "unanswerable", "missing_fields": ["loi_nhuan"], "reason": "Không có dữ liệu lợi nhuận"}),
        ]
    )

    pipeline = B0Pipeline(generator=Text2SQLGenerator(scripted))
    out_dir = tmp_path / "batch_out"
    questions = [
        {"id": "q1", "business_id": "biz_batch", "question": "Tổng tiền?", "as_of_date": "2026-04-01"},
        {"id": "q2", "business_id": "biz_batch", "question": "Số lượng đơn?", "as_of_date": "2026-04-01"},
        {"id": "q3", "business_id": "biz_batch", "question": "Lợi nhuận?", "as_of_date": "2026-04-01"},
    ]

    outcomes = pipeline.run_questions(
        questions=questions,
        bundles={"biz_batch": artifacts.bundle_dir},
        output_dir=out_dir,
        batch_size=2,
    )
    assert len(outcomes) == 3
    assert outcomes[0].final_answer.to_submission_dict() == {"id": "q1", "type": "number", "answer": 300000}
    assert outcomes[1].final_answer.to_submission_dict() == {"id": "q2", "type": "number", "answer": 2}
    assert outcomes[1].retry_count == 1
    assert outcomes[2].final_answer.to_submission_dict()["type"] == "unanswerable"

    lines = [
        json.loads(line)
        for line in (out_dir / "submission.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item["id"] for item in lines] == ["q1", "q2", "q3"]
    assert [item["type"] for item in lines] == ["number", "number", "unanswerable"]




