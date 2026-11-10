"""Compatibility tests between B0.1, B0.2 (post improvement-b01-b02) and Component C Grounding."""

from __future__ import annotations

import json

import pytest

from datamate.b0.b01.contracts import (
    ColumnMetadata,
    JoinEdge,
    JoinStatistics,
    RelationshipEvidence,
    SchemaCatalog,
    TableMetadata,
)
from datamate.b0.b01.relationship_evidence import relationship_fingerprint
from datamate.b0.b01.schema_catalog import SchemaCatalogBuilder
from datamate.b0.b02.contracts import BusinessContext, BusinessRule, ContractBuilder, RuleCatalog
from datamate.grounding import (
    B02ContextAdapter,
    CoverageStatus,
    GroundingToPlannerAdapter,
    QuestionGroundingEngine,
    QuestionRequest,
)


def _trusted_attestation(
    business_id: str,
    left_table: str,
    right_table: str,
    key_pairs: tuple[tuple[str, str], ...],
    cardinality: str,
) -> RelationshipEvidence:
    edge_probe = JoinEdge(
        left_table=left_table,
        left_column=key_pairs[0][0],
        right_table=right_table,
        right_column=key_pairs[0][1],
        cardinality=cardinality,
        status="candidate",
        confidence=0.95,
        evidence=(),
        additional_key_pairs=key_pairs[1:],
    )
    return RelationshipEvidence(
        origin="reviewed_relationship",
        business_id=business_id,
        source="relationships.json",
        source_sha256="a" * 64,
        statement="Reviewed join relationship",
        review_status="approved",
        reviewed_by="qa_reviewer",
        relationship_sha256=relationship_fingerprint(edge_probe, business_id),
    )


class TestB01B02GroundingCompatibility:
    """Verify Component C Grounding works seamlessly with improved B0.1/B0.2 contracts."""

    def test_b02_adapter_ignores_unvalidated_join_edges(self) -> None:
        """Only edges with status == 'validated' may be used by B02ContextAdapter and SchemaGrounder."""
        tables = (
            TableMetadata(
                name="don_hang",
                grain="order",
                row_count=10,
                columns=(
                    ColumnMetadata(name="ma_don", data_type="VARCHAR"),
                    ColumnMetadata(name="ma_khach", data_type="VARCHAR"),
                    ColumnMetadata(name="tong_tien", data_type="DECIMAL(18,2)", provenance="Tổng tiền"),
                ),
            ),
            TableMetadata(
                name="khach_hang",
                grain="customer",
                row_count=5,
                columns=(
                    ColumnMetadata(name="ma_khach", data_type="VARCHAR"),
                    ColumnMetadata(name="ten_khach", data_type="VARCHAR", provenance="Tên khách hàng"),
                ),
            ),
            TableMetadata(
                name="san_pham",
                grain="product",
                row_count=8,
                columns=(
                    ColumnMetadata(name="ma_sp", data_type="VARCHAR"),
                    ColumnMetadata(name="ten_sp", data_type="VARCHAR", provenance="Tên sản phẩm"),
                ),
            ),
        )
        edges = (
            JoinEdge(
                left_table="don_hang",
                left_column="ma_khach",
                right_table="khach_hang",
                right_column="ma_khach",
                cardinality="many_to_one",
                status="validated",
                confidence=0.95,
                evidence=("reviewed",),
            ),
            JoinEdge(
                left_table="don_hang",
                left_column="ma_don",
                right_table="san_pham",
                right_column="ma_sp",
                cardinality="many_to_one",
                status="uncertain",
                confidence=0.75,
                evidence=("inferred only",),
            ),
            JoinEdge(
                left_table="khach_hang",
                left_column="ma_khach",
                right_table="san_pham",
                right_column="ma_sp",
                cardinality="one_to_one",
                status="invalid",
                confidence=0.0,
                evidence=("orphan keys",),
            ),
        )
        ctx = BusinessContext(
            contract_version="1.1",
            business_id="biz_join_filter",
            schema_catalog=SchemaCatalog(tables=tables, join_graph=edges),
            rule_catalog=RuleCatalog(rules=()),
        )

        adapter = B02ContextAdapter(ctx)
        join_edges = adapter.get_join_edges()

        assert len(join_edges) == 1
        assert join_edges[0].left_table == "don_hang"
        assert join_edges[0].right_table == "khach_hang"

    def test_b02_adapter_preserves_composite_join_keys_and_null_warnings(self) -> None:
        """Composite key pairs and JoinStatistics NULL key warnings must flow to SelectedSchema and Planner prompt."""
        tables = (
            TableMetadata(
                name="lines",
                grain="order_line",
                row_count=100,
                columns=(
                    ColumnMetadata(name="order_id", data_type="VARCHAR"),
                    ColumnMetadata(name="line_no", data_type="INTEGER"),
                    ColumnMetadata(name="thanh_tien", data_type="DECIMAL(18,2)", provenance="Doanh thu dòng"),
                ),
            ),
            TableMetadata(
                name="allocations",
                grain="allocation_lot",
                row_count=150,
                columns=(
                    ColumnMetadata(name="order_id", data_type="VARCHAR"),
                    ColumnMetadata(name="line_no", data_type="INTEGER"),
                    ColumnMetadata(name="lot_code", data_type="VARCHAR", provenance="Mã lô hàng"),
                ),
                profile_rows=({"order_id": "O1", "line_no": 1, "lot_code": "LOT-99"},),
            ),
        )
        composite_edge = JoinEdge(
            left_table="allocations",
            left_column="order_id",
            right_table="lines",
            right_column="order_id",
            cardinality="many_to_one",
            status="validated",
            confidence=0.95,
            evidence=("reviewed composite",),
            fanout_warning=True,
            additional_key_pairs=(("line_no", "line_no"),),
            statistics=JoinStatistics(
                left_rows=150,
                right_rows=100,
                left_null_rows=3,
                right_null_rows=0,
                left_distinct=100,
                right_distinct=100,
                matched_distinct=100,
                left_coverage=1.0,
                right_coverage=1.0,
                observed_cardinality="many_to_one",
            ),
        )
        ctx = BusinessContext(
            contract_version="1.1",
            business_id="biz_composite",
            schema_catalog=SchemaCatalog(tables=tables, join_graph=(composite_edge,)),
            rule_catalog=RuleCatalog(
                rules=(
                    BusinessRule(
                        rule_id="r_rev",
                        text="Doanh thu tính theo cột thanh_tien trên bảng lines.",
                        source="rulebook.md",
                        scope="global",
                        precedence=1,
                        required_fields=("lines.thanh_tien",),
                    ),
                )
            ),
        )

        adapter = B02ContextAdapter(ctx)
        engine = QuestionGroundingEngine()
        grounded = engine.ground(
            QuestionRequest(
                question_id="q_comp_1",
                business_id="biz_composite",
                question="Tổng doanh thu của lô hàng LOT-99 trong tháng 8/2026 là bao nhiêu?",
                as_of_date="2026-08-31",
            ),
            context=adapter,
        )

        assert len(grounded.selected_schema.join_paths) == 1
        jp = grounded.selected_schema.join_paths[0]
        assert jp.additional_key_pairs == (("line_no", "line_no"),)
        assert jp.null_key_warning is True
        assert any("NULL" in w for w in grounded.selected_schema.warnings)

        # Ensure both composite join columns were selected as relevant on both tables
        for tbl_cand in grounded.selected_schema.tables:
            assert "order_id" in tbl_cand.relevant_columns
            assert "line_no" in tbl_cand.relevant_columns

        prompt_md = GroundingToPlannerAdapter.to_planner_prompt_markdown(grounded)
        assert "order_id" in prompt_md and "line_no" in prompt_md
        assert " AND " in prompt_md
        assert "NULL" in prompt_md

    def test_b02_adapter_extracts_samples_date_coverage_and_roles_from_profiling(self) -> None:
        """When profile_rows are stripped on export, samples and date bounds come from data_profiling."""
        tables = (
            TableMetadata(
                name="don_hang_a1b2c3d4",
                grain="order",
                row_count=50,
                columns=(
                    ColumnMetadata(name="ma_don", data_type="VARCHAR", provenance="Mã đơn"),
                    ColumnMetadata(name="ngay_ban", data_type="DATE", provenance="Ngày bán"),
                    ColumnMetadata(name="tong_tien", data_type="DECIMAL(18,2)", provenance="Tổng tiền"),
                    ColumnMetadata(name="kenh_ban", data_type="VARCHAR", provenance="Kênh bán"),
                ),
                profile_rows=(),  # Stripped as in BusinessContext.to_dict()
            ),
        )
        data_profiling = {
            "don_hang_a1b2c3d4": {
                "row_count": 50,
                "columns": {
                    "ma_don": {"null_count": 0, "cardinality": 50, "mode": "exact"},
                    "ngay_ban": {
                        "null_count": 0,
                        "cardinality": 20,
                        "mode": "exact",
                        "observed_min": "2026-08-01",
                        "observed_max": "2026-08-31",
                    },
                    "tong_tien": {"null_count": 0, "cardinality": 45, "mode": "exact"},
                    "kenh_ban": {"null_count": 0, "cardinality": 2, "mode": "exact"},
                },
                "samples": [
                    {
                        "ma_don": "DH001",
                        "ngay_ban": "2026-08-05",
                        "tong_tien": "250000.00",
                        "kenh_ban": "ShopeeFood",
                    }
                ],
            }
        }
        business_metadata = {
            "schema_mapping": {
                "don_hang_a1b2c3d4": {
                    "family": "don_hang",
                    "source_ids": ["orders.csv"],
                    "columns": {
                        "ma_don": {"original_name": "Mã đơn", "role": "identifier", "sql_type": "VARCHAR"},
                        "ngay_ban": {"original_name": "Ngày bán", "role": "date", "sql_type": "DATE"},
                        "tong_tien": {"original_name": "Tổng tiền", "role": "money", "sql_type": "DECIMAL(18,2)"},
                        "kenh_ban": {"original_name": "Kênh bán", "role": "text", "sql_type": "VARCHAR"},
                    },
                }
            }
        }
        ctx = BusinessContext(
            contract_version="1.1",
            business_id="biz_profiled",
            schema_catalog=SchemaCatalog(tables=tables),
            rule_catalog=RuleCatalog(rules=()),
            data_profiling=data_profiling,
            business_metadata=business_metadata,
        )

        # Round-trip through JSON dict to verify B02ContextAdapter.from_dict
        payload = json.loads(json.dumps(ctx.to_dict()))
        adapter = B02ContextAdapter.from_dict(payload)

        tbl_spec = adapter.get_tables()[0]
        assert tbl_spec.date_coverage_start == "2026-08-01"
        assert tbl_spec.date_coverage_end == "2026-08-31"
        assert "don_hang" in tbl_spec.aliases

        col_map = {c.name: c for c in tbl_spec.columns}
        assert col_map["ma_don"].role == "id"
        assert "Mã đơn" in col_map["ma_don"].aliases
        assert col_map["tong_tien"].role == "money"
        assert "ShopeeFood" in col_map["kenh_ban"].sample_values

        # Out-of-range temporal query should trigger TEMPORAL_OUT_OF_RANGE risk flag
        engine = QuestionGroundingEngine()
        grounded_out = engine.ground(
            QuestionRequest(
                question_id="q_out_of_range",
                business_id="biz_profiled",
                question="Tổng doanh thu kênh ShopeeFood trong tháng 01/2025 là bao nhiêu?",
                as_of_date="2026-08-31",
            ),
            context=adapter,
        )
        assert grounded_out.coverage_status == CoverageStatus.UNKNOWN
        assert any("TEMPORAL_OUT_OF_RANGE" in flag for flag in grounded_out.risk_flags)
        assert any(mv.matched_db_value == "ShopeeFood" for mv in grounded_out.matched_values)

    def test_e2e_b01_schema_catalog_builder_to_grounding_reverse_composite_traversal(
        self,
    ) -> None:
        """Full pipeline from B0.1 SchemaCatalogBuilder -> B0.2 ContractBuilder -> B02ContextAdapter.from_dict -> Grounding."""
        business_id = "biz_e2e_builder"
        tables = [
            TableMetadata(
                name="lines",
                grain="order_line",
                row_count=2,
                profile_is_complete=True,
                columns=(
                    ColumnMetadata(name="order_id", data_type="VARCHAR"),
                    ColumnMetadata(name="line_no", data_type="INTEGER"),
                    ColumnMetadata(name="thanh_tien", data_type="DECIMAL(18,2)", provenance="Doanh thu"),
                ),
                profile_rows=(
                    {"order_id": "O1", "line_no": 1, "thanh_tien": "100.00"},
                    {"order_id": "O1", "line_no": 2, "thanh_tien": "200.00"},
                ),
            ),
            TableMetadata(
                name="allocations",
                grain="allocation",
                row_count=2,
                profile_is_complete=True,
                columns=(
                    ColumnMetadata(name="order_id", data_type="VARCHAR"),
                    ColumnMetadata(name="line_no", data_type="INTEGER"),
                    ColumnMetadata(name="warehouse_code", data_type="VARCHAR", provenance="Mã kho"),
                ),
                profile_rows=(
                    {"order_id": "O1", "line_no": 1, "warehouse_code": "KHO-HN"},
                    {"order_id": "O1", "line_no": 2, "warehouse_code": "KHO-SG"},
                ),
            ),
        ]
        pairs = (("order_id", "order_id"), ("line_no", "line_no"))
        declared = [
            JoinEdge(
                left_table="allocations",
                left_column="order_id",
                right_table="lines",
                right_column="order_id",
                cardinality="many_to_one",
                status="candidate",
                confidence=0.95,
                evidence=("reviewed manifest",),
                additional_key_pairs=(("line_no", "line_no"),),
                relationship_evidence=_trusted_attestation(
                    business_id, "allocations", "lines", pairs, "many_to_one"
                ),
            )
        ]

        catalog = SchemaCatalogBuilder().build(tables, declared, business_id=business_id)
        rules = RuleCatalog(
            business_id=business_id,
            rules=(
                BusinessRule(
                    rule_id="r1",
                    topic="Doanh thu",
                    text="Doanh thu được tính từ cột thanh_tien của bảng lines.",
                    source="rulebook.md",
                    scope="global",
                    precedence=1,
                    required_fields=("lines.thanh_tien",),
                ),
            ),
        )
        ctx = ContractBuilder().build(
            business_id=business_id,
            schema_catalog=catalog,
            rule_catalog=rules,
            data_profiling={
                "allocations": {
                    "samples": [
                        {"order_id": "O1", "line_no": 1, "warehouse_code": "KHO-HN"}
                    ],
                    "columns": {},
                }
            },
        )

        # Round-trip through JSON contract and BusinessContextSchemaReader
        payload = json.loads(json.dumps(ctx.to_dict()))
        adapter = B02ContextAdapter.from_dict(payload)

        engine = QuestionGroundingEngine()
        grounded = engine.ground(
            QuestionRequest(
                question_id="q_rev_comp",
                business_id=business_id,
                question="Tổng doanh thu của kho KHO-HN là bao nhiêu?",
                as_of_date="2026-08-31",
            ),
            context=adapter,
        )

        # Primary table is 'lines' (fact table for revenue), traversed in reverse to 'allocations'
        assert grounded.selected_schema.primary_table == "lines"
        assert len(grounded.selected_schema.join_paths) == 1
        jp = grounded.selected_schema.join_paths[0]
        assert jp.left_table == "lines"
        assert jp.right_table == "allocations"
        assert jp.key_pairs == (("order_id", "order_id"), ("line_no", "line_no"))
        assert jp.cardinality == "one_to_many"
        assert jp.fanout_warning is True

