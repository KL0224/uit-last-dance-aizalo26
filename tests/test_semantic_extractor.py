"""Tests for Dynamic Semantic Metric Discovery and Rule-Schema Matcher."""

import pytest
from datamate.context.contracts import BusinessRule, RuleCatalog, MetricDefinition, SemanticCatalog
from datamate.ingestion.contracts import SchemaCatalog, TableMetadata, ColumnMetadata
from datamate.context.semantic_extractor import RuleSchemaMatcher


@pytest.fixture
def dev_012_schema() -> SchemaCatalog:
    tho_cols = (
        ColumnMetadata(name="ho_ten", data_type="VARCHAR"),
        ColumnMetadata(name="ngay_vao_lam", data_type="DATE"),
        ColumnMetadata(name="hoa_hong", data_type="DOUBLE"),
    )
    so_sua_cols = (
        ColumnMetadata(name="ngay", data_type="DATE"),
        ColumnMetadata(name="xe", data_type="VARCHAR"),
        ColumnMetadata(name="lam_gi", data_type="VARCHAR"),
        ColumnMetadata(name="tho", data_type="VARCHAR"),
        ColumnMetadata(name="tien", data_type="BIGINT"),
        ColumnMetadata(name="ghi_chu", data_type="VARCHAR"),
    )
    tables = (
        TableMetadata(name="danh_sach_tho_65cdb6fe", columns=tho_cols),
        TableMetadata(name="so_sua_xe_8cb37feb", columns=so_sua_cols),
    )
    return SchemaCatalog(tables=tables, join_graph=())


@pytest.fixture
def dev_012_rules() -> tuple[BusinessRule, ...]:
    return (
        BusinessRule(
            rule_id="r_0",
            text="Sổ sửa xe: mỗi dòng một lượt xe vào sửa (một phiếu), không ghi mã phiếu.",
            source="README.md",
            scope="business",
            precedence=10,
            required_fields=("ngay", "xe", "tho", "tien"),
            topic="Lượt xe",
        ),
        BusinessRule(
            rule_id="r_11",
            text="- **Hoa hồng (%)**: phần trăm hoa hồng của thợ, tính trên tổng Tiền các phiếu thợ làm trong tháng",
            source="README.md",
            scope="business",
            precedence=10,
            required_fields=("hoa_hong", "tho", "tien"),
            topic="Hoa hồng",
        ),
        BusinessRule(
            rule_id="r_16",
            text="Bán được bao nhiêu tiền, thu về bao nhiêu tiền | là doanh thu theo mục này",
            source="rulebook.md",
            scope="split_default",
            precedence=5,
            required_fields=("tien",),
            topic="Doanh thu",
        ),
        BusinessRule(
            rule_id="r_82",
            text="Lượt xe, phiếu | mỗi dòng sổ sửa xe là một lượt xe (một phiếu)",
            source="rulebook.md",
            scope="split_default",
            precedence=5,
            required_fields=("xe", "tho", "tien"),
            topic="Lượt xe, phiếu",
        ),
        BusinessRule(
            rule_id="r_86",
            text="Bảo hành | Tỉ lệ bảo hành bằng số phiếu bảo hành có ngày trong kỳ",
            source="rulebook.md",
            scope="split_default",
            precedence=5,
            required_fields=("ngay", "xe", "tien"),
            topic="Bảo hành",
        ),
    )


def test_rule_schema_matcher_discovers_commission_and_revenue(
    dev_012_schema: SchemaCatalog, dev_012_rules: tuple[BusinessRule, ...]
) -> None:
    matcher = RuleSchemaMatcher()
    catalog = matcher.extract_semantic_catalog(
        business_id="dev_012",
        schema=dev_012_schema,
        rules=dev_012_rules,
    )

    metrics_by_id = {m.metric_id: m for m in catalog.metrics}
    
    # 1. Phải phát hiện được metric hoa_hong / commission
    assert "commission" in metrics_by_id or "hoa_hong" in metrics_by_id
    comm_metric = metrics_by_id.get("commission") or metrics_by_id.get("hoa_hong")
    assert comm_metric is not None
    assert "hoa_hong" in comm_metric.required_columns or "tien" in comm_metric.required_columns
    assert any("hoa hồng" in a.lower() for a in comm_metric.aliases)

    # 2. Phải có metric revenue gán đúng bảng so_sua_xe
    assert "revenue" in metrics_by_id
    rev = metrics_by_id["revenue"]
    assert rev.preferred_table == "so_sua_xe_8cb37feb"
    assert "tien" in rev.required_columns

    # 3. Phải có metric order_count và gán đúng bảng so_sua_xe, KHÔNG gán danh_sach_tho
    assert "order_count" in metrics_by_id
    ord_cnt = metrics_by_id["order_count"]
    assert ord_cnt.preferred_table == "so_sua_xe_8cb37feb"
    assert ord_cnt.preferred_table != "danh_sach_tho_65cdb6fe"

    # 4. Phải có warranty_count
    assert "warranty_count" in metrics_by_id


def test_rule_schema_matcher_retail_shop() -> None:
    order_cols = (
        ColumnMetadata(name="order_id", data_type="VARCHAR"),
        ColumnMetadata(name="order_date", data_type="DATE"),
        ColumnMetadata(name="total_amount", data_type="BIGINT"),
    )
    item_cols = (
        ColumnMetadata(name="order_id", data_type="VARCHAR"),
        ColumnMetadata(name="product_name", data_type="VARCHAR"),
        ColumnMetadata(name="quantity", data_type="BIGINT"),
        ColumnMetadata(name="unit_cost", data_type="BIGINT"),
    )
    schema = SchemaCatalog(
        tables=(
            TableMetadata(name="orders", columns=order_cols),
            TableMetadata(name="order_items", columns=item_cols),
        ),
        join_graph=(),
    )
    rules = (
        BusinessRule(
            rule_id="r_rev",
            text="Doanh thu một đơn | tổng thành tiền các dòng hàng",
            source="rulebook.md",
            scope="split_default",
            precedence=5,
            required_fields=("total_amount",),
            topic="Doanh thu",
        ),
        BusinessRule(
            rule_id="r_profit",
            text="Lãi gộp | doanh thu trừ giá vốn",
            source="rulebook.md",
            scope="split_default",
            precedence=5,
            required_fields=("unit_cost", "quantity"),
            topic="Lãi gộp",
        ),
        BusinessRule(
            rule_id="r_qty",
            text="Bán chạy | theo số lượng",
            source="rulebook.md",
            scope="split_default",
            precedence=5,
            required_fields=("quantity",),
            topic="Bán chạy",
        ),
    )
    matcher = RuleSchemaMatcher()
    catalog = matcher.extract_semantic_catalog(
        business_id="retail_001",
        schema=schema,
        rules=rules,
    )
    metrics_by_id = {m.metric_id: m for m in catalog.metrics}
    assert "revenue" in metrics_by_id
    assert "sold_qty" in metrics_by_id
    assert "cost" in metrics_by_id
    assert "gross_profit" in metrics_by_id
    assert "order_count" in metrics_by_id


def test_llm_semantic_extractor_with_mock_llm(dev_012_schema: SchemaCatalog, dev_012_rules: tuple[BusinessRule, ...]) -> None:
    from datamate.context.semantic_extractor import LLMSemanticExtractor

    mock_llm_json = """```json
    {
      "metrics": [
        {
          "metric_id": "commission",
          "name": "Tiền hoa hồng thợ",
          "aliases": ["hoa hồng", "huê hồng thợ"],
          "preferred_table": "danh_sach_tho_65cdb6fe",
          "required_columns": ["hoa_hong"],
          "formula_hint": "SUM(tien * CAST(hoa_hong AS DOUBLE)/100)",
          "unit": "VND"
        }
      ],
      "suggested_joins": [
        {
          "left_table": "so_sua_xe_8cb37feb",
          "left_column": "tho",
          "right_table": "danh_sach_tho_65cdb6fe",
          "right_column": "ho_ten",
          "join_type": "name_suffix_match",
          "description": "Cột tho ghi tên gọi tắt"
        }
      ]
    }
    ```"""

    def mock_chat(system: str, user: str) -> str:
        return mock_llm_json

    extractor = LLMSemanticExtractor(chat_fn=mock_chat)
    catalog = extractor.extract_semantic_catalog("dev_012", dev_012_schema, dev_012_rules)
    metrics_by_id = {m.metric_id: m for m in catalog.metrics}
    assert "commission" in metrics_by_id
    assert metrics_by_id["commission"].preferred_table == "danh_sach_tho_65cdb6fe"
    assert "revenue" in metrics_by_id  # preserved from base
    assert len(catalog.suggested_joins) == 1
    assert catalog.suggested_joins[0]["left_table"] == "so_sua_xe_8cb37feb"


