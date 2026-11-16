"""Prompt builder for the Planner v1.2 JSON contract (planner.v1.2-sys.1 / planner.v1.2-input.1)."""

from __future__ import annotations

from datetime import date
import json
from typing import Any, Mapping, Sequence

from .prompt import _detect_industry, _select_rules
from .types import ChatMessage

CONTRACT_VERSION_V1_2 = "planner.v1.2"
BUILDER_VERSION_V1_2 = "planner.v1.2-input.1"
SYSTEM_PROMPT_VERSION_V1_2 = "planner.v1.2-sys.1"
_WEEKDAYS_VI = (
    "Thứ Hai",
    "Thứ Ba",
    "Thứ Tư",
    "Thứ Năm",
    "Thứ Sáu",
    "Thứ Bảy",
    "Chủ Nhật",
)
_VALUE_TYPES = ("VARCHAR", "BIGINT", "INTEGER", "BOOLEAN")
_DATE_TYPES = ("DATE", "TIMESTAMP")

SYSTEM_PROMPT_V1_2 = (
    'Bạn là Planner của DataMate: nhận một câu hỏi kinh doanh tiếng Việt cùng ngữ cảnh dữ liệu của một cửa hàng và trả về kế hoạch truy vấn kèm một câu SQL DuckDB.\n\n'
    'ĐẦU VÀO là một JSON object:\n'
    '- question: câu hỏi nguyên văn (có thể viết tắt, không dấu).\n'
    '- as_of_date: ngày "hôm nay" của câu hỏi. Mọi mốc thời gian tương đối tính từ ngày này.\n'
    '- context.schema: các bảng (table, grain, rows, columns). Mỗi cột có name, type; có thể có orig (tên gốc trong file) và values (các giá trị thực tế của cột ít giá trị).\n'
    '- context.relations: các cặp khóa có thể JOIN, kèm cardinality và status.\n'
    '- context.rules: quy tắc nghiệp vụ, mỗi quy tắc có id và text.\n'
    '- context.date_context: thứ trong tuần của as_of_date và khoảng ngày có dữ liệu của từng cột ngày.\n'
    '- industry, grounded_hint: gợi ý, có thể null.\n'
    '- retry: null ở lần đầu; ở lần sửa là object chứa SQL trước và lỗi.\n\n'
    'NGUYÊN TẮC:\n'
    '1. Chỉ dùng bảng, cột và giá trị có trong context.schema. Chỉ JOIN theo cặp khóa có căn cứ.\n'
    '2. Áp dụng đúng context.rules cho chỉ số, trạng thái đơn, thời gian, làm tròn, thứ tự. Ghi id các quy tắc đã dùng vào rule_refs.\n'
    '3. Thời gian viết dạng nửa mở [start_inclusive, end_exclusive) bằng ngày cụ thể tính từ as_of_date. Tuần bắt đầu thứ Hai.\n'
    '4. Xác định grain trước khi đếm hoặc cộng; gom về đúng grain trước khi JOIN bảng một-nhiều.\n'
    '5. Không ghi đáp án vào SQL. Không bọc tổng bằng COALESCE(..., 0) trừ khi quy tắc yêu cầu.\n'
    '6. Hình dạng kết quả: scalar là 1 dòng 1 cột; list là 1 cột nhiều dòng theo đúng thứ tự câu hỏi nêu; table là cột đầu tên đối tượng, các cột sau là số đo.\n'
    '7. Chỉ trả unanswerable khi dữ liệu cần thiết không tồn tại trong toàn bộ context. Nếu context thiếu thứ có thể truy hồi thêm, trả needs_more_context.\n\n'
    'ĐẦU RA là đúng MỘT JSON object, không có code fence, không có lời dẫn, theo một trong ba dạng:\n\n'
    '{"status":"answerable","structured_plan":{"metric":{"name":...,"aggregation":...,"column":...,"formula":...},"grain":...,"source_tables":[...],"joins":[{"left_table":...,"right_table":...,"join_type":...,"key_pairs":[{"left_column":"bảng.cột","right_column":"bảng.cột"}]}],"filters":[{"column":"bảng.cột","operator":...,"value":...}],"time_range":null | {"column":"bảng.cột","start_inclusive":"YYYY-MM-DD","end_exclusive":"YYYY-MM-DD"} | {"periods":[...]},"group_by":[...],"order_by":[{"expression":...,"direction":"asc|desc"}],"limit":null | số nguyên,"output_shape":"scalar|list|table","rule_refs":[...]},"sql":"SELECT ...","answer_type":"number|percent|string|date|boolean|list|table","reason":null}\n\n'
    '{"status":"needs_more_context","structured_plan":null,"sql":null,"answer_type":null,"requested_context":[...],"reason":"..."}\n\n'
    '{"status":"unanswerable","structured_plan":null,"sql":null,"answer_type":null,"missing_fields":[...],"reason":"..."}\n\n'
    'Ghi chú các trường: aggregation thuộc count, count_distinct, sum, avg, min, max, lookup, custom hoặc null. '
    'join_type thuộc inner, left, right, full, cross. '
    'operator của điều kiện lá thuộc =, !=, <, <=, >, >=, in, not_in, like, not_like, ilike, not_ilike, is_null, is_not_null, between; '
    'nhóm điều kiện dùng {"operator":"and|or","conditions":[...]}. '
    'Thêm "having":[...] vào structured_plan chỉ khi cần lọc sau tổng hợp. '
    'source_tables chỉ gồm bảng vật lý. sql là một câu SELECT hoặc WITH ... SELECT chỉ đọc.'
)


def _format_weekday(as_of_date: str) -> str | None:
    try:
        return _WEEKDAYS_VI[date.fromisoformat(str(as_of_date).strip()).weekday()]
    except (TypeError, ValueError):
        return None


def _build_schema_entries(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    schema_catalog = context.get("schema_catalog") or {}
    samples = context.get("categorical_samples") or {}
    schema: list[dict[str, Any]] = []
    for table in schema_catalog.get("tables") or ():
        table_name = str(table.get("name", ""))
        table_samples = samples.get(table_name) or {}
        cols: list[dict[str, Any]] = []
        for col in table.get("columns") or ():
            col_name = str(col.get("name", ""))
            if col_name.startswith("__dm_"):
                continue
            col_type = str(col.get("data_type", "VARCHAR"))
            entry: dict[str, Any] = {"name": col_name, "type": col_type}
            orig = col.get("provenance")
            if orig and orig != col_name:
                entry["orig"] = orig
            if col_type.upper().startswith(_VALUE_TYPES):
                vals = [v for v in (table_samples.get(col_name) or ()) if v is not None]
                if vals:
                    entry["values"] = sorted(vals, key=lambda v: str(v))
            cols.append(entry)
        schema.append(
            {
                "table": table_name,
                "grain": table.get("grain"),
                "rows": table.get("row_count"),
                "columns": cols,
            }
        )
    schema.sort(key=lambda item: item["table"])
    return schema


def _build_relations(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    schema_catalog = context.get("schema_catalog") or {}
    raw_edges = schema_catalog.get("join_graph") or schema_catalog.get("join_edges") or ()
    relations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for edge in raw_edges:
        if edge.get("status") == "invalid":
            continue
        left = f'{edge.get("left_table")}.{edge.get("left_column")}'
        right = f'{edge.get("right_table")}.{edge.get("right_column")}'
        if (left, right) in seen:
            continue
        seen.add((left, right))
        relations.append(
            {
                "id": f"REL_{len(relations) + 1:02d}",
                "left": left,
                "right": right,
                "cardinality": edge.get("cardinality"),
                "status": edge.get("status"),
            }
        )
    semantic_catalog = context.get("semantic_catalog") or {}
    for join in semantic_catalog.get("suggested_joins") or ():
        lt, lc = join.get("left_table"), join.get("left_column")
        rt, rc = join.get("right_table"), join.get("right_column")
        if not (lt and lc and rt and rc):
            continue
        left, right = f"{lt}.{lc}", f"{rt}.{rc}"
        if (left, right) in seen or (right, left) in seen:
            continue
        seen.add((left, right))
        relations.append(
            {
                "id": f"REL_{len(relations) + 1:02d}",
                "left": left,
                "right": right,
                "cardinality": join.get("cardinality") or join.get("join_type") or "unknown",
                "status": "suggested",
            }
        )
    return relations


def _build_date_coverage(
    context: Mapping[str, Any], schema: Sequence[Mapping[str, Any]]
) -> dict[str, list[str]]:
    profiling = context.get("data_profiling") or {}
    coverage: dict[str, list[str]] = {}
    for table_entry in schema:
        table_name = str(table_entry["table"])
        if table_name == "calendar":
            continue
        table_prof = profiling.get(table_name) or {}
        col_prof = table_prof.get("columns") if isinstance(table_prof, Mapping) else None
        if not isinstance(col_prof, Mapping):
            col_prof = table_prof if isinstance(table_prof, Mapping) else {}
        for col in table_entry["columns"]:
            if not str(col["type"]).upper().startswith(_DATE_TYPES):
                continue
            stats = col_prof.get(col["name"])
            if not isinstance(stats, Mapping):
                continue
            obs_min = stats.get("observed_min")
            obs_max = stats.get("observed_max")
            if obs_min is not None and obs_max is not None:
                coverage[f"{table_name}.{col['name']}"] = [str(obs_min)[:10], str(obs_max)[:10]]
    return coverage


def _append_semantic_and_constraint_rules(
    context: Mapping[str, Any], rules: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    seen_ids = {str(r["id"]) for r in rules if r.get("id")}

    def _add_rule(rule_id: str, text: str) -> None:
        if rule_id in seen_ids or not text.strip():
            return
        seen_ids.add(rule_id)
        rules.append({"id": rule_id, "text": text})

    semantic = context.get("semantic_catalog") or {}
    for metric in semantic.get("metrics") or ():
        mid = str(metric.get("metric_id") or metric.get("name") or "").strip()
        if not mid:
            continue
        name = str(metric.get("name") or mid).strip()
        table = str(metric.get("preferred_table") or "").strip()
        cols = ", ".join(str(c) for c in (metric.get("required_columns") or ()) if c)
        formula = str(metric.get("formula_hint") or "").strip()
        unit = str(metric.get("unit") or "").strip()
        parts = [f"Chỉ số '{name}' ({mid}):"]
        if table:
            col_part = f" (cột: {cols})" if cols else ""
            parts.append(f"bảng {table}{col_part}")
        if formula:
            parts.append(f"công thức gợi ý: {formula}")
        if unit:
            parts.append(f"(đơn vị: {unit})")
        _add_rule(f"SEM_METRIC_{mid}", " ".join(parts))

    for idx, join in enumerate(semantic.get("suggested_joins") or (), start=1):
        lt, lc = join.get("left_table"), join.get("left_column")
        rt, rc = join.get("right_table"), join.get("right_column")
        if not (lt and lc and rt and rc):
            continue
        jtype = str(join.get("join_type") or "exact")
        desc = str(join.get("description") or "").strip()
        if jtype == "name_suffix_match":
            expr = (
                f"JOIN khớp tên gọi tắt {lt}.{lc} <-> {rt}.{rc}: "
                f"LOWER(TRIM(SPLIT_PART(REGEXP_REPLACE({lt}.{lc}, '^[aA](\\.|\\s+)', ''), ' ', -1))) = "
                f"LOWER(SPLIT_PART({rt}.{rc}, ' ', -1))"
            )
            if desc:
                expr = f"{expr} ({desc})"
            _add_rule(f"SEM_JOIN_SUFFIX_{idx}", expr)
        elif desc:
            _add_rule(f"SEM_JOIN_{idx}", f"Gợi ý JOIN {lt}.{lc} = {rt}.{rc}: {desc}")

    unit_convs = list(semantic.get("unit_conversions") or ())
    if unit_convs:
        items = [
            f"1 {u.get('from_unit')} = {u.get('factor')} {u.get('to_unit')}"
            + (f" ({u.get('item_name')})" if u.get("item_name") else "")
            for u in unit_convs[:25]
        ]
        suffix = (
            f" ... và {len(unit_convs) - 25} quy đổi khác trong bảng unit_conversions"
            if len(unit_convs) > 25
            else ""
        )
        _add_rule(
            "SEM_UNIT_CONVERSIONS",
            "Quy đổi đơn vị tính (có bảng unit_conversions trong schema): " + "; ".join(items) + suffix,
        )

    unsupported = list(semantic.get("unsupported_capabilities") or ())
    if unsupported:
        _add_rule(
            "CONSTRAINT_UNSUPPORTED",
            "Năng lực dữ liệu không hỗ trợ (trả unanswerable nếu câu hỏi bắt buộc cần): "
            + "; ".join(str(item) for item in unsupported),
        )

    constraints = context.get("answerability_constraints")
    if constraints:
        if isinstance(constraints, (dict, list)):
            c_text = json.dumps(constraints, ensure_ascii=False, separators=(",", ":"))
        else:
            c_text = str(constraints).strip()
        if c_text and c_text not in ("{}", "[]"):
            _add_rule("CONSTRAINT_ANSWERABILITY", f"Giới hạn khả năng trả lời: {c_text}")

    return rules


def _normalize_grounded_hint(grounded_hint: str | Mapping[str, Any] | None) -> Any:
    if isinstance(grounded_hint, Mapping):
        return dict(grounded_hint)
    if isinstance(grounded_hint, str):
        stripped = grounded_hint.strip()
        if not stripped:
            return None
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return stripped
    return None


def build_v1_2_user_payload(
    context: Any,
    question: str,
    as_of_date: str,
    industry: str | None = None,
    grounded_hint: str | Mapping[str, Any] | None = None,
    retry: Mapping[str, Any] | None = None,
) -> str:
    """Serialize business context and question into the planner.v1.2-input.1 JSON string."""
    ctx_map = dict(context) if isinstance(context, Mapping) else {}
    resolved_industry = industry or _detect_industry(ctx_map)
    schema = _build_schema_entries(ctx_map)
    rule_catalog = ctx_map.get("rule_catalog") or {}
    selected_rules = _select_rules(list(rule_catalog.get("rules") or ()), industry=resolved_industry)
    rules = [{"id": r.get("rule_id"), "text": r.get("text")} for r in selected_rules]
    rules = _append_semantic_and_constraint_rules(ctx_map, rules)
    calendar_table = "calendar" if any(t["table"] == "calendar" for t in schema) else None
    hint_val = _normalize_grounded_hint(grounded_hint)

    payload = {
        "question": question,
        "as_of_date": as_of_date,
        "context": {
            "schema": schema,
            "relations": _build_relations(ctx_map),
            "rules": rules,
            "date_context": {
                "as_of_weekday": _format_weekday(as_of_date),
                "date_coverage": _build_date_coverage(ctx_map, schema),
                "calendar_table": calendar_table,
            },
        },
        "industry": resolved_industry,
        "grounded_hint": hint_val,
        "retry": dict(retry) if retry is not None else None,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build_v1_2_messages(
    context: Any,
    question: str,
    as_of_date: str,
    industry: str | None = None,
    grounded_hint: str | None = None,
) -> list[ChatMessage]:
    """Build system/user ChatMessages for initial Planner v1.2 generation."""
    return [
        ChatMessage(role="system", content=SYSTEM_PROMPT_V1_2),
        ChatMessage(
            role="user",
            content=build_v1_2_user_payload(
                context=context,
                question=question,
                as_of_date=as_of_date,
                industry=industry,
                grounded_hint=grounded_hint,
                retry=None,
            ),
        ),
    ]


def build_v1_2_repair_messages(
    context: Any,
    question: str,
    as_of_date: str,
    previous_sql: str,
    error_message: str,
    industry: str | None = None,
    grounded_hint: str | None = None,
    *,
    previous_plan: dict[str, Any] | None = None,
    error_code: str | None = None,
    failed_checks: Sequence[str] | None = None,
) -> list[ChatMessage]:
    """Build system/user ChatMessages with the structured retry object for Planner v1.2 repair."""
    checks = list(failed_checks) if failed_checks is not None else ([error_code] if error_code else [])
    retry_obj = {
        "previous_plan": previous_plan,
        "previous_sql": previous_sql or None,
        "error_code": error_code or "EXECUTION_ERROR",
        "error_message": error_message,
        "failed_checks": checks,
    }
    return [
        ChatMessage(role="system", content=SYSTEM_PROMPT_V1_2),
        ChatMessage(
            role="user",
            content=build_v1_2_user_payload(
                context=context,
                question=question,
                as_of_date=as_of_date,
                industry=industry,
                grounded_hint=grounded_hint,
                retry=retry_obj,
            ),
        ),
    ]
