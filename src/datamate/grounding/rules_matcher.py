"""C1 Fast-Path: Vietnamese rule and pattern matcher for intent, metrics, and filters."""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence

from .contracts import (
    AnswerTypeHint,
    FilterCondition,
    OperationKind,
    QuestionIntent,
)
from .protocols import BusinessContextProtocol

_VN_NUMBER_WORDS: dict[str, int] = {
    "một": 1,
    "hai": 2,
    "ba": 3,
    "bốn": 4,
    "năm": 5,
    "sáu": 6,
    "bảy": 7,
    "tám": 8,
    "chín": 9,
    "mười": 10,
}

_BUILTIN_METRIC_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "cash_collected",
        (
            "tiền thực thu",
            "tiền mặt thu được",
            "thu được bao nhiêu tiền",
            "thực thu",
            "thu tiền mặt",
        ),
    ),
    (
        "distinct_product_orders",
        (
            "được ưa chuộng",
            "xuất hiện trong nhiều đơn",
            "nhiều đơn mua nhất",
        ),
    ),
    (
        "sold_qty",
        (
            "bán chạy",
            "bán được bao nhiêu ly",
            "bán được bao nhiêu phần",
            "bán được bao nhiêu hộp",
            "số lượng bán",
            "tổng số lượng",
            "bao nhiêu ly",
            "bao nhiêu món",
        ),
    ),
    (
        "revenue",
        (
            "doanh thu",
            "doanh số",
            "mua nhiều tiền nhất",
            "chi tiêu nhiều nhất",
            "tổng thành tiền",
            "tổng tiền",
        ),
    ),
    (
        "order_count",
        (
            "bao nhiêu đơn",
            "số đơn hàng",
            "tổng số đơn",
            "số lượng hóa đơn",
            "mấy đơn",
        ),
    ),
    (
        "cost",
        (
            "chi phí",
            "giá vốn",
            "tiền vốn",
        ),
    ),
    (
        "gross_profit",
        (
            "lợi nhuận gộp",
            "lãi gộp",
            "lợi nhuận",
        ),
    ),
    (
        "historical_stock",
        (
            "tồn kho đầu kỳ",
            "tồn kho cuối ngày",
            "tồn kho lịch sử",
            "tồn kho tại ngày",
        ),
    ),
)


class VietnameseRuleMatcher:
    """Fast-path deterministic extractor for Vietnamese tabular QA questions."""

    def extract_top_k(self, q_norm: str) -> int | None:
        """Extract Top-K integer from numeric or Vietnamese word patterns."""
        m_top = re.search(r"\btop\s+(\d+)\b", q_norm)
        if m_top:
            return int(m_top.group(1))

        m_num_entity = re.search(
            r"\b(\d+)\s+(?:sản phẩm|mặt hàng|món|khách hàng|nhân viên|chi nhánh|ngày)\s+"
            r"(?:được ưa chuộng|bán chạy|mua nhiều|chi tiêu nhiều|cao nhất|thấp nhất|đầu tiên)",
            q_norm,
        )
        if m_num_entity:
            return int(m_num_entity.group(1))

        for word, val in _VN_NUMBER_WORDS.items():
            pattern = (
                rf"\b{word}\s+(?:sản phẩm|mặt hàng|món|khách hàng|nhân viên|chi nhánh)\s+"
                r"(?:được ưa chuộng|bán chạy|mua nhiều|chi tiêu nhiều|cao nhất|thấp nhất)"
            )
            if re.search(pattern, q_norm):
                return val
        return None

    def extract_metrics(
        self,
        q_norm: str,
        context: BusinessContextProtocol | None = None,
    ) -> list[str]:
        """Match target metrics using context MetricRegistry and built-in Vietnamese patterns."""
        matched: list[str] = []

        if context is not None:
            for m_spec in context.get_metrics():
                if any(alias.lower() in q_norm for alias in m_spec.aliases):
                    if m_spec.metric_id not in matched:
                        matched.append(m_spec.metric_id)

        for metric_id, phrases in _BUILTIN_METRIC_PATTERNS:
            if any(p in q_norm for p in phrases):
                if metric_id not in matched:
                    matched.append(metric_id)

        # Prioritize cash_collected over generic revenue when explicitly asking cash collection
        if "cash_collected" in matched and "revenue" in matched and "doanh thu" not in q_norm:
            matched.remove("revenue")

        return matched

    def extract_group_by(self, q_norm: str) -> list[str]:
        """Infer grouping dimensions from question subject or 'theo ...' clauses."""
        groups: list[str] = []
        if any(
            p in q_norm
            for p in ("khách hàng nào", "khách nào", "theo khách hàng", "khách hàng chi tiêu")
        ):
            groups.append("customer")
        if any(
            p in q_norm
            for p in (
                "sản phẩm nào",
                "mặt hàng nào",
                "món nào",
                "sản phẩm được ưa chuộng",
                "sản phẩm bán chạy",
                "theo sản phẩm",
            )
        ):
            groups.append("product")
        if any(p in q_norm for p in ("ngày nào", "vào ngày mấy", "theo ngày")):
            groups.append("date")
        if any(p in q_norm for p in ("ca nào", "theo ca")):
            groups.append("shift")
        return groups

    def extract_filters_and_entities(
        self,
        question: str,
        q_norm: str,
        context: BusinessContextProtocol | None = None,
    ) -> tuple[list[FilterCondition], list[str]]:
        """Extract HAVING conditions, entity mentions, and known categorical aliases."""
        filters: list[FilterCondition] = []
        entities: list[str] = []

        # 1. HAVING minimum count: "ít nhất N đơn", "từ N đơn trở lên"
        m_min_orders = re.search(
            r"(?:ít nhất|tối thiểu|từ)\s+(\d+|một|hai|ba|bốn|năm)\s+đơn",
            q_norm,
        )
        if m_min_orders:
            raw_num = m_min_orders.group(1)
            val = _VN_NUMBER_WORDS.get(raw_num, int(raw_num) if raw_num.isdigit() else 1)
            filters.append(
                FilterCondition(
                    field_hint="order_count",
                    operator=">=",
                    raw_value=val,
                    is_having=True,
                )
            )

        # 2. Match known value aliases from BusinessContext
        if context is not None:
            for alias_phrase, (tbl, col, db_val) in context.get_value_aliases().items():
                if re.search(rf"\b{re.escape(alias_phrase)}\b", q_norm):
                    if alias_phrase not in entities:
                        entities.append(alias_phrase)
                    filters.append(
                        FilterCondition(
                            field_hint=col,
                            operator="=",
                            raw_value=alias_phrase,
                            grounded_column=f"{tbl}.{col}",
                            grounded_value=db_val,
                            is_having=False,
                        )
                    )

        # 3. Extract product with size or explicit named product e.g., "Cà phê sữa (L)"
        m_sized_prod = re.search(
            r"([A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]"
            r"[^?.,;]*?\([SMLsml]\))",
            question,
        )
        if m_sized_prod:
            prod_phrase = m_sized_prod.group(1).strip()
            if prod_phrase not in entities:
                entities.append(prod_phrase)
            filters.append(
                FilterCondition(
                    field_hint="product_name",
                    operator="LIKE",
                    raw_value=prod_phrase,
                    is_having=False,
                )
            )

        return filters, entities

    def match(
        self,
        question: str,
        context: BusinessContextProtocol | None = None,
    ) -> QuestionIntent:
        """Run deterministic rule-based extraction and compute confidence score."""
        q_clean = unicodedata.normalize("NFC", question).strip()
        q_norm = q_clean.lower()

        top_k = self.extract_top_k(q_norm)
        metrics = self.extract_metrics(q_norm, context)
        group_by = self.extract_group_by(q_norm)
        filters, entities = self.extract_filters_and_entities(q_clean, q_norm, context)

        operation: OperationKind | None = None
        answer_hint: AnswerTypeHint = AnswerTypeHint.NUMBER
        sort_order = "desc"
        confidence = 0.9

        # Determine Operation & AnswerTypeHint
        if any(
            p in q_norm
            for p in (
                "bao nhiêu phần trăm",
                "mấy phần trăm",
                "tăng hay giảm",
                "tốc độ tăng trưởng",
            )
        ):
            operation = OperationKind.PERCENT_CHANGE
            answer_hint = AnswerTypeHint.PERCENT
        elif any(p in q_norm for p in ("chiếm tỷ lệ", "tỷ trọng", "tỉ lệ")):
            operation = OperationKind.RATIO
            answer_hint = AnswerTypeHint.PERCENT
        elif re.search(r"\bcó\b.*\bkhông\s*\??$", q_norm) and "bao nhiêu" not in q_norm:
            operation = OperationKind.EXISTENCE
            answer_hint = AnswerTypeHint.BOOLEAN
        elif top_k is not None:
            operation = OperationKind.TOP_K
            answer_hint = AnswerTypeHint.LIST
            if any(p in q_norm for p in ("thấp nhất", "ít nhất", "kém nhất")):
                sort_order = "asc"
        elif any(
            p in q_norm
            for p in (
                "cao nhất",
                "nhiều nhất",
                "lớn nhất",
                "nhiều tiền nhất",
                "bán chạy nhất",
                "ưa chuộng nhất",
            )
        ):
            operation = OperationKind.ARGMAX
            sort_order = "desc"
            if "ngày nào" in q_norm or "ngày mấy" in q_norm:
                answer_hint = AnswerTypeHint.DATE
            elif any(
                p in q_norm
                for p in ("những ", "các ", "danh sách ")
            ):
                answer_hint = AnswerTypeHint.LIST
            else:
                answer_hint = AnswerTypeHint.STRING
        elif any(p in q_norm for p in ("thấp nhất", "ít nhất")) and any(
            g in q_norm for g in ("nào", "ngày mấy")
        ):
            operation = OperationKind.ARGMIN
            sort_order = "asc"
            answer_hint = AnswerTypeHint.DATE if "ngày" in q_norm else AnswerTypeHint.STRING
        elif any(p in q_norm for p in ("trung bình", "bình quân")):
            operation = OperationKind.AVG
            answer_hint = AnswerTypeHint.NUMBER
        elif any(
            p in q_norm
            for p in (
                "bao nhiêu khách hàng",
                "bao nhiêu mặt hàng khác nhau",
                "bao nhiêu sản phẩm khác nhau",
            )
        ):
            operation = OperationKind.COUNT_DISTINCT
            answer_hint = AnswerTypeHint.NUMBER
        elif any(
            p in q_norm
            for p in ("có bao nhiêu đơn", "mấy đơn", "số lượng đơn", "tổng số đơn")
        ):
            operation = OperationKind.COUNT
            answer_hint = AnswerTypeHint.NUMBER
        elif any(
            p in q_norm
            for p in (
                "tổng",
                "thu được bao nhiêu",
                "bán được bao nhiêu",
                "là bao nhiêu",
                "đạt bao nhiêu",
            )
        ):
            operation = OperationKind.SUM
            answer_hint = AnswerTypeHint.NUMBER
        elif any(p in q_norm for p in ("bảng thống kê", "báo cáo bảng")):
            operation = OperationKind.TABLE_REPORT
            answer_hint = AnswerTypeHint.TABLE
        else:
            # Ambiguous question structure -> lower confidence to trigger 3B LLM fallback
            operation = OperationKind.LOOKUP
            answer_hint = AnswerTypeHint.STRING
            confidence = 0.45

        if not metrics and operation in {
            OperationKind.SUM,
            OperationKind.AVG,
            OperationKind.PERCENT_CHANGE,
            OperationKind.RATIO,
        }:
            confidence = min(confidence, 0.55)

        return QuestionIntent(
            operation=operation,
            target_metrics=tuple(metrics),
            entities=tuple(entities),
            filters=tuple(filters),
            group_by=tuple(group_by),
            top_k=top_k,
            sort_order=sort_order,
            tie_break_rule="entity_asc",
            answer_type_hint=answer_hint,
            confidence=confidence,
            used_llm_fallback=False,
        )


__all__ = ["VietnameseRuleMatcher"]

