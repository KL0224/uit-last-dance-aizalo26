"""Tests for Component C (Question Grounding) data contracts, protocols, and mock provider."""

from __future__ import annotations

import pytest

from datamate.grounding.contracts import (
    AnswerTypeHint,
    CoverageStatus,
    DateRole,
    EvidenceRequirement,
    FilterCondition,
    GroundedQuestion,
    MatchedValue,
    OperationKind,
    QuestionIntent,
    QuestionRequest,
    ResolvedTimeRange,
    SchemaCandidate,
    SelectedSchema,
)
from datamate.grounding.mock_provider import MockBusinessContextProvider
from datamate.grounding.protocols import BusinessContextProtocol


class TestGroundingContracts:
    """Verify data contracts structure, immutability, and serialization."""

    def test_question_request_validation_and_normalization(self) -> None:
        req = QuestionRequest(
            question_id="q_001",
            business_id="dev_003",
            question="  Trong tháng này, ca tối thu được bao nhiêu tiền mặt?  ",
            as_of_date="2026-08-27",
        )
        assert req.question_id == "q_001"
        assert req.business_id == "dev_003"
        assert req.question == "Trong tháng này, ca tối thu được bao nhiêu tiền mặt?"
        assert req.as_of_date == "2026-08-27"

    def test_question_request_rejects_empty_fields(self) -> None:
        with pytest.raises(ValueError, match="question_id"):
            QuestionRequest(question_id="", business_id="b1", question="abc", as_of_date="2026-08-27")
        with pytest.raises(ValueError, match="as_of_date"):
            QuestionRequest(question_id="q1", business_id="b1", question="abc", as_of_date="27-08-2026")

    def test_resolved_time_range_invariants(self) -> None:
        tr = ResolvedTimeRange(
            raw_expression="tháng này",
            start_date="2026-08-01",
            end_date="2026-08-27",
            date_role=DateRole.PAYMENT_DATE,
            inclusive=True,
            interpretation="Từ đầu tháng 08/2026 đến as_of_date 2026-08-27",
        )
        assert tr.start_date == "2026-08-01"
        assert tr.end_date == "2026-08-27"
        assert tr.date_role == DateRole.PAYMENT_DATE
        assert tr.inclusive is True

        with pytest.raises(ValueError, match="start_date"):
            ResolvedTimeRange(
                raw_expression="lỗi",
                start_date="2026-08-28",
                end_date="2026-08-01",
                date_role=DateRole.ORDER_DATE,
            )

    def test_grounded_question_serialization_and_properties(self) -> None:
        intent = QuestionIntent(
            operation=OperationKind.SUM,
            target_metrics=("cash_collected",),
            entities=("ca tối", "tiền mặt"),
            filters=(
                FilterCondition(
                    field_hint="shift",
                    operator="=",
                    raw_value="ca tối",
                ),
            ),
            group_by=(),
            top_k=None,
            answer_type_hint=AnswerTypeHint.NUMBER,
        )
        time_range = ResolvedTimeRange(
            raw_expression="tháng này",
            start_date="2026-08-01",
            end_date="2026-08-27",
            date_role=DateRole.PAYMENT_DATE,
        )
        schema = SelectedSchema(
            primary_table="shift_payments",
            tables=(
                SchemaCandidate(
                    table_name="shift_payments",
                    relevant_columns=("shift_name", "payment_method", "amount", "payment_date"),
                    grain="payment_event",
                    score=0.95,
                    rationale="Bảng thu tiền theo ca khớp với metric cash_collected",
                ),
            ),
            join_paths=(),
            fanout_warning=False,
        )
        matched = (
            MatchedValue(
                raw_text="ca tối",
                table_name="shift_payments",
                column_name="shift_name",
                matched_db_value="Ca tối",
                match_type="exact_normalized",
                confidence=1.0,
            ),
        )
        ev_req = (
            EvidenceRequirement(
                capability_key="payments",
                required_concepts=("cash_collected", "shift"),
                is_mandatory=True,
            ),
        )

        grounded = GroundedQuestion(
            question_id="q_001",
            business_id="dev_003",
            question="Trong tháng này, ca tối thu được bao nhiêu tiền mặt?",
            as_of_date="2026-08-27",
            intent=intent,
            resolved_time_ranges=(time_range,),
            selected_schema=schema,
            matched_values=matched,
            answer_type_hint=AnswerTypeHint.NUMBER,
            evidence_requirements=ev_req,
            coverage_status=CoverageStatus.SUPPORTED,
        )

        assert grounded.is_directly_unanswerable is False
        payload = grounded.to_dict()
        assert payload["question_id"] == "q_001"
        assert payload["intent"]["operation"] == "sum"
        assert payload["coverage_status"] == "supported"
        assert payload["selected_schema"]["primary_table"] == "shift_payments"


class TestMockBusinessContextProvider:
    """Verify mock contexts satisfy BusinessContextProtocol for independent testing."""

    def test_fnb_context_satisfies_protocol(self) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        assert isinstance(ctx, BusinessContextProtocol)
        assert ctx.business_id == "mock_fnb_003"
        table_names = [t.name for t in ctx.get_tables()]
        assert "orders" in table_names
        assert "order_items" in table_names
        assert "shift_payments" in table_names
        assert ctx.get_capability_status("sales_by_product") == "supported"
        assert ctx.get_capability_status("historical_stock") == "unsupported"

    def test_retail_no_customer_context_for_unanswerable_testing(self) -> None:
        ctx = MockBusinessContextProvider.create_anonymous_retail_context()
        assert isinstance(ctx, BusinessContextProtocol)
        assert ctx.get_capability_status("customers") == "unsupported"
        assert ctx.get_capability_status("cost") == "unsupported"
