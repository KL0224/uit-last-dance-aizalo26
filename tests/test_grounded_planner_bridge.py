"""Test suite for Grounded Planner Bridge (Task 1)."""

from typing import Any
import pytest

from datamate.grounding.adapters import (
    B02ContextAdapter,
    BusinessContextAdapter,
    GroundingToPlannerAdapter,
)
from datamate.grounding.contracts import (
    CoverageStatus,
    GroundedQuestion,
    OperationKind,
    QuestionIntent,
    SelectedSchema,
)
from datamate.planner.base import BaseLLM
from datamate.planner.generator import Text2SQLGenerator
from datamate.planner.prompt import build_repair_messages, build_text2sql_messages
from datamate.planner.types import ChatMessage, GenerationOptions, GenerationResult


class MockLLM(BaseLLM):
    """Mock LLM capturing incoming messages."""

    def __init__(self) -> None:
        self.last_messages: list[ChatMessage] = []
        self.last_batch_messages: list[list[ChatMessage]] = []

    def load(self) -> None:
        pass

    def generate(self, prompt: str, *, options: GenerationOptions | None = None) -> GenerationResult:
        return GenerationResult(text="SELECT 1", input_tokens=10, output_tokens=10, finish_reason="stop")

    def chat(self, messages: list[ChatMessage], *, options: GenerationOptions | None = None) -> GenerationResult:
        self.last_messages = messages
        json_output = '```json\n{"status": "answerable", "answer_type": "number", "sql": "SELECT 1"}\n```'
        return GenerationResult(text=json_output, input_tokens=10, output_tokens=10, finish_reason="stop")

    def generate_batch(
        self, prompts: list[str], *, options: GenerationOptions | None = None
    ) -> list[GenerationResult]:
        return [self.generate(p, options=options) for p in prompts]

    def chat_batch(
        self, messages_batch: list[list[ChatMessage]], *, options: GenerationOptions | None = None
    ) -> list[GenerationResult]:
        self.last_batch_messages = messages_batch
        return [self.chat(msgs, options=options) for msgs in messages_batch]


def test_naming_aliases() -> None:
    """BusinessContextAdapter and to_gate_evidence_proof must be available."""
    assert issubclass(BusinessContextAdapter, B02ContextAdapter) or BusinessContextAdapter is B02ContextAdapter
    assert hasattr(GroundingToPlannerAdapter, "to_gate_evidence_proof")


def test_build_text2sql_messages_with_grounded_hint() -> None:
    """build_text2sql_messages should embed grounded_hint into user prompt when provided."""
    hint = "### KẾT QUẢ PHÂN TÍCH CÂU HỎI & LIÊN KẾT DỮ LIỆU (GROUNDING HINTS)\n- **Phép toán**: `sum`"
    messages = build_text2sql_messages(
        context={},
        question="Doanh thu hôm nay?",
        as_of_date="2026-08-27",
        grounded_hint=hint,
    )
    assert len(messages) == 2
    user_content = messages[1].content
    assert hint in user_content
    assert "Doanh thu hôm nay?" in user_content


def test_build_repair_messages_with_grounded_hint() -> None:
    """build_repair_messages should embed grounded_hint into user prompt when provided."""
    hint = "### KẾT QUẢ PHÂN TÍCH CÂU HỎI & LIÊN KẾT DỮ LIỆU (GROUNDING HINTS)"
    messages = build_repair_messages(
        context={},
        question="Doanh thu hôm nay?",
        as_of_date="2026-08-27",
        previous_sql="SELECT sum(amount)",
        error_message="Table not found",
        grounded_hint=hint,
    )
    assert len(messages) == 2
    user_content = messages[1].content
    assert hint in user_content
    assert "Table not found" in user_content


def test_generator_generate_and_repair_with_grounded_hint() -> None:
    """Text2SQLGenerator passes grounded_hint through to prompt builder."""
    llm = MockLLM()
    gen = Text2SQLGenerator(model=llm)

    hint = "HINT: Filter by shift = 'toi'"
    res = gen.generate(
        context={},
        question="Ca tối thu được bao nhiêu?",
        as_of_date="2026-08-27",
        grounded_hint=hint,
    )
    assert res.sql == "SELECT 1"
    assert any(hint in m.content for m in llm.last_messages)

    repair_res = gen.repair(
        context={},
        question="Ca tối thu được bao nhiêu?",
        as_of_date="2026-08-27",
        previous_sql="SELECT 1",
        error_message="Invalid column",
        grounded_hint=hint,
    )
    assert repair_res.sql == "SELECT 1"
    assert any(hint in m.content for m in llm.last_messages)


def test_generator_batch_with_grounded_hint() -> None:
    """generate_batch and repair_batch propagate grounded_hint per item."""
    llm = MockLLM()
    gen = Text2SQLGenerator(model=llm)

    items = [
        {
            "context": {},
            "question": "Q1",
            "as_of_date": "2026-08-27",
            "grounded_hint": "HINT_ITEM_1",
        },
        {
            "context": {},
            "question": "Q2",
            "as_of_date": "2026-08-27",
        },
    ]

    results = gen.generate_batch(items)
    assert len(results) == 2
    assert "HINT_ITEM_1" in llm.last_batch_messages[0][1].content
    assert "HINT_ITEM_1" not in llm.last_batch_messages[1][1].content


def test_format_context_with_semantic_catalog() -> None:
    """Verify that semantic_catalog metrics are formatted in planner prompt."""
    from datamate.planner.prompt import format_context_for_prompt

    ctx = {
        "semantic_catalog": {
            "metrics": [
                {
                    "metric_id": "commission",
                    "name": "Hoa hồng thợ",
                    "preferred_table": "danh_sach_tho",
                    "required_columns": ["hoa_hong"],
                    "formula_hint": "SUM(tien * hoa_hong)",
                }
            ]
        }
    }
    prompt_str = format_context_for_prompt(ctx)
    assert "### CHỈ SỐ NGHIỆP VỤ ĐÃ ĐỐI CHIẾU (GROUNDED METRICS & FORMULAS):" in prompt_str
    assert "Hoa hồng thợ (commission): bảng `danh_sach_tho` (cột: hoa_hong) -> Công thức: SUM(tien * hoa_hong)" in prompt_str


def test_select_rules_prunes_submission_format() -> None:
    """Verify that benchmark submission formatting rules are pruned."""
    from datamate.planner.prompt import _select_rules

    rules = [
        {"rule_id": "r1", "topic": "Doanh thu", "text": "Doanh thu là tổng tiền bán hàng.", "status": "active", "precedence": 100},
        {"rule_id": "r2", "topic": "number", "text": "number | JSON number, không đơn vị | 4820000", "status": "active", "precedence": 100},
        {"rule_id": "r3", "topic": None, "text": "Mỗi dòng `submission.jsonl`: `{\"id\": ...}`. Đúng +1, sai −1.", "status": "active", "precedence": 100},
    ]
    kept = _select_rules(rules, industry=None)
    kept_ids = [r["rule_id"] for r in kept]
    assert "r1" in kept_ids
    assert "r2" not in kept_ids
    assert "r3" not in kept_ids

