import os
import pytest
import duckdb

from datamate.b0.b04 import (
    ExecutionRequest,
    ExecutionResponse,
    execute_query,
    extract_clean_sql,
    validate_read_only_sql,
    normalize_value,
    EmptyQueryError,
    SecurityViolation,
)
try:
    from tests.mock_data.build_mock_db import build_mock_database, build_mock_folder, MOCK_DB_PATH, MOCK_FOLDER_PATH
except ModuleNotFoundError:
    from mock_data.build_mock_db import build_mock_database, build_mock_folder, MOCK_DB_PATH, MOCK_FOLDER_PATH



@pytest.fixture(scope="session", autouse=True)
def setup_mock_data():
    """Ensures mock database and folder are built before any test runs."""
    build_mock_database(MOCK_DB_PATH)
    build_mock_folder(MOCK_FOLDER_PATH)


def test_01_valid_sql_execution():
    """
    Scenario 1: Valid SELECT query wrapped in markdown ```sql ... ```.
    Expected: is_valid=True, route='yes', cleaned_sql stripped of markdown,
    columns and rows populated and correctly normalized.
    """
    query = """
    ```sql
    SELECT customer_id, customer_name, total_spent
    FROM customers
    WHERE city = 'Ha Noi';
    ```
    """
    req = ExecutionRequest(
        question_id="q_test_01",
        db_path=MOCK_DB_PATH,
        sql_query=query,
        retry_count=0,
        max_retries=1,
    )
    res = execute_query(req)

    assert res.is_valid is True
    assert res.route == "yes"
    assert res.cleaned_sql is not None
    assert "```" not in res.cleaned_sql
    assert res.error_type is None
    assert res.error_message is None
    assert res.columns == ["customer_id", "customer_name", "total_spent"]
    assert res.row_count == 1
    assert len(res.rows) == 1
    assert res.rows[0]["customer_id"] == "CUST_001"
    assert res.rows[0]["customer_name"] == "Nguyen Van A"
    assert res.rows[0]["total_spent"] == 1500000.0
    assert res.execution_time_ms > 0


def test_02_syntax_error_recoverable():
    """
    Scenario 2: Syntax error in SQL on initial attempt (retry_count=0).
    Expected: is_valid=False, route='recoverable', error_type='SyntaxError',
    actionable error_message with line indicators.
    """
    query = "SELEC * FORM customers"
    req = ExecutionRequest(
        question_id="q_test_02",
        db_path=MOCK_DB_PATH,
        sql_query=query,
        retry_count=0,
        max_retries=1,
    )
    res = execute_query(req)

    assert res.is_valid is False
    assert res.route == "recoverable"
    assert res.error_type == "SyntaxError"
    assert res.error_message is not None
    assert len(res.error_message) > 0
    assert res.rows is None


def test_03_catalog_error_recoverable():
    """
    Scenario 3: Column or table does not exist on initial attempt (retry_count=0).
    Expected: is_valid=False, route='recoverable', error_type='CatalogError' or 'BinderError',
    contains DuckDB's helpful hint.
    """
    query = "SELECT non_existent_column FROM customers"
    req = ExecutionRequest(
        question_id="q_test_03",
        db_path=MOCK_DB_PATH,
        sql_query=query,
        retry_count=0,
        max_retries=1,
    )
    res = execute_query(req)

    assert res.is_valid is False
    assert res.route == "recoverable"
    assert res.error_type in ("CatalogError", "BinderError")
    assert "non_existent_column" in res.error_message


def test_04_rerun_corrected_sql_success():
    """
    Scenario 4: Simulates 'One bounded retry' flow.
    Initial attempt failed, LLM regenerated corrected SQL and reruns with retry_count=1.
    Expected: is_valid=True, route='yes'.
    """
    corrected_query = """
    SELECT c.customer_name, SUM(t.amount) AS total_val
    FROM customers c
    JOIN transactions t ON c.customer_id = t.customer_id
    WHERE t.status = 'COMPLETED'
    GROUP BY c.customer_name
    ORDER BY total_val DESC
    LIMIT 2;
    """
    req = ExecutionRequest(
        question_id="q_test_04",
        db_path=MOCK_DB_PATH,
        sql_query=corrected_query,
        retry_count=1,
        max_retries=1,
    )
    res = execute_query(req)

    assert res.is_valid is True
    assert res.route == "yes"
    assert res.row_count == 2
    assert "customer_name" in res.columns
    assert "total_val" in res.columns


def test_05_failed_after_retry_abstain():
    """
    Scenario 5: Query fails and retry_count >= max_retries (already used retry).
    Expected: is_valid=False, route='abstain' (transitions to Abstain if unresolved).
    """
    failing_query = "SELECT * FROM non_existent_table"
    req = ExecutionRequest(
        question_id="q_test_05",
        db_path=MOCK_DB_PATH,
        sql_query=failing_query,
        retry_count=1,
        max_retries=1,
    )
    res = execute_query(req)

    assert res.is_valid is False
    assert res.route == "abstain"
    assert res.error_type in ("CatalogError", "BinderError")


def test_06_security_guardrail_read_only():
    """
    Scenario 6: Hostile/destructive commands (DROP, INSERT, COPY, read_csv).
    Expected: Blocked immediately by AST sanitizer or DuckDB sandbox,
    error_type='SecurityViolation', underlying tables remain completely intact.
    """
    malicious_queries = [
        "DROP TABLE customers;",
        "INSERT INTO customers VALUES ('CUST_HACK', 'Hacker', 'Nowhere', 0, false, '2026-01-01');",
        "UPDATE customers SET total_spent = 0;",
        "COPY customers TO 'leaked.csv';",
        "SELECT * FROM read_csv('secret.csv');",
    ]

    for bad_sql in malicious_queries:
        req = ExecutionRequest(
            question_id="q_test_06",
            db_path=MOCK_DB_PATH,
            sql_query=bad_sql,
            retry_count=0,
            max_retries=1,
        )
        res = execute_query(req)

        assert res.is_valid is False
        assert res.error_type == "SecurityViolation", f"Failed to detect security violation for: {bad_sql}"
        assert res.route == "recoverable"

    # Verify database integrity: ensure 'customers' still exists and has 5 original rows
    verify_con = duckdb.connect(MOCK_DB_PATH, read_only=True)
    count = verify_con.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    verify_con.close()
    assert count == 5, "Database was modified! Security barrier was breached."


def test_07_infinite_query_timeout():
    """
    Scenario 7: Infinite recursive CTE query with timeout_sec=1.0.
    Expected: Interrupted after ~1 second, is_valid=False, error_type='TimeoutError',
    does NOT hang or block the test suite.
    """
    infinite_sql = """
    WITH RECURSIVE inf(x) AS (
        SELECT 1
        UNION ALL
        SELECT x + 1 FROM inf
    )
    SELECT COUNT(*) FROM inf;
    """
    req = ExecutionRequest(
        question_id="q_test_07",
        db_path=MOCK_DB_PATH,
        sql_query=infinite_sql,
        timeout_sec=1.0,
        retry_count=0,
        max_retries=1,
    )
    res = execute_query(req)

    assert res.is_valid is False
    assert res.error_type == "TimeoutError"
    assert "timed out" in res.error_message.lower()
    assert res.route == "recoverable"
    assert res.execution_time_ms >= 800.0  # Approx >= 0.8s


def test_08_empty_query():
    """Scenario 8: Empty or whitespace query."""
    req = ExecutionRequest(
        question_id="q_test_08",
        db_path=MOCK_DB_PATH,
        sql_query="   ```sql   ```   ",
        retry_count=0,
    )
    res = execute_query(req)

    assert res.is_valid is False
    assert res.error_type == "EmptyQueryError"
    assert res.route == "recoverable"


def test_09_folder_db_path():
    """Scenario 9: db_path is a directory of CSV/Parquet files."""
    query = "SELECT order_id, total_amount, status FROM orders WHERE status = 'Delivered'"
    req = ExecutionRequest(
        question_id="q_test_09",
        db_path=MOCK_FOLDER_PATH,
        sql_query=query,
        retry_count=0,
    )
    res = execute_query(req)

    assert res.is_valid is True
    assert res.route == "yes"
    assert res.row_count == 1
    assert res.rows[0]["order_id"] == "ORD_1"
    assert res.rows[0]["total_amount"] == 150000


def test_10_multi_statement_security():
    """Scenario 10: Multi-statement injection attempt."""
    query = "SELECT * FROM customers; SELECT * FROM transactions;"
    req = ExecutionRequest(
        question_id="q_test_10",
        db_path=MOCK_DB_PATH,
        sql_query=query,
        retry_count=0,
    )
    res = execute_query(req)

    assert res.is_valid is False
    assert res.error_type == "SecurityViolation"
    assert "Multiple SQL statements" in res.error_message


def test_11_normalization():
    """Scenario 11: Normalization of various special data types."""
    import datetime
    import decimal

    assert normalize_value(None) is None
    assert normalize_value(float("nan")) is None
    assert normalize_value(float("inf")) is None
    assert normalize_value(datetime.date(2026, 11, 3)) == "2026-11-03"
    assert normalize_value(datetime.datetime(2026, 11, 3, 14, 30, 0)) == "2026-11-03T14:30:00"
    assert normalize_value(decimal.Decimal("100.00")) == 100
    assert normalize_value(decimal.Decimal("100.50")) == 100.5
    assert normalize_value(b"hello") == "hello"
    assert normalize_value([1, float("nan"), 3]) == [1, None, 3]
    assert normalize_value({"a": float("nan"), "b": decimal.Decimal("42")}) == {"a": None, "b": 42}


def test_12_nonexistent_db_path():
    """Scenario 12: db_path does not exist on disk."""
    req = ExecutionRequest(
        question_id="q_test_12",
        db_path="invalid_path_to_nonexistent_file.duckdb",
        sql_query="SELECT 1",
        retry_count=0,
    )
    res = execute_query(req)

    assert res.is_valid is False
    assert res.error_type == "DatabaseIOError"
    assert res.route == "abstain"  # Unrecoverable system error


def test_13_adapter_to_b05_execution_result():
    """Scenario 13: Verifies adapter method converting ExecutionResponse to B0.5 ExecutionResult."""
    # 1. Success response
    req = ExecutionRequest(
        question_id="q_test_13_success",
        db_path=MOCK_DB_PATH,
        sql_query="SELECT customer_id, customer_name FROM customers LIMIT 2",
    )
    res = execute_query(req)
    b05_res = res.to_b05_execution_result()

    assert b05_res.status == "success"
    assert b05_res.columns == ["customer_id", "customer_name"]
    assert len(b05_res.rows) == 2
    assert isinstance(b05_res.rows[0], list)

    # 2. Error response
    req_err = ExecutionRequest(
        question_id="q_test_13_err",
        db_path=MOCK_DB_PATH,
        sql_query="SELECT nonexistent_column FROM customers",
    )
    res_err = execute_query(req_err)
    b05_err = res_err.to_b05_execution_result()

    assert b05_err.status == "error"
    assert b05_err.error is not None
    assert b05_err.error.type == "BinderError"


def test_14_from_b03_adapter():
    """Scenario 14: Verifies ExecutionRequest creation from B0.3 Text2SQLResult."""
    from datamate.b0.b03.types import Text2SQLResult

    b03_res = Text2SQLResult(
        status="answerable",
        answer_type="number",
        sql="SELECT COUNT(*) FROM customers",
        tables_used=("customers",),
    )
    req = ExecutionRequest.from_b03(
        b03_result=b03_res,
        question_id="q_from_b03",
        db_path=MOCK_DB_PATH,
    )
    assert req.question_id == "q_from_b03"
    assert req.sql_query == "SELECT COUNT(*) FROM customers"
    assert req.answer_type == "number"

    res = execute_query(req)
    assert res.is_valid is True
    assert res.route == "yes"
    assert res.row_count == 1


