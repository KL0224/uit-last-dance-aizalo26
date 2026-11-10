"""Adapters bridging Component C (Grounding) with B0.2 (Context), B0.3 (Planner), and B0.5 (Gate)."""

from __future__ import annotations

from typing import Any, Sequence

from datamate.b0.b02.contracts import BusinessContext
from datamate.b0.b05.contracts import EvidenceProof

from .contracts import GroundedQuestion
from .protocols import (
    BusinessContextProtocol,
    CalendarEventSpec,
    ColumnSpec,
    JoinSpec,
    MetricSpec,
    TableSpec,
)


class B02ContextAdapter(BusinessContextProtocol):
    """Adapter wrapping a B0.2 BusinessContext to satisfy BusinessContextProtocol."""

    def __init__(self, b02_context: BusinessContext) -> None:
        self._ctx = b02_context
        self.business_id: str = b02_context.business_id
        self._tables: tuple[TableSpec, ...] = self._build_tables()
        self._join_edges: tuple[JoinSpec, ...] = self._build_joins()

    def _build_tables(self) -> tuple[TableSpec, ...]:
        specs: list[TableSpec] = []
        for tbl in self._ctx.schema_catalog.tables:
            # Extract sample values from profile_rows if available
            samples_by_col: dict[str, list[Any]] = {c.name: [] for c in tbl.columns}
            for row in tbl.profile_rows:
                for col_name, val in row.items():
                    if (
                        col_name in samples_by_col
                        and val is not None
                        and val not in samples_by_col[col_name]
                        and len(samples_by_col[col_name]) < 15
                    ):
                        samples_by_col[col_name].append(val)

            col_specs: list[ColumnSpec] = []
            for col in tbl.columns:
                if col.name.startswith("__dm_"):
                    continue
                col_specs.append(
                    ColumnSpec(
                        name=col.name,
                        data_type=col.data_type,
                        sample_values=tuple(samples_by_col.get(col.name, ())),
                        null_ratio=col.null_ratio or 0.0,
                    )
                )
            specs.append(
                TableSpec(
                    name=tbl.name,
                    columns=tuple(col_specs),
                    grain=tbl.grain or "unknown",
                    row_count=tbl.row_count or 0,
                )
            )
        return tuple(specs)

    def _build_joins(self) -> tuple[JoinSpec, ...]:
        return tuple(
            JoinSpec(
                left_table=edge.left_table,
                left_column=edge.left_column,
                right_table=edge.right_table,
                right_column=edge.right_column,
                cardinality=edge.cardinality,
                fanout_warning=edge.fanout_warning,
                confidence=edge.confidence,
            )
            for edge in self._ctx.schema_catalog.join_graph
        )

    def get_tables(self) -> Sequence[TableSpec]:
        return self._tables

    def get_join_edges(self) -> Sequence[JoinSpec]:
        return self._join_edges

    def get_metrics(self) -> Sequence[MetricSpec]:
        return ()

    def get_capability_status(self, capability_key: str) -> str:
        constraints = self._ctx.answerability_constraints or {}
        if capability_key in constraints:
            val = constraints[capability_key]
            if isinstance(val, bool):
                return "supported" if val else "unsupported"
            return str(val).lower()
        return "unknown"

    def get_calendar_events(self) -> Sequence[CalendarEventSpec]:
        meta = self._ctx.business_metadata or {}
        raw_events = meta.get("calendar_events") or ()
        events: list[CalendarEventSpec] = []
        for ev in raw_events:
            if isinstance(ev, dict):
                events.append(
                    CalendarEventSpec(
                        event_key=str(ev.get("event_key", "")),
                        aliases=tuple(str(a) for a in (ev.get("aliases") or ())),
                        year=int(ev.get("year", 2026)),
                        start_date=str(ev.get("start_date", "")),
                        end_date=str(ev.get("end_date", "")),
                    )
                )
        return tuple(events)

    def get_active_rules(self, topic: str | None = None) -> Sequence[str]:
        sorted_rules = sorted(
            self._ctx.rule_catalog.rules, key=lambda r: r.precedence
        )
        return tuple(
            r.text
            for r in sorted_rules
            if topic is None or r.topic == topic
        )

    def get_value_aliases(self) -> dict[str, tuple[str, str, Any]]:
        meta = self._ctx.business_metadata or {}
        return dict(meta.get("value_aliases") or {})


class GroundingToPlannerAdapter:
    """Adapter converting GroundedQuestion into Planner prompt hints and B0.5 EvidenceProof."""

    @staticmethod
    def format_grounded_hint_for_planner(grounded: GroundedQuestion) -> str:
        """Render a concise, structured markdown section to guide the 9B SQL Planner."""
        lines: list[str] = [
            "### KẾT QUẢ PHÂN TÍCH CÂU HỎI & LIÊN KẾT DỮ LIỆU (GROUNDING HINTS)",
            f"- **Phép toán chính (Operation)**: `{grounded.intent.operation.value}`",
            f"- **Kiểu đáp án kỳ vọng (Answer Type Hint)**: `{grounded.answer_type_hint.value}`",
        ]
        if grounded.intent.target_metrics:
            lines.append(
                f"- **Chỉ số nghiệp vụ (Target Metrics)**: `{', '.join(grounded.intent.target_metrics)}`"
            )
        if grounded.intent.top_k is not None:
            lines.append(
                f"- **Giới hạn Top-K**: `LIMIT {grounded.intent.top_k}` (sắp xếp `{grounded.intent.sort_order.upper()}`)"
            )

        if grounded.resolved_time_ranges:
            lines.append("- **Khoảng thời gian đã phân giải (Resolved Time Constraints)**:")
            for tr in grounded.resolved_time_ranges:
                comp_str = ""
                if tr.comparison_start_date and tr.comparison_end_date:
                    comp_str = f" | Kỳ so sánh: `{tr.comparison_start_date}` đến `{tr.comparison_end_date}`"
                lines.append(
                    f"  + `{tr.raw_expression}` ({tr.date_role.value}): "
                    f"từ `{tr.start_date}` đến `{tr.end_date}` (inclusive){comp_str}"
                )

        if grounded.selected_schema.primary_table:
            lines.append(
                f"- **Bảng trọng tâm (Primary Table)**: `{grounded.selected_schema.primary_table}`"
            )
            for sc in grounded.selected_schema.tables:
                cols_str = ", ".join(sc.relevant_columns)
                lines.append(
                    f"  + Bảng `{sc.table_name}` (grain={sc.grain}): các cột liên quan `[{cols_str}]` ({sc.rationale})"
                )
            for jp in grounded.selected_schema.join_paths:
                warn = " [CẢNH BÁO FANOUT 1-N]" if jp.fanout_warning else ""
                lines.append(
                    f"  + Gợi ý JOIN: `{jp.left_table}.{jp.left_column} = {jp.right_table}.{jp.right_column}` ({jp.cardinality}){warn}"
                )

        if grounded.matched_values:
            lines.append("- **Giá trị thực tế trong DB đã đối chiếu (Grounded Values)**:")
            for mv in grounded.matched_values:
                lines.append(
                    f"  + Cụm từ `{mv.raw_text}` -> Cột `{mv.table_name}.{mv.column_name}` = `{mv.matched_db_value!r}`"
                )

        return "\n".join(lines)

    @staticmethod
    def to_b05_evidence_proof(grounded: GroundedQuestion) -> EvidenceProof:
        """Convert GroundedQuestion coverage result into a B0.5 catalog-verified EvidenceProof."""
        if grounded.is_directly_unanswerable and grounded.missing_evidence_proof is not None:
            mp = grounded.missing_evidence_proof
            return EvidenceProof(
                capability_status="unsupported",
                coverage_status="unsupported",
                checked_all_sources=mp.checked_all_sources,
                missing_fields=list(mp.missing_fields),
                source_kind="catalog_verified",
                proof=mp.reason,
            )

        return EvidenceProof(
            capability_status=grounded.coverage_status.value,
            coverage_status=grounded.coverage_status.value,
            checked_all_sources=True,
            missing_fields=[],
            source_kind="catalog_verified",
            proof="Verified by Component C Answerability Precheck",
        )


__all__ = [
    "B02ContextAdapter",
    "GroundingToPlannerAdapter",
]

