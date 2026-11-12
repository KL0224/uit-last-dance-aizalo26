"""C1 Fallback: 3B Structured LLM Parser (e.g., Qwen2.5-3B-Instruct) for complex questions."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Sequence

from .contracts import (
    AnswerTypeHint,
    FilterCondition,
    OperationKind,
    QuestionIntent,
)

logger = logging.getLogger(__name__)

_MAX_QUESTION_CHARS = 8_192
_MAX_RESPONSE_CHARS = 20_000
_MAX_LIST_ITEMS = 32
_MAX_TEXT_CHARS = 256
_MAX_PROMPT_METRICS = 64
_MAX_PROMPT_TABLES = 32
_CONTEXT_SAFETY_TOKENS = 64
_ALLOWED_GROUPS = frozenset({"customer", "product", "date", "shift"})
_ALLOWED_FILTER_OPERATORS = frozenset(
    {"=", "!=", "<", "<=", ">", ">=", "LIKE", "IN"}
)
_BUILTIN_METRICS = (
    "cash_collected",
    "distinct_product_orders",
    "sold_qty",
    "revenue",
    "order_count",
    "commission",
    "warranty_count",
    "cost",
    "gross_profit",
    "historical_stock",
)
_METRIC_PROMPT_HINTS: dict[str, tuple[str, ...]] = {
    "cash_collected": ("thực thu", "thu tiền", "tiền mặt"),
    "distinct_product_orders": ("ưa chuộng", "nhiều đơn"),
    "sold_qty": ("số lượng", "bán chạy", "bán được"),
    "revenue": ("doanh thu", "doanh số", "tổng tiền", "tiền bán", "dthu", "tiền"),
    "order_count": ("số đơn", "đơn hàng", "bao nhiêu đơn", "lượt xe", "phiếu", "số phiếu", "mấy phiếu"),
    "commission": ("hoa hồng", "huê hồng", "tiền hoa hồng", "lương hoa hồng", "chiết khấu"),
    "warranty_count": ("bảo hành", "phiếu bảo hành", "xe bảo hành"),
    "cost": ("chi phí", "giá vốn"),
    "gross_profit": ("lợi nhuận", "lãi gộp"),
    "historical_stock": ("tồn kho",),
}

EXTRACTOR_SYSTEM_PROMPT = """Bạn là bộ trích xuất ngữ nghĩa câu hỏi kinh doanh tiếng Việt (Semantic Extractor) cho hệ thống DataMate.
Nhiệm vụ của bạn là phân tích câu hỏi và trả về MỘT khối JSON hợp lệ theo cấu trúc:
{
  "normalized_question": "câu hỏi tiếng Việt chuẩn hóa, không còn viết tắt hay từ lóng",
  "operation": "sum | count | count_distinct | avg | argmax | argmin | top_k | percent_change | ratio | comparison | lookup | existence | table_report",
  "target_metrics": ["metric_id_từ_danh_sách_khả_dụng"],
  "entities": ["tên đối tượng cụ thể, chủng loại, phân loại, dịch vụ, hành động, hoặc từ khóa lọc"],
  "filters": [{"field_hint": "...", "operator": "=", "raw_value": "...", "is_having": false}],
  "group_by": ["customer | product | date | shift"],
  "top_k": null,
  "sort_order": "desc",
  "answer_type_hint": "number | percent | string | date | boolean | list | table"
}

NGUYÊN TẮC BẮT BUỘC (DOMAIN-AGNOSTIC):
1. RÀNG BUỘC KHÉP KÍN METRIC (CLOSED METRIC SELECTION):
   - 'target_metrics' BẮT BUỘC CHỈ ĐƯỢC CHỌN các ID có mặt trong danh sách 'Metric IDs khả dụng' được cung cấp (ví dụ: 'revenue', 'order_count', 'sold_qty', 'cash_collected').
   - TUYỆT ĐỐI KHÔNG tự sáng tác, dịch nghĩa hoặc bịa ra bất kỳ metric ID mới nào ngoài danh sách được cung cấp.

2. PHÂN BIỆT RÕ RÀNG GIỮA METRIC VÀ ENTITY/FILTER:
   - METRIC ('target_metrics'): Chỉ chứa đại lượng số học tổng hợp chung của giao dịch:
     + Tiền tệ, doanh thu, dòng tiền, hoa hồng, chiết khấu, lợi nhuận -> chọn metric tiền (ví dụ: 'revenue' hoặc 'cash_collected').
     + Số đơn, số lượt giao dịch, số phiếu, số lần thực hiện -> chọn metric đếm giao dịch (ví dụ: 'order_count').
     + Số lượng hàng hoá, số sản phẩm, số cái/chiếc/hộp -> chọn metric số lượng (ví dụ: 'sold_qty').
   - ENTITY & FILTER ('entities', 'filters'): Chứa mọi danh từ cụ thể chỉ đối tượng, phân loại, chủng loại mặt hàng, tên dịch vụ, hành động, trạng thái, hoặc ghi chú (ví dụ: tên món, tên việc, tên thiết bị, tên dịch vụ, bảo hành, hoàn trả, tên người):
     + BẮT BUỘC đưa các từ khóa này vào 'entities' hoặc 'filters'.
     + TUYỆT ĐỐI KHÔNG đưa tên dịch vụ, tên mặt hàng hoặc trạng thái vào 'target_metrics'!

3. CHỈ SỐ PHÁI SINH TỪ CÔNG THỨC (DERIVED METRICS):
   - Khi câu hỏi yêu cầu tính hoa hồng, tỷ lệ % hoặc chia trung bình: 'target_metrics' phải là metric cơ sở tương ứng (ví dụ: hoa hồng dựa trên doanh thu thì chọn 'revenue'; trung bình mỗi phiếu chọn 'revenue').

Tuyệt đối không sinh câu lệnh SQL và không giải thích ngoài khối JSON."""


def _extract_json_dict(raw_text: str) -> dict[str, Any]:
    """Strip <think> blocks and markdown code fences to parse JSON dictionary."""
    if not isinstance(raw_text, str):
        raise TypeError("LLM fallback response must be text")
    if len(raw_text) > _MAX_RESPONSE_CHARS:
        raise ValueError("LLM fallback response exceeds the size limit")
    cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
    if "<think>" in cleaned:
        cleaned = cleaned.split("<think>", 1)[0].strip()

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        brace_match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if brace_match:
            cleaned = brace_match.group(0)

    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("LLM fallback response must be a JSON object")
    return data


def _string_list(
    payload: dict[str, Any],
    field_name: str,
    *,
    allowed: frozenset[str] | None = None,
) -> tuple[str, ...]:
    """Validate a bounded list of short strings from untrusted LLM JSON."""
    raw_value = payload.get(field_name) or []
    if not isinstance(raw_value, list):
        raise ValueError(f"{field_name} must be a list")
    if len(raw_value) > _MAX_LIST_ITEMS:
        raise ValueError(f"{field_name} exceeds the item limit")

    values: list[str] = []
    for item in raw_value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name} must contain nonempty strings")
        normalized = item.strip()
        if len(normalized) > _MAX_TEXT_CHARS:
            raise ValueError(f"{field_name} contains an oversized value")
        if allowed is not None and normalized not in allowed:
            raise ValueError(f"unsupported {field_name}: {normalized!r}")
        values.append(normalized)
    return tuple(values)


def _parse_filters(payload: dict[str, Any]) -> tuple[FilterCondition, ...]:
    """Validate filter objects before they enter deterministic grounding."""
    raw_filters = payload.get("filters") or []
    if not isinstance(raw_filters, list):
        raise ValueError("filters must be a list")
    if len(raw_filters) > _MAX_LIST_ITEMS:
        raise ValueError("filters exceeds the item limit")

    filters: list[FilterCondition] = []
    for item in raw_filters:
        if not isinstance(item, dict):
            raise ValueError("filters must contain objects")
        field_hint = item.get("field_hint", "")
        operator = item.get("operator", "=")
        is_having = item.get("is_having", False)
        if not isinstance(field_hint, str) or not field_hint.strip():
            raise ValueError("filter field_hint must be nonempty text")
        if len(field_hint) > _MAX_TEXT_CHARS:
            raise ValueError("filter field_hint exceeds the size limit")
        if not isinstance(operator, str):
            raise ValueError("filter operator must be text")
        normalized_operator = operator.strip().upper()
        if normalized_operator not in _ALLOWED_FILTER_OPERATORS:
            raise ValueError(f"unsupported filter operator: {operator!r}")
        if not isinstance(is_having, bool):
            raise ValueError("filter is_having must be boolean")
        raw_value = item.get("raw_value")
        if not isinstance(raw_value, (str, int, float, bool, type(None), list)):
            raise ValueError("filter raw_value has an unsupported type")
        if isinstance(raw_value, str) and len(raw_value) > _MAX_TEXT_CHARS:
            raise ValueError("filter raw_value exceeds the size limit")
        if isinstance(raw_value, list) and (
            len(raw_value) > _MAX_LIST_ITEMS
            or any(
                not isinstance(value, (str, int, float, bool, type(None)))
                for value in raw_value
            )
        ):
            raise ValueError("filter raw_value list is invalid")
        filters.append(
            FilterCondition(
                field_hint=field_hint.strip(),
                operator=normalized_operator,
                raw_value=raw_value,
                is_having=is_having,
            )
        )
    return tuple(filters)


def _prioritize_candidates(
    question: str,
    values: Sequence[str],
    *,
    limit: int,
    hints: dict[str, tuple[str, ...]] | None = None,
) -> list[str]:
    """Deduplicate and keep question-relevant registry entries first."""
    unique_values = list(dict.fromkeys(str(value) for value in values))
    q_norm = question.lower()

    def _is_relevant(value: str) -> bool:
        normalized_value = value.lower().replace("_", " ")
        return normalized_value in q_norm or any(
            hint in q_norm for hint in (hints or {}).get(value, ())
        )

    relevant = [value for value in unique_values if _is_relevant(value)]
    relevant_set = set(relevant)
    remaining = [value for value in unique_values if value not in relevant_set]
    return (relevant + remaining)[:limit]


def _build_user_prompt(
    question: str,
    as_of_date: str,
    metrics: Sequence[str],
    tables: Sequence[str],
) -> str:
    """Serialize bounded registry candidates compactly for the 3B extractor."""
    metrics_json = json.dumps(list(metrics), ensure_ascii=False, separators=(",", ":"))
    tables_json = json.dumps(list(tables), ensure_ascii=False, separators=(",", ":"))
    return (
        f"Câu hỏi: {question}\n"
        f"Ngày tham chiếu (as_of_date): {as_of_date}\n"
        f"Metric IDs khả dụng (chỉ được chọn target_metrics trong danh sách này): {metrics_json}\n"
        f"Bảng ứng viên: {tables_json}"
    )


class StructuredLLMParser:
    """Invoke Qwen2.5-3B-Instruct for structured intent extraction."""

    def __init__(
        self,
        chat_fn: Callable[[str, str], str],
        *,
        token_count_fn: Callable[[str, str], int] | None = None,
        max_input_tokens: int = 3_584,
    ) -> None:
        if max_input_tokens < 1:
            raise ValueError("max_input_tokens must be positive")
        self._chat_fn = chat_fn
        self._token_count_fn = token_count_fn or (
            lambda system, user: len(f"{system}\n{user}".encode("utf-8"))
        )
        self._max_input_tokens = max_input_tokens

    def extract_intent(
        self,
        question: str,
        as_of_date: str,
        available_metrics: Sequence[str],
        available_tables: Sequence[str],
    ) -> QuestionIntent:
        """Invoke the 3B model and parse its JSON response into a QuestionIntent."""
        if len(question) > _MAX_QUESTION_CHARS:
            raise ValueError("Question exceeds the grounding LLM size limit")
        effective_metrics = tuple(dict.fromkeys(tuple(available_metrics) + _BUILTIN_METRICS))
        prompt_metrics = _prioritize_candidates(
            question,
            effective_metrics,
            limit=_MAX_PROMPT_METRICS,
            hints=_METRIC_PROMPT_HINTS,
        )
        prompt_tables = _prioritize_candidates(
            question,
            available_tables,
            limit=_MAX_PROMPT_TABLES,
        )
        while True:
            user_prompt = _build_user_prompt(
                question,
                as_of_date,
                prompt_metrics,
                prompt_tables,
            )
            input_tokens = self._token_count_fn(
                EXTRACTOR_SYSTEM_PROMPT,
                user_prompt,
            )
            if input_tokens <= self._max_input_tokens:
                break
            if prompt_tables:
                prompt_tables = prompt_tables[: len(prompt_tables) // 2]
                continue
            if len(prompt_metrics) > 1:
                prompt_metrics = prompt_metrics[: max(1, len(prompt_metrics) // 2)]
                continue
            raise ValueError(
                "Grounding LLM prompt exceeds the input token budget after registry trimming"
            )
        raw_response = self._chat_fn(EXTRACTOR_SYSTEM_PROMPT, user_prompt)
        payload = _extract_json_dict(raw_response)

        raw_target_metrics = _string_list(payload, "target_metrics")
        allowed_metrics = set(effective_metrics) | set(_BUILTIN_METRICS)

        # Kiểm tra metric không hợp lệ / nằm ngoài registry cho phép
        invalid_metrics: list[str] = []
        normalized_metrics: list[str] = []
        for raw_m in raw_target_metrics:
            m_clean = raw_m.strip().lower().replace("-", "_").replace(" ", "_")
            if m_clean in allowed_metrics:
                normalized_metrics.append(m_clean)
                continue
            # Thử map qua _METRIC_PROMPT_HINTS
            mapped = None
            for canon_id, hints in _METRIC_PROMPT_HINTS.items():
                if canon_id in allowed_metrics and any(h.replace(" ", "_") in m_clean or m_clean in h for h in hints):
                    mapped = canon_id
                    break
            if mapped:
                normalized_metrics.append(mapped)
            else:
                invalid_metrics.append(raw_m)

        if invalid_metrics:
            raise ValueError(f"LLM returned unavailable metrics: {sorted(invalid_metrics)}")

        target_metrics = tuple(dict.fromkeys(normalized_metrics))

        raw_op = str(payload.get("operation", "lookup")).lower()
        try:
            operation = OperationKind(raw_op)
        except ValueError as exc:
            raise ValueError(f"Unsupported LLM operation: {raw_op!r}") from exc

        raw_hint = str(payload.get("answer_type_hint", "number")).lower()
        try:
            answer_hint = AnswerTypeHint(raw_hint)
        except ValueError as exc:
            raise ValueError(f"Unsupported LLM answer_type_hint: {raw_hint!r}") from exc

        filters = _parse_filters(payload)
        entities = _string_list(payload, "entities")
        group_by = _string_list(payload, "group_by", allowed=_ALLOWED_GROUPS)

        top_k_val = payload.get("top_k")
        top_k = (
            int(top_k_val)
            if isinstance(top_k_val, int)
            and not isinstance(top_k_val, bool)
            and top_k_val > 0
            else None
        )
        sort_order = str(payload.get("sort_order", "desc")).lower()
        if sort_order not in {"asc", "desc"}:
            raise ValueError("LLM sort_order must be 'asc' or 'desc'")

        normalized_question = payload.get("normalized_question")
        if normalized_question is not None:
            if not isinstance(normalized_question, str) or not normalized_question.strip():
                raise ValueError("LLM normalized_question must be nonempty text")
            normalized_question = normalized_question.strip()
            if len(normalized_question) > _MAX_QUESTION_CHARS:
                raise ValueError("LLM normalized_question exceeds the size limit")

        return QuestionIntent(
            operation=operation,
            target_metrics=target_metrics,
            entities=entities,
            filters=filters,
            group_by=group_by,
            top_k=top_k,
            sort_order=sort_order,
            tie_break_rule="entity_asc",
            answer_type_hint=answer_hint,
            confidence=0.85,
            used_llm_fallback=True,
            normalized_question=normalized_question,
        )


def create_qwen3b_vllm_parser(
    config_path: str | Path,
    *,
    model_path_override: str | Path | None = None,
) -> StructuredLLMParser:
    """Load a local Qwen 3B snapshot with vLLM and build the C1 fallback parser.

    The import stays local so importing ``datamate.grounding`` on a CPU-only
    machine does not import vLLM, PyTorch, or allocate GPU memory.
    """
    from dataclasses import replace
    from datamate.planner import ChatMessage, VLLMModel, load_config

    model_config, generation_options = load_config(config_path)
    if model_path_override is not None:
        model_config = replace(model_config, model_path=Path(model_path_override))
    model = VLLMModel(model_config, default_options=generation_options)
    model.load()

    def _chat(system_prompt: str, user_prompt: str) -> str:
        result = model.chat(
            [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_prompt),
            ],
            options=generation_options,
        )
        return result.text

    def _count_tokens(system_prompt: str, user_prompt: str) -> int:
        try:
            return model.count_chat_tokens(
                [
                    ChatMessage(role="system", content=system_prompt),
                    ChatMessage(role="user", content=user_prompt),
                ]
            )
        except Exception as exc:
            logger.warning("count_chat_tokens failed (%s), using char length approximation", exc)
            return (len(system_prompt) + len(user_prompt)) // 3

    max_input_tokens = (
        model_config.max_model_len
        - generation_options.max_new_tokens
        - _CONTEXT_SAFETY_TOKENS
    )
    if max_input_tokens < 1:
        raise ValueError("Grounding model configuration leaves no input token budget")
    return StructuredLLMParser(
        chat_fn=_chat,
        token_count_fn=_count_tokens,
        max_input_tokens=max_input_tokens,
    )


__all__ = [
    "EXTRACTOR_SYSTEM_PROMPT",
    "StructuredLLMParser",
    "create_qwen3b_vllm_parser",
]
