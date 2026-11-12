"""Tests for C5: Answerability Precheck."""

from __future__ import annotations

import pytest

from datamate.grounding.answerability import AnswerabilityPrechecker
from datamate.grounding.contracts import (
    AnswerTypeHint,
    CoverageStatus,
    DateRole,
    OperationKind,
    QuestionIntent,
    ResolvedTimeRange,
)
from datamate.grounding.mock_provider import MockBusinessContextProvider
from datamate.grounding.schema_grounder import SchemaGrounder


class TestAnswerabilityPrechecker:
    """Verify C5 detects true UNSUPPORTED cases while avoiding false unanswerables."""

    @pytest.fixture()
    def prechecker(self) -> AnswerabilityPrechecker:
        return AnswerabilityPrechecker()

    @pytest.fixture()
    def schema_grounder(self) -> SchemaGrounder:
        return SchemaGrounder()

    def test_supported_when_capability_and_date_coverage_present(
        self,
        prechecker: AnswerabilityPrechecker,
        schema_grounder: SchemaGrounder,
    ) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        intent = QuestionIntent(
            operation=OperationKind.SUM,
            target_metrics=("cash_collected",),
            entities=("ca tối", "tiền mặt"),
            answer_type_hint=AnswerTypeHint.NUMBER,
        )
        schema = schema_grounder.ground(
            "Trong tháng này, ca tối thu được bao nhiêu tiền mặt?", intent, ctx
        )
        time_ranges = (
            ResolvedTimeRange(
                raw_expression="tháng này",
                start_date="2026-08-01",
                end_date="2026-08-27",
                date_role=DateRole.PAYMENT_DATE,
            ),
        )
        reqs, status, proof, flags = prechecker.evaluate(
            question="Trong tháng này, ca tối thu được bao nhiêu tiền mặt?",
            intent=intent,
            resolved_time_ranges=time_ranges,
            selected_schema=schema,
            context=ctx,
        )
        assert status == CoverageStatus.SUPPORTED
        assert proof is None
        assert any(r.capability_key == "payments" for r in reqs)
        assert flags == ()

    def test_unsupported_when_customer_identity_missing_in_anonymous_retail(
        self,
        prechecker: AnswerabilityPrechecker,
        schema_grounder: SchemaGrounder,
    ) -> None:
        ctx = MockBusinessContextProvider.create_anonymous_retail_context()
        intent = QuestionIntent(
            operation=OperationKind.ARGMAX,
            target_metrics=("revenue",),
            group_by=("customer",),
            answer_type_hint=AnswerTypeHint.STRING,
        )
        schema = schema_grounder.ground(
            "Khách hàng nào mua nhiều tiền nhất tháng này?", intent, ctx
        )
        _, status, proof, _ = prechecker.evaluate(
            question="Khách hàng nào mua nhiều tiền nhất tháng này?",
            intent=intent,
            resolved_time_ranges=(),
            selected_schema=schema,
            context=ctx,
        )
        assert status == CoverageStatus.UNSUPPORTED
        assert proof is not None
        assert proof.capability_key == "customers"
        assert proof.checked_all_sources is True
        assert "pos_receipts" in proof.checked_tables
        assert "customer" in proof.missing_fields[0]

    def test_unsupported_when_cost_or_historical_stock_missing(
        self,
        prechecker: AnswerabilityPrechecker,
        schema_grounder: SchemaGrounder,
    ) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        intent = QuestionIntent(
            operation=OperationKind.SUM,
            target_metrics=("gross_profit", "cost"),
            answer_type_hint=AnswerTypeHint.NUMBER,
        )
        schema = schema_grounder.ground(
            "Lợi nhuận gộp tháng này là bao nhiêu?", intent, ctx
        )
        _, status, proof, _ = prechecker.evaluate(
            question="Lợi nhuận gộp tháng này là bao nhiêu?",
            intent=intent,
            resolved_time_ranges=(),
            selected_schema=schema,
            context=ctx,
        )
        assert status == CoverageStatus.UNSUPPORTED
        assert proof is not None
        assert proof.capability_key == "cost"
        assert proof.checked_all_sources is True

    def test_semi_structured_size_or_topping_is_not_falsely_unsupported(
        self,
        prechecker: AnswerabilityPrechecker,
        schema_grounder: SchemaGrounder,
    ) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        intent = QuestionIntent(
            operation=OperationKind.SUM,
            target_metrics=("sold_qty",),
            entities=("Cà phê sữa (L)",),
            answer_type_hint=AnswerTypeHint.NUMBER,
        )
        schema = schema_grounder.ground(
            "Tháng này bán được bao nhiêu ly Cà phê sữa (L)?", intent, ctx
        )
        _, status, proof, _ = prechecker.evaluate(
            question="Tháng này bán được bao nhiêu ly Cà phê sữa (L)?",
            intent=intent,
            resolved_time_ranges=(),
            selected_schema=schema,
            context=ctx,
        )
        assert status == CoverageStatus.SUPPORTED
        assert proof is None

