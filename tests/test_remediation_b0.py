"""Regression tests for the B0 remediation plan (docs/plan/B0_REMEDIATION_PLAN.md).

Each test reproduces a defect from docs/review/B0_COMPREHENSIVE_CODE_REVIEW.md
and must fail before the matching fix.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

import duckdb
import pytest

from datamate.b0.b01.contracts import (
    ColumnMetadata,
    JoinEdge,
    KeyCandidate,
    SchemaCatalog,
    TableMetadata,
)
from datamate.b0.b01.ingestion.normalization import parse_date
from datamate.b0.b02.rule_compiler import BusinessRuleCompiler
from datamate.b0.b03.parser import (
    extract_tables_from_sql,
    infer_answer_type_from_sql,
    parse_text2sql_response,
)
from datamate.b0.b03.prompt import format_context_for_prompt
from datamate.b0.b03.types import Text2SQLResult
from datamate.b0.b04 import ExecutionRequest, execute_query, normalize_value
from datamate.b0.b04.sanitizer import validate_read_only_sql
from datamate.b0.b04.schemas import SecurityViolation
from datamate.b0.b05.formatter import format_answer, format_date


# --------------------------------------------------------------- B0.1 BUG-03
@pytest.mark.parametrize(
    "text,expected",
    [
        ("2026-03-15 9:30", datetime.datetime(2026, 3, 15, 9, 30)),
        ("2026-03-15 09:30", datetime.datetime(2026, 3, 15, 9, 30)),
        ("15-03-2026 09:30", datetime.datetime(2026, 3, 15, 9, 30)),
        ("2026/03/15", datetime.date(2026, 3, 15)),
        ("2026/03/15 10:20:30", datetime.datetime(2026, 3, 15, 10, 20, 30)),
    ],
)
def test_parse_date_extra_formats(text, expected):
    assert parse_date(text, "1900", None) == expected


# --------------------------------------------------------------- B0.2 BUG-07
def test_rule_links_original_vietnamese_column_name(tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text("- Doanh thu = tổng Thành tiền của các dòng hàng\n", encoding="utf-8")
    schema = SchemaCatalog(
        tables=(
            TableMetadata(
                "ban_hang",
                (ColumnMetadata("thanh_tien", "DECIMAL(38,0)", provenance="Thành tiền"),),
            ),
        )
    )
    catalog = BusinessRuleCompiler().ingest_documents([doc], None, schema)
    assert "thanh_tien" in catalog.rules[0].required_fields


# ------------------------------------------------------------ B0.3 BUG-08/09/10
def _context_dict():
    return {
        "schema_catalog": {
            "tables": [
                {
                    "name": "don_hang",
                    "columns": [
                        {
                            "name": "ma_khach",
                            "data_type": "VARCHAR",
                            "nullable": False,
                            "provenance": "Mã khách",
                        },
                        {"name": "ngay_ban", "data_type": "DATE", "nullable": True},
                    ],
                    "primary_key_candidates": [],
                },
                {"name": "khach_hang", "columns": [], "primary_key_candidates": []},
            ],
            "key_candidates": [
                {
                    "table": "khach_hang",
                    "columns": ["ma_khach"],
                    "key_type": "primary",
                    "status": "candidate",
                }
            ],
            "join_graph": [
                {
                    "left_table": "don_hang",
                    "left_column": "ma_khach",
                    "right_table": "khach_hang",
                    "right_column": "ma_khach",
                    "cardinality": "many_to_one",
                    "status": "validated",
                    "additional_key_pairs": [["chi_nhanh", "chi_nhanh"]],
                }
            ],
        },
        "rule_catalog": {"rules": []},
        "data_profiling": {
            "don_hang": {
                "columns": {
                    "ngay_ban": {"observed_min": "2026-01-01", "observed_max": "2026-03-31"}
                }
            }
        },
    }


def test_prompt_reads_real_b01_contract_keys():
    text = format_context_for_prompt(_context_dict())
    assert "QUAN HỆ JOIN" in text
    assert "`don_hang`.ma_khach = `khach_hang`.ma_khach" in text
    assert "chi_nhanh" in text  # composite key pair preserved
    assert "[Khóa chính: ma_khach]" in text
    assert "Mã khách" in text  # original Vietnamese header
    assert "2026-01-01" in text and "2026-03-31" in text


def test_prompt_keeps_legacy_keys():
    data = {
        "schema_catalog": {
            "tables": [{"name": "t", "columns": [], "primary_key_candidates": ["id"]}],
            "join_edges": [
                {
                    "left_table": "a",
                    "left_column": "x",
                    "right_table": "b",
                    "right_column": "y",
                    "cardinality": "one_to_one",
                }
            ],
        }
    }
    text = format_context_for_prompt(data)
    assert "[Khóa chính: id]" in text
    assert "`a`.x = `b`.y" in text


@pytest.mark.parametrize(
    "raw_type,expected",
    [("integer", "number"), ("money", "number"), ("text", "string"), ("timestamp", "date")],
)
def test_parser_normalizes_answer_type_aliases(raw_type, expected):
    raw = json.dumps({"status": "answerable", "answer_type": raw_type, "sql": "SELECT 1"})
    assert parse_text2sql_response(raw).answer_type == expected


def test_parser_never_returns_generic_answer_type():
    raw = json.dumps({"status": "answerable", "sql": "SELECT name FROM t LIMIT 1"})
    assert parse_text2sql_response(raw).answer_type != "generic"
    result = Text2SQLResult(status="answerable", answer_type=None, sql="SELECT COUNT(*) FROM t")
    assert result.to_b05_generation_result().answer_type == "number"


def test_to_b05_carries_answer_semantics():
    raw = json.dumps(
        {
            "status": "answerable",
            "answer_type": "number",
            "sql": "SELECT AVG(thanh_tien) FROM t",
            "answer_semantics": {"numeric_kind": "money_vnd"},
        }
    )
    gen = parse_text2sql_response(raw).to_b05_generation_result()
    assert gen.answer_semantics.numeric_kind == "money_vnd"
    assert format_answer("number", Decimal("125000.67"), {"numeric_kind": "money_vnd"}) == 125001


def test_count_semantics_inferred_from_sql():
    result = Text2SQLResult(status="answerable", answer_type="number", sql="SELECT COUNT(*) FROM t")
    assert result.to_b05_generation_result().answer_semantics.numeric_kind == "count"


# --------------------------------------------------------------- B0.3 BUG-11
def test_extract_tables_ignores_extract_from_and_cte():
    sql = (
        "WITH c AS (SELECT EXTRACT(YEAR FROM order_date) y FROM orders) "
        "SELECT * FROM c JOIN customers ON 1=1"
    )
    assert extract_tables_from_sql(sql) == ("orders", "customers")


def test_extract_tables_fallback_on_unparseable_sql():
    assert extract_tables_from_sql("SELECT EXTRACT(YEAR FROM d) FROM orders WHERE ((") == (
        "orders",
    )


# --------------------------------------------------------------- B0.3 BUG-12
def test_parser_ignores_think_block():
    raw = (
        "<think>draft:\n```sql\nSELECT wrong FROM nowhere\n```\n</think>\n"
        '```json\n{"status":"answerable","answer_type":"number","sql":"SELECT COUNT(*) FROM orders"}\n```'
    )
    assert parse_text2sql_response(raw).sql == "SELECT COUNT(*) FROM orders"


def test_parser_json_with_backticks_inside_string():
    raw = json.dumps(
        {
            "status": "answerable",
            "answer_type": "number",
            "sql": "SELECT 1",
            "assumptions": ["dùng ```cột``` ngay_ban"],
        }
    )
    result = parse_text2sql_response(raw)
    assert result.sql == "SELECT 1"
    assert result.assumptions == ("dùng ```cột``` ngay_ban",)


# --------------------------------------------------------------- B0.3 BUG-20
def test_infer_answer_type_lowercase_from():
    assert infer_answer_type_from_sql("select name from t limit 1") == "string"


# --------------------------------------------------------------- B0.4 BUG-15
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM t WHERE note LIKE '%update%'",
        "SELECT * FROM t WHERE status = 'delete'",
        "SELECT 1 -- do not drop null rows",
        "SELECT 1 /* create view */",
        'SELECT "load" FROM t',
    ],
)
def test_sanitizer_allows_keywords_in_literals_and_comments(sql):
    assert validate_read_only_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "TRUNCATE TABLE t",
        "SHOW TABLES",
        "SELECT 1; EXPORT DATABASE '/tmp/x'",
        "DESCRIBE t",
        "CALL pragma_version()",
    ],
)
def test_sanitizer_blocks_non_select_roots(sql):
    with pytest.raises(SecurityViolation):
        validate_read_only_sql(sql)


def test_sanitizer_allows_with_and_union():
    assert validate_read_only_sql("WITH a AS (SELECT 1 x) SELECT x FROM a UNION SELECT 2")


# --------------------------------------------------------------- B0.4 BUG-14
def test_normalize_value_edge_types():
    assert normalize_value(Decimal("Infinity")) is None
    assert normalize_value(Decimal("-Infinity")) is None
    assert normalize_value(Decimal("NaN")) is None
    assert normalize_value(datetime.time(14, 30, 0)) == "14:30:00"
    assert normalize_value(True) is True
    assert normalize_value(Decimal("12.50")) == 12.5
    assert normalize_value(Decimal("12")) == 12


# --------------------------------------------------------------- B0.4 BUG-17
def _db(tmp_path, rows=15):
    path = tmp_path / "t.duckdb"
    con = duckdb.connect(str(path))
    con.execute(f"CREATE TABLE t AS SELECT range AS n FROM range({rows})")
    con.close()
    return str(path)


def test_truncated_flag_when_exceeding_max_rows(tmp_path):
    res = execute_query(
        ExecutionRequest(question_id="q", db_path=_db(tmp_path), sql_query="SELECT n FROM t", max_rows=10)
    )
    assert res.is_valid and res.row_count == 10
    assert res.truncated is True
    assert res.to_b05_execution_result().truncated is True


def test_not_truncated_when_exactly_max_rows(tmp_path):
    res = execute_query(
        ExecutionRequest(question_id="q", db_path=_db(tmp_path, 10), sql_query="SELECT n FROM t", max_rows=10)
    )
    assert res.truncated is False


# --------------------------------------------------------------- B0.4 BUG-16
def test_directory_loads_bundle_database(tmp_path):
    _db(tmp_path)  # creates t.duckdb, rename to the bundle convention
    (tmp_path / "t.duckdb").rename(tmp_path / "data.duckdb")
    res = execute_query(
        ExecutionRequest(question_id="q", db_path=str(tmp_path), sql_query="SELECT COUNT(*) AS c FROM t")
    )
    assert res.is_valid and res.rows == [{"c": 15}]


def test_directory_duplicate_stems_not_lost(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "orders.csv").write_text("x\n1\n2\n")
    (tmp_path / "b" / "orders.csv").write_text("x\n3\n")
    res = execute_query(
        ExecutionRequest(
            question_id="q",
            db_path=str(tmp_path),
            sql_query="SELECT (SELECT COUNT(*) FROM orders) + (SELECT COUNT(*) FROM orders_2) AS c",
        )
    )
    assert res.is_valid and res.rows == [{"c": 3}]


def test_directory_xlsx_all_sheets(tmp_path):
    pd = pytest.importorskip("pandas")
    path = tmp_path / "book.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="S1", index=False)
        pd.DataFrame({"b": [2, 3]}).to_excel(writer, sheet_name="S2", index=False)
    res = execute_query(
        ExecutionRequest(
            question_id="q",
            db_path=str(tmp_path),
            sql_query="SELECT (SELECT COUNT(*) FROM book_S1) + (SELECT COUNT(*) FROM book_S2) AS c",
        )
    )
    assert res.is_valid and res.rows == [{"c": 3}]


# --------------------------------------------------------------- B0.5 BUG-13/19
@pytest.mark.parametrize(
    "value", ["2026-03-15T00:00:00", "2026-03-15 10:20:30", "2026-03-15T10:20:30+07:00"]
)
def test_format_date_accepts_iso_timestamps(value):
    assert format_date(value, {}) == "2026-03-15"


def test_format_date_still_rejects_garbage():
    from datamate.b0.b05.errors import FormattingError

    with pytest.raises(FormattingError):
        format_date("15/03/2026", {})


def test_format_list_and_table_normalize_scalars():
    out = format_answer("list", [Decimal("100.00"), datetime.date(2026, 3, 15)], {})
    assert out == [100, "2026-03-15"]
    json.dumps(out)
    table = format_answer(
        "table", {"columns": ["a", "b"], "rows": [[Decimal("1.50"), datetime.date(2026, 1, 2)]]}, {}
    )
    assert table["rows"] == [[1.5, "2026-01-02"]]
    json.dumps(table)


# --------------------------------------------------------------- E2E-05 & E2E-08
def test_e2e05_full_table_join_discovered_when_first_5_rows_disjoint(tmp_path):
    """When first 5 rows have 0 overlap on ma_khach but full table has >=80% overlap, join is discovered."""
    from datamate.b0.b01.ingestion import prepare_business

    biz = tmp_path / "in" / "biz_join"
    biz.mkdir(parents=True)
    # 5 rows with K100..K104 (not in khach_hang), followed by 20 rows with K1..K20 (in khach_hang) -> 20/25 = 80%
    don_rows = ["Mã đơn,Mã khách,Thành tiền"]
    for i in range(5):
        don_rows.append(f"D_MISS_{i},K_MISS_{i},100")
    for i in range(1, 21):
        don_rows.append(f"D_{i},K_{i},200")
    (biz / "don_hang.csv").write_text("\n".join(don_rows) + "\n", encoding="utf-8")

    kh_rows = ["Mã khách,Tên khách"] + [f"K_{i},Khách {i}" for i in range(1, 21)]
    (biz / "khach_hang.csv").write_text("\n".join(kh_rows) + "\n", encoding="utf-8")
    (biz / "README.md").write_text("# Biz join test\n", encoding="utf-8")

    artifacts = prepare_business(biz, tmp_path / "out")
    ctx = json.loads((artifacts.bundle_dir / "business_context.json").read_text(encoding="utf-8"))
    join_graph = ctx["schema_catalog"]["join_graph"]
    assert len(join_graph) == 1
    assert join_graph[0]["left_column"] == "ma_khach"
    assert join_graph[0]["right_column"] == "ma_khach"


def test_e2e08_synthetic_header_column_1_not_dropped_as_repeated_header(tmp_path):
    from datamate.b0.b01.ingestion.readers import CSVReader

    csv_file = tmp_path / "single.csv"
    csv_file.write_text(",b\ncolumn_1,b\nreal_value,other\n", encoding="utf-8")
    reader = CSVReader()
    sources = reader.discover(csv_file, "single.csv", {"single.csv": {"delimiter": ","}})
    rows = list(reader.rows(sources[0]))
    assert [r.values[0] for r in rows] == ["column_1", "real_value"]


# --------------------------------------------------------------- E2E-06
def test_e2e06_prompt_filters_other_industries_and_lower_precedence_rules():
    ctx = {
        "schema_catalog": {"tables": []},
        "business_metadata": {"industry": "Nhà thuốc"},
        "rule_catalog": {
            "rules": [
                {
                    "rule_id": "r_default",
                    "text": "Doanh thu | Công thức mặc định",
                    "scope": "split_default",
                    "precedence": 100,
                    "status": "descriptive",
                    "topic": "Doanh thu",
                    "industry": None,
                },
                {
                    "rule_id": "r_biz",
                    "text": "Doanh thu | Công thức riêng của doanh nghiệp",
                    "scope": "business",
                    "precedence": 300,
                    "status": "descriptive",
                    "topic": "Doanh thu",
                    "industry": None,
                },
                {
                    "rule_id": "r_pharma",
                    "text": "Hạn dùng | Quy tắc ngành Nhà thuốc",
                    "scope": "industry",
                    "precedence": 200,
                    "status": "descriptive",
                    "topic": "Hạn dùng",
                    "industry": "Nhà thuốc",
                },
                {
                    "rule_id": "r_fashion",
                    "text": "Size áo | Quy tắc ngành Thời trang",
                    "scope": "industry",
                    "precedence": 200,
                    "status": "descriptive",
                    "topic": "Size áo",
                    "industry": "Thời trang",
                },
            ]
        },
    }
    prompt_text = format_context_for_prompt(ctx)
    assert "Công thức riêng của doanh nghiệp" in prompt_text
    assert "Công thức mặc định" not in prompt_text
    assert "Quy tắc ngành Nhà thuốc" in prompt_text
    assert "Quy tắc ngành Thời trang" not in prompt_text


# --------------------------------------------------------------- E2E-07
def test_e2e07_select_star_hides_internal_dm_row_id_column(tmp_path):
    path = tmp_path / "bundle.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE sales (__dm_row_id BIGINT, ma_don VARCHAR, thanh_tien BIGINT)")
    con.execute("INSERT INTO sales VALUES (1, 'D1', 100000), (2, 'D2', 200000)")
    con.close()

    res = execute_query(
        ExecutionRequest(
            question_id="q_star",
            db_path=str(path),
            sql_query="SELECT * FROM sales ORDER BY ma_don",
        )
    )
    assert res.is_valid
    assert res.columns == ["ma_don", "thanh_tien"]
    assert res.rows == [
        {"ma_don": "D1", "thanh_tien": 100000},
        {"ma_don": "D2", "thanh_tien": 200000},
    ]


# --------------------------------------------------------------- E2E-03 & E2E-04
def test_e2e03_b05_retry_recognizes_catalog_data_and_empty_query_errors():
    from datamate.b0.b05.contracts import ExecutionErrorDetail
    from datamate.b0.b05.errors import ErrorCode
    from datamate.b0.b05.retry import classify_error

    cat = classify_error(
        ExecutionErrorDetail(
            type="CatalogError",
            message="Catalog Error: Table with name don_hang does not exist!",
        )
    )
    assert cat.code == ErrorCode.SCHEMA_ERROR and cat.retryable is True

    data_err = classify_error(
        ExecutionErrorDetail(
            type="DataError",
            message="Out of Range Error: Overflow in multiplication",
        )
    )
    assert data_err.code == ErrorCode.SQL_TYPE_ERROR and data_err.retryable is True

    empty_err = classify_error(
        ExecutionErrorDetail(
            type="EmptyQueryError",
            message="SQL query is empty.",
        )
    )
    assert empty_err.code == ErrorCode.SQL_SYNTAX and empty_err.retryable is True


def test_e2e04_infer_money_numeric_kind_from_sql():
    avg_res = Text2SQLResult(
        status="answerable",
        answer_type="number",
        sql="SELECT AVG(thanh_tien) FROM don_hang",
    ).to_b05_generation_result()
    assert avg_res.answer_semantics.numeric_kind == "average_money_vnd"

    sum_res = Text2SQLResult(
        status="answerable",
        answer_type="number",
        sql="SELECT SUM(don_gia * so_luong) FROM don_hang",
    ).to_b05_generation_result()
    assert sum_res.answer_semantics.numeric_kind == "money_vnd"


# --------------------------------------------------------------- E2E-02
def test_e2e02_evidence_proof_verifies_missing_field_and_rejects_existing_field():
    from datamate.b0.b05.contracts import ExecutionResult, GateRequest, QuestionMeta
    from datamate.b0.b05.gate import evaluate_gate

    ctx = _context_dict()
    # Case 1: Truly missing field "chi_phi_quang_cao" -> verified unanswerable
    ua_valid = parse_text2sql_response(
        json.dumps(
            {
                "status": "unanswerable",
                "missing_fields": ["chi_phi_quang_cao"],
                "reason": "Dữ liệu không có trường chi phí quảng cáo",
            }
        )
    )
    proof_valid = ua_valid.to_b05_evidence_proof(ctx)
    assert proof_valid.source_kind == "catalog_verified"
    assert proof_valid.capability_status == "unsupported"
    assert proof_valid.checked_all_sources is True

    outcome_valid = evaluate_gate(
        GateRequest(
            contract_version="b05.v1",
            question=QuestionMeta("q_ua1", "biz_test", "Chi phí quảng cáo?", "2026-04-01"),
            generation=ua_valid.to_b05_generation_result(),
            execution=ExecutionResult(status="not_executed"),
            evidence=proof_valid,
        )
    )
    assert outcome_valid.decision == "unanswerable"
    assert outcome_valid.final_answer.to_submission_dict()["type"] == "unanswerable"

    # Case 2: Hallucinated missing field "ma_khach" (which actually exists in don_hang!) -> rejected -> abstain
    ua_fake = parse_text2sql_response(
        json.dumps(
            {
                "status": "unanswerable",
                "missing_fields": ["ma_khach"],
                "reason": "Thiếu cột ma_khach",
            }
        )
    )
    proof_fake = ua_fake.to_b05_evidence_proof(ctx)
    assert proof_fake.source_kind != "catalog_verified" or proof_fake.capability_status != "unsupported"

    outcome_fake = evaluate_gate(
        GateRequest(
            contract_version="b05.v1",
            question=QuestionMeta("q_ua2", "biz_test", "Mã khách?", "2026-04-01"),
            generation=ua_fake.to_b05_generation_result(),
            execution=ExecutionResult(status="not_executed"),
            evidence=proof_fake,
        )
    )
    assert outcome_fake.decision == "abstain"


