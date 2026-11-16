"""Adapters bridging Component C (Grounding) with B0.2 (Context), B0.3 (Planner), and B0.5 (Gate)."""

from __future__ import annotations

from datetime import date, timedelta
import json
import logging
from typing import Any, Sequence

from datamate.ingestion.metadata_adapter import BusinessContextSchemaReader
from datamate.context.contracts import BusinessContext, BusinessRule, RuleCatalog
from datamate.gate.contracts import EvidenceProof

from .contracts import GroundedQuestion
from .protocols import (
    BusinessContextProtocol,
    CalendarEventSpec,
    ColumnSpec,
    JoinSpec,
    MetricSpec,
    TableSpec,
)

logger = logging.getLogger(__name__)

_ROLE_MAP: dict[str, str] = {
    "identifier": "id",
    "id": "id",
    "date": "date",
    "money": "money",
    "quantity": "quantity",
    "text": "text",
    "name": "name",
    "category": "category",
    "status": "category",
}


def _extract_column_aliases(raw_names: Sequence[str | None]) -> tuple[str, ...]:
    aliases: list[str] = []
    for raw in raw_names:
        if not raw or not str(raw).strip():
            continue
        clean = str(raw).strip()
        if clean not in aliases:
            aliases.append(clean)
        lower = clean.lower()
        for prefix in ("mã ", "tên ", "số ", "ngày "):
            if lower.startswith(prefix) and len(clean) > len(prefix) + 1:
                stripped = clean[len(prefix) :].strip()
                if stripped and stripped not in aliases:
                    aliases.append(stripped)
    return tuple(aliases)


class B02ContextAdapter(BusinessContextProtocol):
    """Adapter wrapping a B0.2 BusinessContext to satisfy BusinessContextProtocol."""

    def __init__(self, b02_context: BusinessContext) -> None:
        self._ctx = b02_context
        self.business_id: str = b02_context.business_id
        self._tables: tuple[TableSpec, ...] = self._build_tables()
        self._join_edges: tuple[JoinSpec, ...] = self._build_joins()
        self._metrics: tuple[MetricSpec, ...] = self._build_metrics()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> B02ContextAdapter:
        """Construct a B02ContextAdapter from a serialized BusinessContext JSON dictionary."""
        schema_catalog = BusinessContextSchemaReader().read(payload)
        raw_rc = payload.get("rule_catalog") or {}
        raw_rules = raw_rc.get("rules") or ()
        rules = tuple(
            BusinessRule(
                rule_id=str(r.get("rule_id", "")),
                text=str(r.get("text", "")),
                source=str(r.get("source", "")),
                scope=str(r.get("scope", "global")),
                precedence=int(r.get("precedence", 0)),
                status=str(r.get("status", "descriptive")),
                required_fields=tuple(str(f) for f in (r.get("required_fields") or ())),
                expression=r.get("expression"),
                validation_messages=tuple(
                    str(m) for m in (r.get("validation_messages") or ())
                ),
                topic=r.get("topic"),
                industry=r.get("industry"),
                question_id=r.get("question_id"),
                requirements=tuple(str(req) for req in (r.get("requirements") or ())),
                binding_evidence=tuple(
                    str(be) for be in (r.get("binding_evidence") or ())
                ),
            )
            for r in raw_rules
            if isinstance(r, dict)
        )
        rule_catalog = RuleCatalog(
            rules=rules,
            warnings=tuple(str(w) for w in (raw_rc.get("warnings") or ())),
            business_id=raw_rc.get("business_id"),
        )
        ctx = BusinessContext(
            contract_version=str(payload.get("contract_version", "1.0")),
            business_id=str(payload["business_id"]),
            schema_catalog=schema_catalog,
            rule_catalog=rule_catalog,
            data_profiling=payload.get("data_profiling"),
            business_metadata=payload.get("business_metadata"),
            answerability_constraints=payload.get("answerability_constraints"),
            normalized_data_handle=payload.get("normalized_data_handle"),
            semantic_catalog=payload.get("semantic_catalog"),
        )
        return cls(ctx)

    def _build_tables(self) -> tuple[TableSpec, ...]:
        specs: list[TableSpec] = []
        profiling = self._ctx.data_profiling or {}
        schema_mapping = (self._ctx.business_metadata or {}).get("schema_mapping") or {}

        for tbl in self._ctx.schema_catalog.tables:
            tbl_prof = profiling.get(tbl.name) if isinstance(profiling, dict) else None
            tbl_map = (
                schema_mapping.get(tbl.name)
                if isinstance(schema_mapping, dict)
                else None
            ) or {}
            cols_map = tbl_map.get("columns") if isinstance(tbl_map, dict) else {}
            if not isinstance(cols_map, dict):
                cols_map = {}

            # Extract sample values from profile_rows or data_profiling['samples']
            samples_by_col: dict[str, list[Any]] = {c.name: [] for c in tbl.columns}
            sample_rows: Sequence[dict[str, Any]] = tbl.profile_rows
            if not sample_rows and isinstance(tbl_prof, dict):
                sample_rows = tbl_prof.get("samples") or ()

            for row in sample_rows:
                if not isinstance(row, dict):
                    continue
                for col_name, val in row.items():
                    if (
                        col_name in samples_by_col
                        and val is not None
                        and val not in samples_by_col[col_name]
                        and len(samples_by_col[col_name]) < 15
                    ):
                        samples_by_col[col_name].append(val)

            # Extract date coverage bounds from data_profiling column stats
            prof_cols = (
                tbl_prof.get("columns")
                if isinstance(tbl_prof, dict) and isinstance(tbl_prof.get("columns"), dict)
                else {}
            )
            min_dates: list[str] = []
            max_dates: list[str] = []
            for c_stats in prof_cols.values():
                if isinstance(c_stats, dict):
                    obs_min = c_stats.get("observed_min")
                    obs_max = c_stats.get("observed_max")
                    if isinstance(obs_min, str) and len(obs_min) >= 10:
                        min_dates.append(obs_min[:10])
                    if isinstance(obs_max, str) and len(obs_max) >= 10:
                        max_dates.append(obs_max[:10])

            col_specs: list[ColumnSpec] = []
            for col in tbl.columns:
                if col.name.startswith("__dm_"):
                    continue
                c_map_entry = cols_map.get(col.name)
                if not isinstance(c_map_entry, dict):
                    c_map_entry = {}
                raw_role = str(c_map_entry.get("role", "")).lower()
                role = _ROLE_MAP.get(raw_role, "")
                if not role:
                    dt_upper = (col.data_type or "").upper()
                    if any(t in dt_upper for t in ("DATE", "TIMESTAMP")):
                        role = "date"
                    elif any(
                        t in dt_upper for t in ("DECIMAL", "NUMERIC", "DOUBLE", "FLOAT")
                    ) and any(
                        k in col.name.lower()
                        for k in ("tien", "gia", "doanh_thu", "amount", "price", "revenue")
                    ):
                        role = "money"
                    elif col.name.lower().startswith("ma_") or col.name.lower().endswith("_id"):
                        role = "id"

                aliases = _extract_column_aliases(
                    (col.provenance, c_map_entry.get("original_name"))
                )
                col_specs.append(
                    ColumnSpec(
                        name=col.name,
                        data_type=col.data_type,
                        aliases=aliases,
                        sample_values=tuple(samples_by_col.get(col.name, ())),
                        role=role,
                        null_ratio=col.null_ratio or 0.0,
                    )
                )

            tbl_aliases: list[str] = []
            family = tbl_map.get("family") if isinstance(tbl_map, dict) else None
            if isinstance(family, str) and family.strip() and family != tbl.name:
                tbl_aliases.append(family.strip())
            if tbl.provenance and tbl.provenance.strip():
                tbl_aliases.append(tbl.provenance.strip())

            specs.append(
                TableSpec(
                    name=tbl.name,
                    columns=tuple(col_specs),
                    grain=tbl.grain or "unknown",
                    aliases=tuple(tbl_aliases),
                    row_count=tbl.row_count or 0,
                    date_coverage_start=min(min_dates) if min_dates else None,
                    date_coverage_end=max(max_dates) if max_dates else None,
                )
            )
        return tuple(specs)

    def _build_joins(self) -> tuple[JoinSpec, ...]:
        joins: list[JoinSpec] = []
        for edge in self._ctx.schema_catalog.join_graph:
            if getattr(edge, "status", "validated") != "validated":
                continue
            stats = getattr(edge, "statistics", None)
            has_null_keys = bool(
                stats is not None
                and (
                    getattr(stats, "left_null_rows", 0) > 0
                    or getattr(stats, "right_null_rows", 0) > 0
                )
            )
            joins.append(
                JoinSpec(
                    left_table=edge.left_table,
                    left_column=edge.left_column,
                    right_table=edge.right_table,
                    right_column=edge.right_column,
                    cardinality=edge.cardinality,
                    fanout_warning=edge.fanout_warning,
                    confidence=edge.confidence,
                    additional_key_pairs=getattr(edge, "additional_key_pairs", ()),
                    null_key_warning=has_null_keys,
                )
            )
        return tuple(joins)

    def _build_metrics(self) -> tuple[MetricSpec, ...]:
        metrics: list[MetricSpec] = []
        seen_ids: set[str] = set()

        # 1. Ưu tiên nạp từ SemanticCatalog nếu đã được biên dịch lúc prepare_bundle
        raw_semantic = getattr(self._ctx, "semantic_catalog", None)
        if isinstance(raw_semantic, dict) and raw_semantic.get("metrics"):
            for m_dict in raw_semantic["metrics"]:
                m_id = m_dict.get("metric_id")
                if m_id and m_id not in seen_ids:
                    seen_ids.add(m_id)
                    metrics.append(
                        MetricSpec(
                            metric_id=m_id,
                            aliases=tuple(m_dict.get("aliases") or (m_id,)),
                            preferred_table=m_dict.get("preferred_table") or "",
                            required_columns=tuple(m_dict.get("required_columns") or ()),
                            formula_hint=m_dict.get("formula_hint") or "",
                            unit=m_dict.get("unit") or "VND",
                        )
                    )

        # 2. Dynamic Discovery qua RuleSchemaMatcher nếu chưa có trong context
        if not metrics:
            try:
                from datamate.context.semantic_extractor import RuleSchemaMatcher
                catalog = RuleSchemaMatcher().extract_semantic_catalog(
                    business_id=getattr(self._ctx, "business_id", ""),
                    schema=self._ctx.schema_catalog,
                    rules=self._ctx.rule_catalog.rules,
                )
                for m in catalog.metrics:
                    if m.metric_id not in seen_ids:
                        seen_ids.add(m.metric_id)
                        metrics.append(
                            MetricSpec(
                                metric_id=m.metric_id,
                                aliases=m.aliases,
                                preferred_table=m.preferred_table,
                                required_columns=m.required_columns,
                                formula_hint=m.formula_hint,
                                unit=m.unit,
                            )
                        )
            except Exception as exc:
                logger.debug("RuleSchemaMatcher failed: %s; falling back to basic heuristics", exc)

        # 3. Fallback an toàn cho revenue & order_count nếu không tìm thấy gì
        if "revenue" not in seen_ids:
            for tbl in self._tables:
                money_cols = [
                    c.name
                    for c in tbl.columns
                    if c.role == "money"
                    or any(
                        k in c.name.lower()
                        for k in ("tong_tien", "thanh_tien", "doanh_thu", "tien", "amount")
                    )
                ]
                if money_cols:
                    seen_ids.add("revenue")
                    metrics.append(
                        MetricSpec(
                            metric_id="revenue",
                            aliases=("doanh thu", "tổng tiền"),
                            preferred_table=tbl.name,
                            required_columns=(money_cols[0],),
                            unit="VND",
                        )
                    )
                    break

        if "order_count" not in seen_ids:
            worker_tables = {
                t.name for t in self._tables
                if any(k in t.name.lower() for k in ("tho", "nhan_vien", "employee", "worker", "danh_sach"))
            }
            for tbl in self._tables:
                if tbl.name in worker_tables or tbl.name == "calendar":
                    continue
                date_cols = [c.name for c in tbl.columns if c.role == "date" or "ngay" in c.name.lower()]
                if date_cols:
                    seen_ids.add("order_count")
                    metrics.append(
                        MetricSpec(
                            metric_id="order_count",
                            aliases=("số đơn", "số lượt", "lượt xe", "phiếu", "số phiếu", "bao nhiêu đơn"),
                            preferred_table=tbl.name,
                            required_columns=(date_cols[0],),
                            unit="count",
                        )
                    )
                    break

        return tuple(metrics)

    def get_tables(self) -> Sequence[TableSpec]:
        return self._tables

    def get_join_edges(self) -> Sequence[JoinSpec]:
        return self._join_edges

    def get_metrics(self) -> Sequence[MetricSpec]:
        return self._metrics

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
                warn_parts: list[str] = []
                if jp.fanout_warning:
                    warn_parts.append("[CẢNH BÁO FANOUT 1-N]")
                if jp.null_key_warning:
                    warn_parts.append("[CẢNH BÁO KHÓA NULL - CÂN NHẮC LEFT JOIN]")
                warn = (" " + " ".join(warn_parts)) if warn_parts else ""
                join_expr = " AND ".join(
                    f"{jp.left_table}.{left_col} = {jp.right_table}.{right_col}"
                    for left_col, right_col in jp.key_pairs
                )
                lines.append(
                    f"  + Gợi ý JOIN: `{join_expr}` ({jp.cardinality}){warn}"
                )

        if grounded.matched_values:
            lines.append("- **Giá trị thực tế trong DB đã đối chiếu (Grounded Values)**:")
            for mv in grounded.matched_values:
                lines.append(
                    f"  + Cụm từ `{mv.raw_text}` -> Cột `{mv.table_name}.{mv.column_name}` = `{mv.matched_db_value!r}`"
                )

        return "\n".join(lines)

    @staticmethod
    def format_grounded_hint_for_v1_2(grounded: GroundedQuestion) -> str:
        """Render a compact JSON hint aligned with the planner.v1.2 half-open schema."""
        hint: dict[str, Any] = {
            "operation": grounded.intent.operation.value,
            "answer_type": grounded.answer_type_hint.value,
        }
        if grounded.intent.target_metrics:
            hint["metrics"] = list(grounded.intent.target_metrics)
        if grounded.intent.top_k is not None:
            hint["top_k"] = grounded.intent.top_k
            hint["sort_order"] = grounded.intent.sort_order.lower()
        if grounded.resolved_time_ranges:
            ranges = []
            for tr in grounded.resolved_time_ranges:
                end_excl = (
                    (date.fromisoformat(tr.end_date) + timedelta(days=1)).isoformat()
                    if tr.inclusive
                    else tr.end_date
                )
                entry: dict[str, Any] = {
                    "expr": tr.raw_expression,
                    "role": tr.date_role.value,
                    "start_inclusive": tr.start_date,
                    "end_exclusive": end_excl,
                }
                if tr.comparison_start_date and tr.comparison_end_date:
                    comp_end_excl = (
                        (date.fromisoformat(tr.comparison_end_date) + timedelta(days=1)).isoformat()
                        if tr.inclusive
                        else tr.comparison_end_date
                    )
                    entry["compare_start_inclusive"] = tr.comparison_start_date
                    entry["compare_end_exclusive"] = comp_end_excl
                ranges.append(entry)
            hint["time_ranges"] = ranges
        if grounded.selected_schema.primary_table:
            hint["primary_table"] = grounded.selected_schema.primary_table
            warnings = []
            for jp in grounded.selected_schema.join_paths:
                if jp.fanout_warning or jp.null_key_warning:
                    pairs = [f"{jp.left_table}.{l}={jp.right_table}.{r}" for l, r in jp.key_pairs]
                    flags = []
                    if jp.fanout_warning:
                        flags.append("fanout_1_n")
                    if jp.null_key_warning:
                        flags.append("null_key_left_join")
                    warnings.append({"join": pairs, "flags": flags})
            if warnings:
                hint["join_warnings"] = warnings
        if grounded.matched_values:
            hint["matched_values"] = [
                {
                    "text": mv.raw_text,
                    "column": f"{mv.table_name}.{mv.column_name}",
                    "value": mv.matched_db_value,
                }
                for mv in grounded.matched_values
            ]
        return json.dumps(hint, ensure_ascii=False, separators=(",", ":"))

    to_planner_prompt_markdown = format_grounded_hint_for_planner

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

    to_gate_evidence_proof = to_b05_evidence_proof


BusinessContextAdapter = B02ContextAdapter

__all__ = [
    "B02ContextAdapter",
    "BusinessContextAdapter",
    "GroundingToPlannerAdapter",
]
