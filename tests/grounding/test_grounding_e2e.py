"""End-to-end tests for QuestionGroundingEngine and B02/B03/B05 Pipeline Adapters."""

from __future__ import annotations

import time

import pytest

from datamate.ingestion.contracts import ColumnMetadata, JoinEdge, SchemaCatalog, TableMetadata
from datamate.context.contracts import BusinessContext, BusinessRule, RuleCatalog
from datamate.grounding.adapters import B02ContextAdapter, GroundingToPlannerAdapter
from datamate.grounding.contracts import (
    AnswerTypeHint,
    CoverageStatus,
    DateRole,
    OperationKind,
    QuestionRequest,
)
from datamate.grounding.engine import QuestionGroundingEngine
from datamate.grounding.mock_provider import MockBusinessContextProvider
from datamate.grounding.protocols import BusinessContextProtocol


class TestQuestionGroundingEngineE2E:
    """Verify full C1->C2->C3->C4->C5 execution, latency, determinism, and B0 adapters."""

    @pytest.fixture()
    def engine(self) -> QuestionGroundingEngine:
        return QuestionGroundingEngine()

    def test_e2e_supported_shift_cash_question(self, engine: QuestionGroundingEngine) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        req = QuestionRequest(
            question_id="q_dev003_01",
            business_id="mock_fnb_003",
            question="Trong tháng này, ca tối thu được bao nhiêu tiền mặt?",
            as_of_date="2026-08-27",
        )
        grounded = engine.ground(req, ctx)

        assert grounded.question_id == "q_dev003_01"
        assert grounded.intent.operation == OperationKind.SUM
        assert "cash_collected" in grounded.intent.target_metrics
        assert len(grounded.resolved_time_ranges) == 1
        assert grounded.resolved_time_ranges[0].start_date == "2026-08-01"
        assert grounded.resolved_time_ranges[0].end_date == "2026-08-27"
        assert grounded.resolved_time_ranges[0].date_role == DateRole.PAYMENT_DATE
        assert grounded.selected_schema.primary_table == "shift_payments"
        assert grounded.coverage_status == CoverageStatus.SUPPORTED
        assert grounded.is_directly_unanswerable is False
        assert grounded.answer_type_hint == AnswerTypeHint.NUMBER

        # Verify Planner prompt hint generation
        hint_text = GroundingToPlannerAdapter.format_grounded_hint_for_planner(grounded)
        assert "2026-08-01" in hint_text
        assert "2026-08-27" in hint_text
        assert "shift_payments" in hint_text
        assert "Ca tối" in hint_text
        assert "Tiền mặt" in hint_text

    def test_e2e_unsupported_question_shortcuts_to_b05_evidence_proof(
        self, engine: QuestionGroundingEngine
    ) -> None:
        ctx = MockBusinessContextProvider.create_anonymous_retail_context()
        req = QuestionRequest(
            question_id="q_ua_01",
            business_id="mock_retail_anon",
            question="Khách hàng nào mua nhiều tiền nhất tháng này?",
            as_of_date="2026-08-27",
        )
        grounded = engine.ground(req, ctx)

        assert grounded.coverage_status == CoverageStatus.UNSUPPORTED
        assert grounded.is_directly_unanswerable is True
        assert grounded.answer_type_hint == AnswerTypeHint.UNANSWERABLE
        assert grounded.missing_evidence_proof is not None

        b05_proof = GroundingToPlannerAdapter.to_b05_evidence_proof(grounded)
        assert b05_proof.capability_status == "unsupported"
        assert b05_proof.checked_all_sources is True
        assert b05_proof.source_kind == "catalog_verified"
        assert "customer" in b05_proof.missing_fields[0]

    def test_b02_business_context_adapter_compatibility(
        self, engine: QuestionGroundingEngine
    ) -> None:
        b01_schema = SchemaCatalog(
            tables=(
                TableMetadata(
                    name="don_hang",
                    grain="order",
                    row_count=200,
                    columns=(
                        ColumnMetadata(name="ma_don", data_type="VARCHAR"),
                        ColumnMetadata(name="ngay_ban", data_type="DATE"),
                        ColumnMetadata(name="tong_tien", data_type="DOUBLE"),
                    ),
                    profile_rows=(
                        {"ma_don": "DH01", "ngay_ban": "2026-08-10", "tong_tien": 150000.0},
                    ),
                ),
            ),
            join_graph=(
                JoinEdge(
                    left_table="don_hang",
                    left_column="ma_don",
                    right_table="don_hang",
                    right_column="ma_don",
                    cardinality="one_to_one",
                    status="validated",
                    confidence=1.0,
                    evidence=("pk",),
                ),
            ),
        )
        b02_rules = RuleCatalog(
            business_id="biz_real_01",
            rules=(
                BusinessRule(
                    rule_id="r1",
                    text="Doanh thu tính trên cột tong_tien.",
                    source="README.md",
                    scope="business_override",
                    precedence=10,
                ),
            ),
        )
        b02_ctx = BusinessContext(
            contract_version="1.0",
            business_id="biz_real_01",
            schema_catalog=b01_schema,
            rule_catalog=b02_rules,
            answerability_constraints={"customers": "unsupported", "sales_by_product": "supported"},
        )

        adapted = B02ContextAdapter(b02_ctx)
        assert isinstance(adapted, BusinessContextProtocol)
        assert adapted.business_id == "biz_real_01"
        assert len(adapted.get_tables()) == 1
        assert adapted.get_capability_status("customers") == "unsupported"

        req = QuestionRequest(
            question_id="q_b02_01",
            business_id="biz_real_01",
            question="Tổng doanh thu tháng này là bao nhiêu?",
            as_of_date="2026-08-27",
        )
        grounded = engine.ground(req, adapted)
        assert grounded.coverage_status == CoverageStatus.SUPPORTED
        assert grounded.selected_schema.primary_table == "don_hang"

    def test_determinism_and_latency_budget(self, engine: QuestionGroundingEngine) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        req = QuestionRequest(
            question_id="q_perf",
            business_id="mock_fnb_003",
            question="Trong tháng này, năm sản phẩm được ưa chuộng nhất là gì?",
            as_of_date="2026-08-27",
        )
        t0 = time.perf_counter()
        g1 = engine.ground(req, ctx)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        g2 = engine.ground(req, ctx)

        assert g1.to_dict() == g2.to_dict()
        assert elapsed_ms < 100.0

