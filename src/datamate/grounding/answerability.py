"""C5: Answerability Precheck — verifying required evidence against CapabilityMatrix."""

from __future__ import annotations

import unicodedata
from typing import Sequence

from .contracts import (
    CoverageStatus,
    EvidenceRequirement,
    MissingEvidenceProof,
    QuestionIntent,
    ResolvedTimeRange,
    SelectedSchema,
)
from .protocols import BusinessContextProtocol

_CAPABILITY_CONCEPT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "customers": ("customer_id", "customer_name", "khách hàng", "người mua", "mã khách"),
    "cost": ("cost", "gia_von", "giá vốn", "chi phí", "chi_phi"),
    "historical_stock": ("ton_kho_lich_su", "historical_stock", "tồn đầu kỳ", "tồn cuối kỳ"),
    "payments": ("payment", "collected_amount", "payment_method", "thực thu", "thanh toán"),
    "sales_by_product": ("product_id", "product_name", "tên món", "sản phẩm", "mặt hàng"),
    "expiry": ("expiry_date", "han_su_dung", "hạn sử dụng", "ngày hết hạn"),
    "warranties": ("warranty", "bao_hanh", "bảo hành"),
}


class AnswerabilityPrechecker:
    """Verify required capabilities and temporal coverage before invoking the LLM Planner."""

    def build_requirements(
        self,
        question: str,
        intent: QuestionIntent,
    ) -> tuple[EvidenceRequirement, ...]:
        """Infer required capabilities from intent metrics, grouping, and question keywords."""
        q_norm = unicodedata.normalize("NFC", question).lower()
        reqs: list[EvidenceRequirement] = []
        seen_caps: set[str] = set()

        def _add_req(cap_key: str, concepts: tuple[str, ...], mandatory: bool = True) -> None:
            if cap_key not in seen_caps:
                seen_caps.add(cap_key)
                reqs.append(
                    EvidenceRequirement(
                        capability_key=cap_key,
                        required_concepts=concepts,
                        is_mandatory=mandatory,
                    )
                )

        if "customer" in intent.group_by or any(
            kw in q_norm for kw in ("khách hàng nào", "khách nào", "bao nhiêu khách hàng")
        ):
            _add_req("customers", ("customer_id", "customer_name"))

        if any(m in intent.target_metrics for m in ("cost", "gross_profit")) or any(
            kw in q_norm for kw in ("lợi nhuận gộp", "lãi gộp", "giá vốn")
        ):
            _add_req("cost", ("cost", "gross_profit"))

        if "historical_stock" in intent.target_metrics or any(
            kw in q_norm for kw in ("tồn kho đầu kỳ", "tồn kho cuối ngày", "tồn kho lịch sử")
        ):
            _add_req("historical_stock", ("historical_stock", "stock_event_date"))

        if "cash_collected" in intent.target_metrics:
            _add_req("payments", ("collected_amount", "payment_date", "payment_method"))

        if "product" in intent.group_by or any(
            m in intent.target_metrics for m in ("sold_qty", "distinct_product_orders")
        ):
            _add_req("sales_by_product", ("product_name", "quantity"))

        if any(kw in q_norm for kw in ("hạn sử dụng", "hết hạn")):
            _add_req("expiry", ("expiry_date",))

        if "bảo hành" in q_norm:
            _add_req("warranties", ("warranty",))

        return tuple(reqs)

    def _has_fallback_column_in_catalog(
        self,
        capability_key: str,
        context: BusinessContextProtocol,
    ) -> bool:
        """Check all tables in catalog to ensure no alternative column provides the capability."""
        keywords = _CAPABILITY_CONCEPT_KEYWORDS.get(capability_key, (capability_key,))
        for tbl in context.get_tables():
            for col in tbl.columns:
                col_text = " ".join(
                    (col.name.lower(), col.description.lower(), *(a.lower() for a in col.aliases))
                )
                if any(kw in col_text for kw in keywords):
                    return True
        return False

    def evaluate(
        self,
        question: str,
        intent: QuestionIntent,
        resolved_time_ranges: Sequence[ResolvedTimeRange],
        selected_schema: SelectedSchema,
        context: BusinessContextProtocol,
    ) -> tuple[
        tuple[EvidenceRequirement, ...],
        CoverageStatus,
        MissingEvidenceProof | None,
        tuple[str, ...],
    ]:
        """Evaluate capability matrix and schema fallback to determine coverage status."""
        reqs = self.build_requirements(question, intent)
        all_tables = tuple(t.name for t in context.get_tables())
        risk_flags: list[str] = []

        if not all_tables:
            proof = MissingEvidenceProof(
                capability_key="schema",
                missing_fields=("tables",),
                checked_tables=(),
                checked_all_sources=True,
                reason="Doanh nghiệp không có bảng dữ liệu nào trong catalog.",
            )
            return reqs, CoverageStatus.UNSUPPORTED, proof, ("EMPTY_SCHEMA",)

        has_unknown = False
        for req in reqs:
            cap_status = context.get_capability_status(req.capability_key).lower()
            if cap_status == "unsupported" and req.is_mandatory:
                # Double-check all tables to avoid false unanswerable
                if not self._has_fallback_column_in_catalog(req.capability_key, context):
                    proof = MissingEvidenceProof(
                        capability_key=req.capability_key,
                        missing_fields=req.required_concepts or (req.capability_key,),
                        checked_tables=all_tables,
                        checked_all_sources=True,
                        reason=(
                            f"Dữ liệu của doanh nghiệp không hỗ trợ năng lực {req.capability_key!r} "
                            f"(thiếu các trường {list(req.required_concepts)} trên toàn bộ bảng {list(all_tables)})."
                        ),
                    )
                    return reqs, CoverageStatus.UNSUPPORTED, proof, ("MISSING_MANDATORY_CAPABILITY",)
                risk_flags.append(f"FALLBACK_COLUMN_USED:{req.capability_key}")
            elif cap_status == "unknown":
                if not self._has_fallback_column_in_catalog(req.capability_key, context):
                    has_unknown = True
                    risk_flags.append(f"UNCERTAIN_CAPABILITY:{req.capability_key}")

        # Check temporal coverage on primary table if available
        if selected_schema.primary_table and resolved_time_ranges:
            tables_map = {t.name: t for t in context.get_tables()}
            prim_t = tables_map.get(selected_schema.primary_table)
            if prim_t and prim_t.date_coverage_start and prim_t.date_coverage_end:
                for tr in resolved_time_ranges:
                    if (
                        tr.end_date < prim_t.date_coverage_start
                        or tr.start_date > prim_t.date_coverage_end
                    ):
                        risk_flags.append(
                            f"TEMPORAL_OUT_OF_RANGE:{tr.start_date}..{tr.end_date}"
                        )
                        has_unknown = True

        status = CoverageStatus.UNKNOWN if has_unknown else CoverageStatus.SUPPORTED
        return reqs, status, None, tuple(risk_flags)


__all__ = ["AnswerabilityPrechecker"]

