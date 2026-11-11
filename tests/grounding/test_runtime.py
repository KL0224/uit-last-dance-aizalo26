"""Contract tests for the Question Grounding runtime boundary."""

from __future__ import annotations

import json
from typing import Any

import pytest

import datamate.grounding as grounding_api
from datamate.context.runtime import BusinessContextRuntimeLoader
from datamate.grounding.contracts import GroundedQuestion, QuestionRequest
from datamate.grounding.engine import QuestionGroundingEngine
from datamate.grounding.mock_provider import MockBusinessContextProvider
from datamate.grounding.protocols import BusinessContextProtocol
from datamate.grounding.runtime import (
    GROUNDING_BUSINESS_MISMATCH,
    GROUNDING_CONTEXT_INVALID,
    GROUNDING_FAILED,
    GROUNDING_REQUEST_INVALID,
    QuestionGroundingRuntime,
    QuestionGroundingRuntimeError,
)


class _RecordingEngine:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def ground(self, request: Any, context: Any) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        raise AssertionError("ground() should not have been called")


class _CapturingEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[QuestionRequest, object]] = []
        self._delegate = QuestionGroundingEngine()

    def ground(
        self,
        request: QuestionRequest,
        context: BusinessContextProtocol,
    ) -> GroundedQuestion:
        self.calls.append((request, context))
        return self._delegate.ground(request, context)


class _BlankBusinessContext:
    business_id = "   "

    def get_tables(self) -> tuple[()]:
        return ()

    def get_join_edges(self) -> tuple[()]:
        return ()

    def get_metrics(self) -> tuple[()]:
        return ()

    def get_capability_status(self, capability_key: str) -> str:
        return "unknown"

    def get_calendar_events(self) -> tuple[()]:
        return ()

    def get_active_rules(self, topic: str | None = None) -> tuple[()]:
        return ()

    def get_value_aliases(self) -> dict[str, tuple[str, str, Any]]:
        return {}


class _ExplodingIdentityContext(_BlankBusinessContext):
    @property
    def business_id(self) -> str:
        raise RuntimeError("context payload must remain private")


@pytest.mark.parametrize(
    ("overrides", "expected_cause"),
    [
        ({"question_id": "   "}, ValueError),
        ({"business_id": ""}, ValueError),
        ({"question": "  "}, ValueError),
        ({"as_of_date": "2026-02-30"}, ValueError),
    ],
)
def test_invalid_request_is_rejected_before_engine(
    overrides: dict[str, str],
    expected_cause: type[Exception],
) -> None:
    engine = _RecordingEngine()
    runtime = QuestionGroundingRuntime(engine=engine)
    request = {
        "question_id": "q-invalid",
        "business_id": "mock_fnb_003",
        "question": "Doanh thu tháng này?",
        "as_of_date": "2026-08-27",
    }
    request.update(overrides)

    with pytest.raises(QuestionGroundingRuntimeError) as captured:
        runtime.ground_question(
            **request,
            context=MockBusinessContextProvider.create_fnb_context(),
        )

    assert captured.value.code == GROUNDING_REQUEST_INVALID
    assert isinstance(captured.value.__cause__, expected_cause)
    assert engine.calls == 0


@pytest.mark.parametrize(
    "context",
    [object(), _BlankBusinessContext(), _ExplodingIdentityContext()],
)
def test_invalid_context_is_rejected_before_engine(context: object) -> None:
    engine = _RecordingEngine()
    runtime = QuestionGroundingRuntime(engine=engine)

    with pytest.raises(QuestionGroundingRuntimeError) as captured:
        runtime.ground_question(
            question_id="q-context",
            business_id="mock_fnb_003",
            question="Doanh thu tháng này?",
            as_of_date="2026-08-27",
            context=context,
        )

    assert captured.value.code == GROUNDING_CONTEXT_INVALID
    assert engine.calls == 0


def test_business_mismatch_is_rejected_before_engine() -> None:
    engine = _RecordingEngine()
    runtime = QuestionGroundingRuntime(engine=engine)

    with pytest.raises(QuestionGroundingRuntimeError) as captured:
        runtime.ground_question(
            question_id="q-mismatch",
            business_id="another-business",
            question="Doanh thu tháng này?",
            as_of_date="2026-08-27",
            context=MockBusinessContextProvider.create_fnb_context(),
        )

    assert captured.value.code == GROUNDING_BUSINESS_MISMATCH
    assert engine.calls == 0


def test_engine_failure_is_classified_without_payload_leakage() -> None:
    root_cause = RuntimeError("engine exploded on a sampled database value")
    engine = _RecordingEngine(error=root_cause)
    runtime = QuestionGroundingRuntime(engine=engine)
    secret_question = "Doanh thu của khách hàng SECRET-CUSTOMER là bao nhiêu?"

    with pytest.raises(QuestionGroundingRuntimeError) as captured:
        runtime.ground_question(
            question_id="q-failure",
            business_id="mock_fnb_003",
            question=secret_question,
            as_of_date="2026-08-27",
            context=MockBusinessContextProvider.create_fnb_context(),
        )

    assert captured.value.code == GROUNDING_FAILED
    assert captured.value.__cause__ is root_cause
    assert secret_question not in str(captured.value)
    assert "sampled database value" not in str(captured.value)
    assert engine.calls == 1


def test_happy_path_normalizes_request_and_calls_engine_once() -> None:
    context = MockBusinessContextProvider.create_fnb_context()
    engine = _CapturingEngine()
    runtime = QuestionGroundingRuntime(engine=engine)

    grounded = runtime.ground_question(
        question_id="  q-supported  ",
        business_id="  mock_fnb_003  ",
        question="  Trong tháng này, ca tối thu được bao nhiêu tiền mặt?  ",
        as_of_date="  2026-08-27  ",
        context=context,
    )

    assert isinstance(grounded, GroundedQuestion)
    assert grounded.question_id == "q-supported"
    assert grounded.business_id == "mock_fnb_003"
    assert grounded.question == "Trong tháng này, ca tối thu được bao nhiêu tiền mặt?"
    assert grounded.as_of_date == "2026-08-27"
    assert len(engine.calls) == 1
    captured_request, captured_context = engine.calls[0]
    assert isinstance(captured_request, QuestionRequest)
    assert captured_context is context


def test_runtime_accepts_context_loader_view_and_is_deterministic(tmp_path) -> None:
    business_id = "biz_runtime_grounding"
    payload = {
        "contract_version": "1.0",
        "business_id": business_id,
        "schema_catalog": {
            "tables": [],
            "key_candidates": [],
            "join_graph": [],
            "warnings": [],
        },
        "rule_catalog": {
            "rules": [],
            "warnings": [],
            "business_id": business_id,
        },
    }
    (tmp_path / "business_context.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    context = BusinessContextRuntimeLoader().load(
        tmp_path, expected_business_id=business_id
    ).grounding_context
    runtime = QuestionGroundingRuntime()
    kwargs = {
        "question_id": "q-runtime-context",
        "business_id": business_id,
        "question": "Tổng doanh thu tháng này là bao nhiêu?",
        "as_of_date": "2026-08-27",
        "context": context,
    }

    first = runtime.ground_question(**kwargs)
    second = runtime.ground_question(**kwargs)

    assert isinstance(first, GroundedQuestion)
    assert first.to_dict() == second.to_dict()
    assert first is not second


def test_runtime_contract_is_exported_from_grounding_package() -> None:
    assert grounding_api.QuestionGroundingRuntime is QuestionGroundingRuntime
    assert grounding_api.QuestionGroundingRuntimeError is QuestionGroundingRuntimeError
    assert grounding_api.GROUNDING_REQUEST_INVALID == GROUNDING_REQUEST_INVALID
    assert grounding_api.GROUNDING_CONTEXT_INVALID == GROUNDING_CONTEXT_INVALID
    assert grounding_api.GROUNDING_BUSINESS_MISMATCH == GROUNDING_BUSINESS_MISMATCH
    assert grounding_api.GROUNDING_FAILED == GROUNDING_FAILED
