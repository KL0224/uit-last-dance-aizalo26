"""Tests for C3 (Schema Grounder) and C4 (Value Grounder)."""

from __future__ import annotations

import pytest

from datamate.grounding.contracts import (
    AnswerTypeHint,
    FilterCondition,
    OperationKind,
    QuestionIntent,
)
from datamate.grounding.mock_provider import MockBusinessContextProvider
from datamate.grounding.schema_grounder import SchemaGrounder
from datamate.grounding.value_grounder import ValueGrounder


class TestSchemaAndValueGrounder:
    """Verify C3 ranks tables/columns/joins and C4 links Vietnamese entities to DB values."""

    @pytest.fixture()
    def schema_grounder(self) -> SchemaGrounder:
        return SchemaGrounder()

    @pytest.fixture()
    def value_grounder(self) -> ValueGrounder:
        return ValueGrounder()

    def test_c3_selects_shift_payments_for_cash_collected(
        self, schema_grounder: SchemaGrounder
    ) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        intent = QuestionIntent(
            operation=OperationKind.SUM,
            target_metrics=("cash_collected",),
            entities=("ca tối", "tiền mặt"),
            answer_type_hint=AnswerTypeHint.NUMBER,
        )
        selected = schema_grounder.ground(
            question="Trong tháng này, ca tối thu được bao nhiêu tiền mặt?",
            intent=intent,
            context=ctx,
        )
        assert selected.primary_table == "shift_payments"
        primary_cand = selected.tables[0]
        assert primary_cand.table_name == "shift_payments"
        assert "collected_amount" in primary_cand.relevant_columns
        assert "payment_date" in primary_cand.relevant_columns
        assert "shift_name" in primary_cand.relevant_columns
        assert "payment_method" in primary_cand.relevant_columns

    def test_c3_builds_join_path_for_customer_revenue(
        self, schema_grounder: SchemaGrounder
    ) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        intent = QuestionIntent(
            operation=OperationKind.ARGMAX,
            target_metrics=("revenue",),
            group_by=("customer",),
            answer_type_hint=AnswerTypeHint.STRING,
        )
        selected = schema_grounder.ground(
            question="Khách hàng nào mua nhiều tiền nhất tháng này?",
            intent=intent,
            context=ctx,
        )
        assert selected.primary_table == "order_items"
        table_names = [t.table_name for t in selected.tables]
        assert "order_items" in table_names
        assert "orders" in table_names
        assert "customers" in table_names
        assert len(selected.join_paths) >= 2

    def test_c4_links_shift_payment_and_product_values(
        self,
        schema_grounder: SchemaGrounder,
        value_grounder: ValueGrounder,
    ) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        intent = QuestionIntent(
            operation=OperationKind.SUM,
            target_metrics=("cash_collected",),
            entities=("ca tối", "tiền mặt"),
            filters=(
                FilterCondition(field_hint="shift_name", operator="=", raw_value="ca tối"),
                FilterCondition(field_hint="payment_method", operator="=", raw_value="tiền mặt"),
            ),
            answer_type_hint=AnswerTypeHint.NUMBER,
        )
        schema = schema_grounder.ground(
            question="Trong tháng này, ca tối thu được bao nhiêu tiền mặt?",
            intent=intent,
            context=ctx,
        )
        matched_values, updated_filters = value_grounder.ground(
            question="Trong tháng này, ca tối thu được bao nhiêu tiền mặt?",
            intent=intent,
            selected_schema=schema,
            context=ctx,
        )
        db_vals = {m.raw_text: (m.table_name, m.column_name, m.matched_db_value) for m in matched_values}
        assert db_vals["ca tối"] == ("shift_payments", "shift_name", "Ca tối")
        assert db_vals["tiền mặt"] == ("shift_payments", "payment_method", "Tiền mặt")
        assert all(f.grounded_value is not None for f in updated_filters)

    def test_c4_matches_sample_values_and_unaccented_text(
        self,
        schema_grounder: SchemaGrounder,
        value_grounder: ValueGrounder,
    ) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        intent = QuestionIntent(
            operation=OperationKind.SUM,
            target_metrics=("sold_qty",),
            entities=("Cà phê sữa (L)",),
            filters=(
                FilterCondition(
                    field_hint="product_name",
                    operator="LIKE",
                    raw_value="Cà phê sữa (L)",
                ),
            ),
            answer_type_hint=AnswerTypeHint.NUMBER,
        )
        schema = schema_grounder.ground(
            question="Tháng này bán được bao nhiêu ly Cà phê sữa (L)?",
            intent=intent,
            context=ctx,
        )
        matched_values, _ = value_grounder.ground(
            question="Tháng này bán được bao nhiêu ly Cà phê sữa (L)?",
            intent=intent,
            selected_schema=schema,
            context=ctx,
        )
        assert any(
            m.table_name == "order_items"
            and m.column_name == "product_name"
            and m.matched_db_value == "Cà phê sữa (L)"
            for m in matched_values
        )

