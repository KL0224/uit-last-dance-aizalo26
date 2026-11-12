"""Regression tests cho các lỗi trong docs/review/DATAMATE_PIPELINE_LOGIC_AND_RUNTIME_REVIEW.md."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import duckdb
import pytest

import datamate.pipeline as pipeline_mod
from datamate.gate.audit import AuditLogger
from datamate.gate.contracts import GateAction, QuestionMeta
from datamate.gate.errors import ErrorCode
from datamate.pipeline import B0Pipeline
from datamate.planner.errors import Text2SQLParseError
from datamate.planner.parser import (
    extract_json_contract_dict,
    infer_answer_type_from_sql,
    normalize_answer_type,
    parse_text2sql_response,
)
from datamate.planner.types import Text2SQLResult

ROOT = Path(__file__).resolve().parent.parent


# ---------------- P1: answer_type theo SELECT ngoài cùng ----------------
@pytest.mark.parametrize(
    "sql,declared,expected",
    [
        ("WITH top AS (SELECT ma_kh FROM t ORDER BY dt DESC LIMIT 5) SELECT SUM(dt) FROM top", "number", "number"),
        ("SELECT SUM(x) FROM (SELECT x FROM t ORDER BY y LIMIT 3) s", "number", "number"),
        ("SELECT ma_kh FROM t ORDER BY dt DESC LIMIT 5", "string", "list"),
        ("SELECT MAX(ngay_ban) FROM t", "date", "date"),
        ("SELECT EXTRACT(YEAR FROM ngay) AS y, SUM(dt) FROM t GROUP BY 1", "table", "table"),
    ],
)
def test_p1_answer_type_uses_outer_select(sql, declared, expected):
    assert normalize_answer_type(declared, sql) == expected


def test_p1_infer_handles_cte_and_minmax_date():
    assert infer_answer_type_from_sql("WITH a AS (SELECT k, v FROM t) SELECT SUM(v) FROM a") == "number"
    assert infer_answer_type_from_sql("SELECT MAX(ngay_ban) FROM t") == "date"
    assert infer_answer_type_from_sql("SELECT EXTRACT(YEAR FROM ngay) AS y, SUM(dt) FROM t GROUP BY 1") == "table"


# ---------------- L3: percent chỉ khi SQL là tỷ lệ ----------------
def test_l3_count_question_with_percent_sign_stays_number():
    assert normalize_answer_type("number", "SELECT COUNT(*) FROM t WHERE giam_gia>10", "Có bao nhiêu đơn giảm giá trên 10%?") == "number"


def test_l3_ratio_question_still_percent():
    assert normalize_answer_type("number", "SELECT ROUND(SUM(a)*100.0/SUM(b),2) FROM t", "Tỷ lệ hoàn trả là bao nhiêu?") == "percent"


# ---------------- P2: không dùng SQL nháp trong thinking ----------------
def test_p2_truncated_think_draft_is_rejected():
    raw = "<think>Draft:\n```sql\nSELECT COUNT(*) FROM orders\n```\nlet me reconsider..."
    with pytest.raises(Text2SQLParseError):
        parse_text2sql_response(raw, "Có bao nhiêu đơn?")


def test_p2_closed_think_json_in_thinking_not_used_as_answer():
    raw = '<think>draft {"status":"answerable","sql":"SELECT 1"}</think>\nKhông thể trả lời.'
    res = parse_text2sql_response(raw)
    assert res.status == "unanswerable"


def test_p2_closed_think_final_json_still_parsed():
    raw = '<think>reason</think>\n```json\n{"status":"answerable","answer_type":"number","sql":"SELECT COUNT(*) FROM t"}\n```'
    res = parse_text2sql_response(raw)
    assert res.status == "answerable" and res.sql == "SELECT COUNT(*) FROM t"


# ---------------- P3: quét JSON tuyến tính ----------------
def test_p3_brace_scan_is_fast_on_long_output():
    body = "so {a} then {b} " * 2000 + " no json here"
    start = time.perf_counter()
    assert extract_json_contract_dict(body) is None
    assert time.perf_counter() - start < 1.0


def test_p3_trailing_comma_json_is_recovered():
    obj = extract_json_contract_dict('text {"status": "answerable", "sql": "SELECT 1",} tail')
    assert obj and obj["sql"] == "SELECT 1"


# ---------------- P4 + L4-L7: pipeline ----------------
class _FakeGenerator:
    def __init__(self, batch_len=None):
        self.batch_len = batch_len

    def _res(self):
        return Text2SQLResult(status="answerable", answer_type="number", sql="SELECT 1", tables_used=())

    def generate(self, **kwargs):
        return self._res()

    repair = generate

    def generate_batch(self, items, options=None):
        n = len(items) if self.batch_len is None else self.batch_len
        return [self._res() for _ in range(n)]

    def repair_batch(self, items, options=None):
        return [self._res() for _ in items]


def _write_valid_context(bundle, tables=(), business_id="b"):
    payload = {
        "contract_version": "1.0",
        "business_id": business_id,
        "schema_catalog": {
            "tables": list(tables),
            "key_candidates": [],
            "join_graph": [],
            "warnings": [],
        },
        "rule_catalog": {
            "rules": [],
            "warnings": [],
            "business_id": business_id,
        },
        "business_metadata": {},
    }
    (bundle / "business_context.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_p4_internal_error_becomes_abstain(tmp_path, monkeypatch):
    def boom(_req):
        raise RuntimeError("executor exploded")

    monkeypatch.setattr(pipeline_mod, "execute_query", boom)
    outcome = B0Pipeline(_FakeGenerator()).answer_question(
        {"id": "q1", "business_id": "b", "question": "?", "as_of_date": "2025-01-01"},
        tmp_path,
        context={},
    )
    assert outcome.action == GateAction.FINAL
    assert outcome.final_answer.type == "abstain"
    assert outcome.reason_code == ErrorCode.UNKNOWN_ERROR


def test_p4_batch_short_result_does_not_crash(tmp_path, monkeypatch):
    def boom(_req):
        raise RuntimeError("x")

    monkeypatch.setattr(pipeline_mod, "execute_query", boom)
    questions = [
        QuestionMeta(id=f"q{i}", business_id="b", question="?", as_of_date="2025-01-01") for i in range(3)
    ]
    _write_valid_context(tmp_path)
    pipe = B0Pipeline(_FakeGenerator(batch_len=1))
    outcomes = pipe.run_questions(questions, {"b": tmp_path}, tmp_path / "out", batch_size=3)
    assert len(outcomes) == 3 and all(o is not None for o in outcomes)
    lines = (tmp_path / "out" / "submission.jsonl").read_text(encoding="utf-8").splitlines()
    assert {json.loads(x)["id"] for x in lines} == {"q0", "q1", "q2"}
    manifest = json.loads((tmp_path / "out" / "submission.manifest.json").read_text(encoding="utf-8"))
    assert manifest["record_count"] == 3


def test_l6_stale_detailed_log_is_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "execute_query", lambda _r: (_ for _ in ()).throw(RuntimeError("x")))
    out = tmp_path / "out"
    out.mkdir()
    _write_valid_context(tmp_path)
    (out / "detailed_logs.jsonl").write_text('{"id":"stale"}\n', encoding="utf-8")
    q = QuestionMeta(id="q1", business_id="b", question="?", as_of_date="2025-01-01")
    B0Pipeline(_FakeGenerator()).run_questions([q], {"b": tmp_path}, out)
    ids = [json.loads(x)["id"] for x in (out / "detailed_logs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert ids == ["q1"]


def test_l7_audit_logger_public_history(tmp_path):
    log = AuditLogger(tmp_path)
    log.record_attempt("q", 0, "SELECT 1", "ok")
    hist = log.get_history("q")
    assert hist[0]["attempt"] == 0 and log.get_history("missing") == []


def _make_bundle(tmp_path, tables_sql):
    con = duckdb.connect(str(tmp_path / "data.duckdb"))
    for stmt in tables_sql:
        con.execute(stmt)
    tables = []
    for (table_name,) in con.execute("SHOW TABLES").fetchall():
        quoted = '"' + table_name.replace('"', '""') + '"'
        columns = [
            {"name": name, "data_type": data_type}
            for name, data_type, *_ in con.execute(f"DESCRIBE {quoted}").fetchall()
        ]
        tables.append({"name": table_name, "columns": columns})
    con.close()
    _write_valid_context(tmp_path, tables)
    return tmp_path


def test_l1_load_context_handles_unusual_table_names(tmp_path):
    bundle = _make_bundle(tmp_path, [
        'CREATE TABLE "don hang" (id INT, loai VARCHAR)',
        "INSERT INTO \"don hang\" VALUES (1,'a'),(2,'b')",
    ])
    ctx = B0Pipeline.load_context(bundle)
    assert ctx["categorical_samples"]["don hang"]["loai"]


def test_l2_discovered_joins_are_candidates_without_cartesian_blowup(tmp_path):
    bundle = _make_bundle(tmp_path, [
        "CREATE TABLE a AS SELECT 1 AS ma_kh FROM range(3000)",  # 3000 hàng trùng giá trị
        "CREATE TABLE b AS SELECT 1 AS ma_kh FROM range(3000)",
    ])
    start = time.perf_counter()
    ctx = B0Pipeline.load_context(bundle)
    assert time.perf_counter() - start < 5.0  # self-join COUNT(*) cũ sẽ tạo 9 triệu hàng
    edges = ctx["schema_catalog"]["join_graph"]
    assert edges and all(e["status"] == "candidate" and e["cardinality"] == "unknown" for e in edges)


# ---------------- D1: Dockerfile ----------------
def test_d1_dockerfile_version_specs_are_quoted():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert not re.search(r"(?<![\"'])\b\w+>=[\d.]+(?![\"'])", text.split("pip install", 1)[1].split("\n\n", 1)[0])
