"""Bộ giải mã (parser) và trích xuất kết quả Text-to-SQL từ văn bản sinh ra của LLM."""

from __future__ import annotations

import json
import re
from typing import Any

from .errors import Text2SQLParseError
from .types import Text2SQLResult


def extract_tables_from_sql(sql: str) -> tuple[str, ...]:
    """Trích xuất tên các bảng từ mệnh đề FROM và JOIN trong câu SQL đơn giản."""
    if not sql:
        return ()
    pattern = r"\b(?:FROM|JOIN)\s+([\"`]?[\w\.]+[\"`]?)"
    matches = re.findall(pattern, sql, re.IGNORECASE)
    cleaned = []
    for m in matches:
        tbl = m.strip("`\"' ")
        if tbl and tbl.upper() not in {"SELECT", "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT"}:
            if tbl not in cleaned:
                cleaned.append(tbl)
    return tuple(cleaned)


def infer_answer_type_from_sql(sql: str) -> str:
    """Suy luận answer_type sơ bộ nếu model không cung cấp tường minh."""
    sql_upper = sql.upper()
    if re.search(r"\bCOUNT\s*\(", sql_upper):
        return "number"
    if re.search(r"\b(SUM|AVG|MIN|MAX)\s*\(", sql_upper):
        return "number"
    if re.search(r"\b(DATE|STRFTIME|STRPTIME)\b", sql_upper):
        return "date"
    if "LIMIT 1" in sql_upper and not re.search(r",", sql.split("FROM")[0] if "FROM" in sql_upper else ""):
        return "string"
    return "table"


def clean_markdown_block(text: str) -> str:
    """Bóc tách nội dung bên trong block markdown ```...``` nếu có."""
    text = text.strip()
    match = re.search(r"```(?:json|sql)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


def parse_text2sql_response(raw_text: str) -> Text2SQLResult:
    """
    Parse chuỗi phản hồi của LLM thành đối tượng Text2SQLResult chuẩn mực.
    Xử lý linh hoạt cả trường hợp JSON chuẩn, JSON bọc trong markdown,
    hoặc trường hợp fallback khi model chỉ trả về câu lệnh SQL thô.
    """
    if not raw_text or not raw_text.strip():
        raise Text2SQLParseError("Phản hồi từ LLM hoàn toàn rỗng.")

    cleaned_text = clean_markdown_block(raw_text)

    # 1. Thử giải mã JSON
    data: dict[str, Any] | None = None
    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError:
        # Thử tìm object JSON đầu tiên trong chuỗi
        json_match = re.search(r"\{[\s\S]*\}", cleaned_text)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

    if isinstance(data, dict):
        status = str(data.get("status", "answerable")).lower()
        if status not in {"answerable", "unanswerable"}:
            status = "unanswerable" if data.get("sql") is None else "answerable"

        if status == "unanswerable":
            return Text2SQLResult(
                status="unanswerable",
                answer_type=None,
                sql=None,
                tables_used=(),
                assumptions=tuple(data.get("assumptions") or ()),
                reason=data.get("reason") or "Không thể trả lời từ dữ liệu hiện có.",
            )

        sql = data.get("sql")
        if isinstance(sql, str):
            sql = clean_markdown_block(sql).strip()
            # Xóa dấu chấm phẩy ở cuối nếu có
            sql = re.sub(r";+\s*$", "", sql)

        tables = data.get("tables_used") or ()
        if not tables and sql:
            tables = extract_tables_from_sql(sql)

        answer_type = data.get("answer_type")
        if not answer_type and sql:
            answer_type = infer_answer_type_from_sql(sql)

        return Text2SQLResult(
            status="answerable",
            answer_type=answer_type or "generic",
            sql=sql,
            tables_used=tuple(tables),
            assumptions=tuple(data.get("assumptions") or ()),
            reason=None,
        )

    # 2. Fallback: Nếu model sinh trực tiếp câu SQL mà không bọc JSON
    sql_candidate = cleaned_text.strip()
    if re.search(r"^\s*(?:SELECT|WITH)\b", sql_candidate, re.IGNORECASE):
        sql_clean = re.sub(r";+\s*$", "", sql_candidate)
        tables = extract_tables_from_sql(sql_clean)
        ans_type = infer_answer_type_from_sql(sql_clean)
        return Text2SQLResult(
            status="answerable",
            answer_type=ans_type,
            sql=sql_clean,
            tables_used=tables,
            assumptions=(),
            reason=None,
        )

    # 3. Fallback: Nếu model trả lời dạng văn bản từ chối (unanswerable)
    lower_text = cleaned_text.lower()
    unanswerable_cues = ["không thể trả lời", "không đủ dữ liệu", "thiếu cột", "thiếu bảng", "unanswerable"]
    if any(cue in lower_text for cue in unanswerable_cues):
        return Text2SQLResult(
            status="unanswerable",
            answer_type=None,
            sql=None,
            tables_used=(),
            assumptions=(),
            reason=cleaned_text,
        )

    raise Text2SQLParseError(f"Không thể trích xuất JSON hoặc câu SQL hợp lệ từ phản hồi: {raw_text[:200]}")

