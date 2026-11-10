"""Tests for C1: Question Parser & Intent Extractor (Rule Fast-Path + 3B LLM Fallback)."""

from __future__ import annotations

import logging

import pytest

from datamate.grounding.contracts import AnswerTypeHint, OperationKind, QuestionIntent
from datamate.grounding.llm_fallback import StructuredLLMParser
from datamate.grounding.mock_provider import MockBusinessContextProvider
from datamate.grounding.parser import QuestionIntentParser


class Fake3BModelClient:
    """Fake 3B model client returning JSON strings for testing LLM fallback."""

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.call_count = 0
        self.last_system_prompt = ""
        self.last_user_prompt = ""

    def __call__(self, system_prompt: str, user_prompt: str) -> str:
        self.call_count += 1
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        return self.response_text


class TestQuestionIntentParser:
    """Verify C1 extracts operation, metrics, filters, grouping, top-k, and answer type hints."""

    @pytest.fixture()
    def parser(self) -> QuestionIntentParser:
        return QuestionIntentParser()

    def test_sum_cash_collected_by_shift(self, parser: QuestionIntentParser) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        intent = parser.parse(
            "Trong tháng này, ca tối thu được bao nhiêu tiền mặt?",
            as_of_date="2026-08-27",
            context=ctx,
        )
        assert intent.operation == OperationKind.SUM
        assert "cash_collected" in intent.target_metrics
        assert intent.answer_type_hint == AnswerTypeHint.NUMBER
        assert "ca tối" in intent.entities
        assert "tiền mặt" in intent.entities
        assert intent.used_llm_fallback is False

    def test_top_k_popular_products_count_distinct(self, parser: QuestionIntentParser) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        intent = parser.parse(
            "Trong tháng này, năm sản phẩm được ưa chuộng nhất là gì?",
            as_of_date="2026-08-27",
            context=ctx,
        )
        assert intent.operation == OperationKind.TOP_K
        assert intent.top_k == 5
        assert "distinct_product_orders" in intent.target_metrics
        assert "product" in intent.group_by
        assert intent.answer_type_hint == AnswerTypeHint.LIST

    def test_argmax_customer_and_date_answer_type(self, parser: QuestionIntentParser) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        intent_cust = parser.parse(
            "Khách hàng nào mua nhiều tiền nhất tháng này?",
            as_of_date="2026-08-27",
            context=ctx,
        )
        assert intent_cust.operation == OperationKind.ARGMAX
        assert "revenue" in intent_cust.target_metrics
        assert "customer" in intent_cust.group_by
        assert intent_cust.answer_type_hint == AnswerTypeHint.STRING

        intent_date = parser.parse(
            "Ngày nào trong tháng này có doanh thu cao nhất?",
            as_of_date="2026-08-27",
            context=ctx,
        )
        assert intent_date.operation == OperationKind.ARGMAX
        assert intent_date.answer_type_hint == AnswerTypeHint.DATE
        assert "date" in intent_date.group_by

    def test_percent_change_and_having_minimum_orders(self, parser: QuestionIntentParser) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        intent_pct = parser.parse(
            "Doanh thu tháng này tăng hay giảm bao nhiêu phần trăm so với tháng trước?",
            as_of_date="2026-08-27",
            context=ctx,
        )
        assert intent_pct.operation == OperationKind.PERCENT_CHANGE
        assert intent_pct.answer_type_hint == AnswerTypeHint.PERCENT

        intent_having = parser.parse(
            "Có bao nhiêu khách hàng mua ít nhất 3 đơn trong tháng này?",
            as_of_date="2026-08-27",
            context=ctx,
        )
        assert intent_having.operation in {OperationKind.COUNT, OperationKind.COUNT_DISTINCT}
        having_filters = [f for f in intent_having.filters if f.is_having]
        assert len(having_filters) == 1
        assert having_filters[0].operator == ">="
        assert having_filters[0].raw_value == 3

    def test_boolean_existence_question(self, parser: QuestionIntentParser) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        intent = parser.parse(
            "Tháng này có đơn hàng nào bị hủy không?",
            as_of_date="2026-08-27",
            context=ctx,
        )
        assert intent.operation == OperationKind.EXISTENCE
        assert intent.answer_type_hint == AnswerTypeHint.BOOLEAN

    def test_product_with_size_entity_extraction(self, parser: QuestionIntentParser) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        intent = parser.parse(
            "Tháng này bán được bao nhiêu ly Cà phê sữa (L)?",
            as_of_date="2026-08-27",
            context=ctx,
        )
        assert intent.operation == OperationKind.SUM
        assert "sold_qty" in intent.target_metrics
        assert any("cà phê sữa (l)" in e.lower() for e in intent.entities)

    def test_llm_3b_fallback_when_question_is_ambiguous(self) -> None:
        fake_json = """```json
        {
          "operation": "ratio",
          "target_metrics": ["revenue"],
          "entities": ["nhóm VIP"],
          "group_by": ["customer"],
          "top_k": null,
          "answer_type_hint": "percent"
        }
        ```"""
        fake_client = Fake3BModelClient(fake_json)
        llm_parser = StructuredLLMParser(chat_fn=fake_client)
        parser = QuestionIntentParser(llm_fallback=llm_parser, fallback_threshold=0.75)

        ctx = MockBusinessContextProvider.create_fnb_context()
        intent = parser.parse(
            "Mức độ đóng góp tương đối của tệp VIP vào giỏ hàng chung?",
            as_of_date="2026-08-27",
            context=ctx,
        )
        assert intent.used_llm_fallback is True
        assert fake_client.call_count == 1
        assert intent.operation == OperationKind.RATIO
        assert intent.answer_type_hint == AnswerTypeHint.PERCENT
        assert "nhóm VIP" in intent.entities

    def test_llm_can_return_normalized_question_for_downstream_stages(self) -> None:
        fake_client = Fake3BModelClient(
            """{
              "normalized_question": "Tổng doanh thu hôm nay là bao nhiêu?",
              "operation": "sum",
              "target_metrics": ["revenue"],
              "answer_type_hint": "number"
            }"""
        )
        parser = StructuredLLMParser(chat_fn=fake_client)

        intent = parser.extract_intent(
            question="Tổng doanh thu b.ni là bao nhiêu?",
            as_of_date="2026-08-27",
            available_metrics=("revenue",),
            available_tables=("orders",),
        )

        assert intent.normalized_question == "Tổng doanh thu hôm nay là bao nhiêu?"

    def test_llm_prompt_trims_large_registry_to_token_budget(self) -> None:
        fake_client = Fake3BModelClient(
            '{"operation":"sum","target_metrics":["revenue"],'
            '"answer_type_hint":"number"}'
        )
        parser = StructuredLLMParser(
            chat_fn=fake_client,
            token_count_fn=lambda _system, user: len(user),
            max_input_tokens=260,
        )

        intent = parser.extract_intent(
            question="Tổng doanh thu hôm nay là bao nhiêu?",
            as_of_date="2026-08-27",
            available_metrics=(*(f"metric_{i:03d}" for i in range(100)), "revenue"),
            available_tables=tuple(f"business_table_{i:03d}" for i in range(100)),
        )

        assert intent.target_metrics == ("revenue",)
        assert len(fake_client.last_user_prompt) <= 260
        assert "revenue" in fake_client.last_user_prompt
        assert "metric_099" not in fake_client.last_user_prompt
        assert "business_table_099" not in fake_client.last_user_prompt

    def test_llm_prompt_rejects_question_that_cannot_fit_token_budget(self) -> None:
        fake_client = Fake3BModelClient(
            '{"operation":"lookup","answer_type_hint":"string"}'
        )
        parser = StructuredLLMParser(
            chat_fn=fake_client,
            token_count_fn=lambda _system, user: len(user),
            max_input_tokens=120,
        )

        with pytest.raises(ValueError, match="prompt exceeds the input token budget"):
            parser.extract_intent(
                question="câu hỏi rất dài " * 30,
                as_of_date="2026-08-27",
                available_metrics=("revenue",),
                available_tables=("orders",),
            )

        assert fake_client.call_count == 0

    def test_fast_path_skips_llm_when_semantic_evidence_is_complete(self) -> None:
        fake_client = Fake3BModelClient(
            '{"operation":"lookup","answer_type_hint":"string"}'
        )
        parser = QuestionIntentParser(
            llm_fallback=StructuredLLMParser(chat_fn=fake_client)
        )

        intent = parser.parse(
            "Trong tháng này, ca tối thu được bao nhiêu tiền mặt?",
            as_of_date="2026-08-27",
            context=MockBusinessContextProvider.create_fnb_context(),
        )

        assert intent.used_llm_fallback is False
        assert fake_client.call_count == 0

    def test_missing_metric_for_ranking_forces_llm_fallback(self) -> None:
        fake_client = Fake3BModelClient(
            """{
              "operation": "argmax",
              "target_metrics": ["revenue"],
              "entities": [],
              "group_by": ["product"],
              "top_k": null,
              "answer_type_hint": "string"
            }"""
        )
        parser = QuestionIntentParser(
            llm_fallback=StructuredLLMParser(chat_fn=fake_client)
        )

        intent = parser.parse(
            "Mục nào cao nhất trong tháng này?",
            as_of_date="2026-08-27",
            context=MockBusinessContextProvider.create_fnb_context(),
        )

        assert intent.used_llm_fallback is True
        assert intent.target_metrics == ("revenue",)
        assert fake_client.call_count == 1

    def test_unresolved_emoji_forces_llm_fallback(self) -> None:
        fake_client = Fake3BModelClient(
            """{
              "operation": "argmax",
              "target_metrics": ["revenue"],
              "entities": ["tiền mặt"],
              "group_by": ["date"],
              "top_k": null,
              "answer_type_hint": "date"
            }"""
        )
        parser = QuestionIntentParser(
            llm_fallback=StructuredLLMParser(chat_fn=fake_client)
        )

        intent = parser.parse(
            "Ngày nào có doanh thu 💵 cao nhất tháng này?",
            as_of_date="2026-08-27",
            context=MockBusinessContextProvider.create_fnb_context(),
        )

        assert intent.used_llm_fallback is True
        assert fake_client.call_count == 1

    def test_dotted_shorthand_forces_llm_fallback(self) -> None:
        fake_client = Fake3BModelClient(
            """{
              "operation": "sum",
              "target_metrics": ["revenue"],
              "answer_type_hint": "number"
            }"""
        )
        parser = QuestionIntentParser(
            llm_fallback=StructuredLLMParser(chat_fn=fake_client)
        )

        intent = parser.parse(
            "Tổng doanh thu h.nay là bao nhiêu?",
            as_of_date="2026-08-27",
            context=MockBusinessContextProvider.create_fnb_context(),
        )

        assert intent.used_llm_fallback is True
        assert "UNRESOLVED_SHORTHAND" in intent.fallback_reasons

    def test_compact_vietnamese_shorthand_forces_llm_fallback(self) -> None:
        fake_client = Fake3BModelClient(
            """{
              "operation": "sum",
              "target_metrics": ["revenue"],
              "answer_type_hint": "number"
            }"""
        )
        parser = QuestionIntentParser(
            llm_fallback=StructuredLLMParser(chat_fn=fake_client)
        )

        intent = parser.parse(
            "Tổng doanh thu hnay là bao nhiêu?",
            as_of_date="2026-08-27",
            context=MockBusinessContextProvider.create_fnb_context(),
        )

        assert intent.used_llm_fallback is True
        assert "UNRESOLVED_SHORTHAND" in intent.fallback_reasons

    def test_llm_rejects_metric_outside_available_registry(self) -> None:
        fake_client = Fake3BModelClient(
            """{
              "operation": "sum",
              "target_metrics": ["invented_metric"],
              "answer_type_hint": "number"
            }"""
        )
        parser = StructuredLLMParser(chat_fn=fake_client)

        with pytest.raises(ValueError, match="unavailable metrics"):
            parser.extract_intent(
                question="Tổng chỉ số lạ là bao nhiêu?",
                as_of_date="2026-08-27",
                available_metrics=("revenue",),
                available_tables=("orders",),
            )

        with pytest.raises(ValueError, match="unavailable metrics"):
            parser.extract_intent(
                question="Tổng chỉ số lạ là bao nhiêu?",
                as_of_date="2026-08-27",
                available_metrics=(),
                available_tables=("orders",),
            )

    def test_known_uppercase_alias_does_not_force_llm(self) -> None:
        fake_client = Fake3BModelClient(
            '{"operation":"lookup","answer_type_hint":"string"}'
        )
        parser = QuestionIntentParser(
            llm_fallback=StructuredLLMParser(chat_fn=fake_client)
        )

        intent = parser.parse(
            "Tổng tiền CK tháng này là bao nhiêu?",
            as_of_date="2026-08-27",
            context=MockBusinessContextProvider.create_fnb_context(),
        )

        assert intent.used_llm_fallback is False
        assert "ck" in intent.entities
        assert fake_client.call_count == 0

    def test_incomplete_llm_intent_safely_degrades_to_rule_result(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        fake_client = Fake3BModelClient(
            """{
              "operation": "argmax",
              "target_metrics": [],
              "entities": [],
              "group_by": ["product"],
              "answer_type_hint": "string"
            }"""
        )
        parser = QuestionIntentParser(
            llm_fallback=StructuredLLMParser(chat_fn=fake_client)
        )

        with caplog.at_level(logging.WARNING, logger="datamate.grounding.parser"):
            intent = parser.parse(
                "Mục nào cao nhất trong tháng này?",
                as_of_date="2026-08-27",
                context=MockBusinessContextProvider.create_fnb_context(),
            )

        assert intent.used_llm_fallback is False
        assert "LLM_FALLBACK_FAILED" in intent.fallback_reasons
        record = next(
            item
            for item in caplog.records
            if item.getMessage() == "grounding_llm_fallback_failed"
        )
        assert record.fallback_reasons == ("MISSING_REQUIRED_METRIC",)
        assert record.error_type == "ValueError"

    @pytest.mark.parametrize(
        ("payload", "error"),
        [
            (
                '{"operation":"lookup","entities":"not-a-list",'
                '"answer_type_hint":"string"}',
                "entities must be a list",
            ),
            (
                '{"operation":"lookup","group_by":["secret_dimension"],'
                '"answer_type_hint":"string"}',
                "unsupported group_by",
            ),
            (
                '{"operation":"lookup","filters":[{"field_hint":"status",'
                '"operator":"DROP","raw_value":"x"}],'
                '"answer_type_hint":"string"}',
                "unsupported filter operator",
            ),
            (
                '{"normalized_question":["not text"],'
                '"operation":"lookup","answer_type_hint":"string"}',
                "normalized_question must be nonempty text",
            ),
        ],
    )
    def test_llm_output_is_validated_as_untrusted_data(
        self, payload: str, error: str
    ) -> None:
        parser = StructuredLLMParser(chat_fn=Fake3BModelClient(payload))

        with pytest.raises(ValueError, match=error):
            parser.extract_intent(
                question="Tra cứu dữ liệu",
                as_of_date="2026-08-27",
                available_metrics=("revenue",),
                available_tables=("orders",),
            )
