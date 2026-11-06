"""Comprehensive test suite for B0.3 Text-to-SQL module, prompt builder, parser, and generator."""

from __future__ import annotations

import pytest

from datamate.b0.b01 import ColumnMetadata, SchemaCatalogBuilder, TableMetadata
from datamate.b0.b02 import BusinessContext, BusinessRule, ContractBuilder, RuleCatalog
from datamate.b0.b03 import (
    BaseLLM,
    ChatMessage,
    GenerationOptions,
    GenerationResult,
    Text2SQLGenerator,
    Text2SQLParseError,
    Text2SQLResult,
    build_repair_messages,
    build_text2sql_messages,
    extract_tables_from_sql,
    format_context_for_prompt,
    infer_answer_type_from_sql,
    parse_text2sql_response,
)
from datamate.b0.b05.contracts import GenerationResult as B05GenerationResult


class MockLLM(BaseLLM):
    """Mock LLM implementation for deterministic, offline testing of B0.3."""

    def __init__(self, response_text: str = "") -> None:
        self.response_text = response_text
        self.last_messages: list[ChatMessage] = []
        self._loaded = True

    def load(self) -> None:
        self._loaded = True

    def generate(self, prompt: str, *, options: GenerationOptions | None = None) -> GenerationResult:
        return GenerationResult(
            text=self.response_text,
            input_tokens=10,
            output_tokens=len(self.response_text.split()),
            finish_reason="stop",
        )

    def chat(self, messages: list[ChatMessage], *, options: GenerationOptions | None = None) -> GenerationResult:
        self.last_messages = messages
        return GenerationResult(
            text=self.response_text,
            input_tokens=20,
            output_tokens=len(self.response_text.split()),
            finish_reason="stop",
        )

    def generate_batch(self, prompts: list[str], *, options: GenerationOptions | None = None) -> list[GenerationResult]:
        return [self.generate(p, options=options) for p in prompts]


@pytest.fixture
def sample_business_context() -> BusinessContext:
    """Creates a sample B0.2 BusinessContext for testing."""
    table = TableMetadata(
        name="orders",
        columns=(
            ColumnMetadata(name="order_id", data_type="VARCHAR", nullable=False),
            ColumnMetadata(name="customer_id", data_type="VARCHAR", nullable=False),
            ColumnMetadata(name="amount", data_type="DECIMAL", nullable=False),
            ColumnMetadata(name="order_date", data_type="DATE", nullable=False),
        ),
        primary_key_candidates=("order_id",),
        grain="Mỗi dòng là một đơn hàng",
    )
    schema_catalog = SchemaCatalogBuilder().build([table])
    rule = BusinessRule(
        rule_id="R_ORDERS_01",
        text="Đơn hàng hợp lệ là đơn có amount > 0",
        source="rulebook.md",
        scope="table",
        precedence=1,
    )
    rule_catalog = RuleCatalog(rules=(rule,), business_id="biz_001")
    return ContractBuilder().build(
        business_id="biz_001",
        schema_catalog=schema_catalog,
        rule_catalog=rule_catalog,
    )


def test_text2sql_result_invariants():
    """Verify Text2SQLResult constraints and conversion to B0.5 GenerationResult."""
    # 1. Answerable
    res = Text2SQLResult(
        status="answerable",
        answer_type="number",
        sql="SELECT COUNT(*) FROM orders",
        tables_used=["orders"],
        assumptions=["Không có đơn hủy"],
    )
    assert res.status == "answerable"
    assert isinstance(res.tables_used, tuple)
    assert isinstance(res.assumptions, tuple)

    b05_res = res.to_b05_generation_result()
    assert isinstance(b05_res, B05GenerationResult)
    assert b05_res.answer_type == "number"
    assert b05_res.sql == "SELECT COUNT(*) FROM orders"
    assert b05_res.tables_used == ["orders"]

    # 2. Unanswerable
    unans_res = Text2SQLResult(
        status="unanswerable",
        reason="Thiếu dữ liệu chi phí",
    )
    assert unans_res.status == "unanswerable"
    assert unans_res.reason == "Thiếu dữ liệu chi phí"

    b05_unans = unans_res.to_b05_generation_result()
    assert b05_unans.answer_type == "unanswerable"
    assert b05_unans.sql == ""

    # 3. Invalid status raises ValueError
    with pytest.raises(ValueError, match="Unsupported status"):
        Text2SQLResult(status="invalid_status")  # type: ignore


def test_format_context_for_prompt(sample_business_context: BusinessContext):
    """Verify context formatting includes schema tables, rules, and grains."""
    formatted = format_context_for_prompt(sample_business_context)
    assert "TABLE SCHEMAS" in formatted
    assert "orders" in formatted
    assert "order_id" in formatted
    assert "R_ORDERS_01" in formatted


def test_build_text2sql_messages(sample_business_context: BusinessContext):
    """Verify build_text2sql_messages produces valid ChatMessage pair."""
    messages = build_text2sql_messages(
        context=sample_business_context,
        question="Có bao nhiêu đơn hàng trong năm 2025?",
        as_of_date="2026-01-01",
    )
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert "2026-01-01" in messages[1].content
    assert "Có bao nhiêu đơn hàng" in messages[1].content


def test_build_repair_messages(sample_business_context: BusinessContext):
    """Verify build_repair_messages includes previous SQL and execution error."""
    messages = build_repair_messages(
        context=sample_business_context,
        question="Doanh thu tháng 12?",
        as_of_date="2026-01-01",
        previous_sql="SELECT sum(rev) FROM orders",
        error_message="BinderError: Column 'rev' does not exist",
    )
    assert len(messages) == 2
    assert "SELECT sum(rev) FROM orders" in messages[1].content
    assert "BinderError: Column 'rev' does not exist" in messages[1].content


def test_parse_text2sql_valid_json():
    """Verify parsing valid json format."""
    raw = """
    ```json
    {
      "status": "answerable",
      "answer_type": "number",
      "sql": "SELECT COUNT(*) FROM orders WHERE amount > 0;",
      "tables_used": ["orders"],
      "assumptions": ["Chỉ tính đơn có amount > 0"],
      "reason": null
    }
    ```
    """
    res = parse_text2sql_response(raw)
    assert res.status == "answerable"
    assert res.answer_type == "number"
    assert res.sql == "SELECT COUNT(*) FROM orders WHERE amount > 0"
    assert res.tables_used == ("orders",)
    assert res.assumptions == ("Chỉ tính đơn có amount > 0",)


def test_parse_text2sql_unanswerable_json():
    """Verify parsing unanswerable json format."""
    raw = """
    {
      "status": "unanswerable",
      "answer_type": null,
      "sql": null,
      "tables_used": [],
      "assumptions": [],
      "reason": "Dữ liệu không có thông tin chi phí vận chuyển."
    }
    """
    res = parse_text2sql_response(raw)
    assert res.status == "unanswerable"
    assert res.answer_type is None
    assert res.sql is None
    assert "chi phí vận chuyển" in str(res.reason)


def test_parse_text2sql_raw_sql_fallback():
    """Verify fallback parser when LLM outputs bare SQL inside code fences."""
    raw = """
    ```sql
    SELECT SUM(amount) AS total_revenue
    FROM orders
    JOIN customers ON orders.customer_id = customers.customer_id;
    ```
    """
    res = parse_text2sql_response(raw)
    assert res.status == "answerable"
    assert res.answer_type == "number"
    assert "SELECT SUM(amount)" in (res.sql or "")
    assert "orders" in res.tables_used
    assert "customers" in res.tables_used


def test_parse_text2sql_rejection_text_fallback():
    """Verify fallback when LLM provides textual rejection."""
    raw = "Rất tiếc, tôi không thể trả lời câu hỏi này vì cơ sở dữ liệu thiếu bảng chi phí."
    res = parse_text2sql_response(raw)
    assert res.status == "unanswerable"
    assert "không thể trả lời" in str(res.reason)


def test_parse_text2sql_empty_raises_error():
    """Verify empty response raises Text2SQLParseError."""
    with pytest.raises(Text2SQLParseError, match="hoàn toàn rỗng"):
        parse_text2sql_response("")


def test_extract_tables_from_sql():
    """Verify SQL table extraction regex."""
    sql = 'SELECT * FROM "orders" JOIN line_items ON orders.id = line_items.order_id WHERE x = 1'
    tables = extract_tables_from_sql(sql)
    assert "orders" in tables
    assert "line_items" in tables


def test_infer_answer_type():
    """Verify answer type inference heuristics."""
    assert infer_answer_type_from_sql("SELECT COUNT(*) FROM tbl") == "number"
    assert infer_answer_type_from_sql("SELECT AVG(price) FROM tbl") == "number"
    assert infer_answer_type_from_sql("SELECT strftime('%Y-%m', dt) FROM tbl") == "date"
    assert infer_answer_type_from_sql("SELECT * FROM tbl") == "table"


def test_text2sql_generator_end_to_end(sample_business_context: BusinessContext):
    """Verify Text2SQLGenerator end-to-end generate and repair methods."""
    mock_response = """
    {
      "status": "answerable",
      "answer_type": "number",
      "sql": "SELECT COUNT(*) FROM orders",
      "tables_used": ["orders"]
    }
    """
    mock_llm = MockLLM(mock_response)
    generator = Text2SQLGenerator(mock_llm)

    # 1. Test generate
    result = generator.generate(
        context=sample_business_context,
        question="Đếm số đơn hàng?",
        as_of_date="2026-01-01",
    )
    assert result.status == "answerable"
    assert result.sql == "SELECT COUNT(*) FROM orders"
    assert result.answer_type == "number"

    # 2. Test repair
    mock_repair_response = """
    {
      "status": "answerable",
      "answer_type": "number",
      "sql": "SELECT COUNT(order_id) FROM orders",
      "tables_used": ["orders"]
    }
    """
    mock_llm.response_text = mock_repair_response
    repaired = generator.repair(
        context=sample_business_context,
        question="Đếm số đơn hàng?",
        as_of_date="2026-01-01",
        previous_sql="SELECT COUNT(unknown_col) FROM orders",
        error_message="BinderError: Column 'unknown_col' not found",
    )
    assert repaired.status == "answerable"
    assert repaired.sql == "SELECT COUNT(order_id) FROM orders"

