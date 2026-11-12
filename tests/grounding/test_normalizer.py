"""Tests for Vietnamese shorthand normalization shared by grounding stages."""

import pytest

from datamate.grounding.contracts import OperationKind, QuestionRequest
from datamate.grounding.engine import QuestionGroundingEngine
from datamate.grounding.mock_provider import MockBusinessContextProvider
from datamate.grounding.normalizer import VietnameseQuestionNormalizer
from datamate.grounding.llm_fallback import StructuredLLMParser
from datamate.grounding.parser import QuestionIntentParser


def test_normalizer_expands_compact_and_dotted_vietnamese_shorthand() -> None:
    normalizer = VietnameseQuestionNormalizer()

    assert normalizer.normalize("DT hnay bao nhiêu?") == "doanh thu hôm nay bao nhiêu?"
    assert normalizer.normalize("DT h.nay bao nhiêu?") == "doanh thu hôm nay bao nhiêu?"
    assert normalizer.normalize("SL SP thg này") == "số lượng sản phẩm tháng này"


def test_normalizer_only_replaces_whole_tokens() -> None:
    normalizer = VietnameseQuestionNormalizer()

    assert normalizer.normalize("Sản phẩm SP01 có doanh thu gì?") == (
        "Sản phẩm SP01 có doanh thu gì?"
    )


def test_normalizer_rejects_oversized_input_before_regex_pipeline() -> None:
    normalizer = VietnameseQuestionNormalizer()

    with pytest.raises(ValueError, match="size limit"):
        normalizer.normalize("a" * 8_193)


def test_engine_uses_normalized_question_for_intent_and_temporal_grounding() -> None:
    engine = QuestionGroundingEngine()
    request = QuestionRequest(
        question_id="q-normalized",
        business_id="mock_fnb_003",
        question="Tổng DT hnay là bao nhiêu?",
        as_of_date="2026-08-27",
    )

    grounded = engine.ground(
        request,
        MockBusinessContextProvider.create_fnb_context(),
    )

    assert grounded.question == "Tổng DT hnay là bao nhiêu?"
    assert grounded.intent.normalized_question == (
        "Tổng doanh thu hôm nay là bao nhiêu?"
    )
    assert grounded.intent.operation == OperationKind.SUM
    assert grounded.intent.target_metrics == ("revenue",)
    assert len(grounded.resolved_time_ranges) == 1
    assert grounded.resolved_time_ranges[0].start_date == "2026-08-27"
    assert grounded.resolved_time_ranges[0].end_date == "2026-08-27"


def test_engine_uses_llm_normalized_question_for_temporal_grounding() -> None:
    response = """{
      "normalized_question": "Tổng doanh thu hôm nay là bao nhiêu?",
      "operation": "sum",
      "target_metrics": ["revenue"],
      "answer_type_hint": "number"
    }"""
    parser = QuestionIntentParser(
        llm_fallback=StructuredLLMParser(
            chat_fn=lambda _system, _user: response
        )
    )
    engine = QuestionGroundingEngine(intent_parser=parser)
    request = QuestionRequest(
        question_id="q-llm-normalized",
        business_id="mock_fnb_003",
        question="Tổng doanh thu b.ni là bao nhiêu?",
        as_of_date="2026-08-27",
    )

    grounded = engine.ground(
        request,
        MockBusinessContextProvider.create_fnb_context(),
    )

    assert grounded.intent.used_llm_fallback is True
    assert grounded.intent.normalized_question == (
        "Tổng doanh thu hôm nay là bao nhiêu?"
    )
    assert len(grounded.resolved_time_ranges) == 1
    assert grounded.resolved_time_ranges[0].start_date == "2026-08-27"
