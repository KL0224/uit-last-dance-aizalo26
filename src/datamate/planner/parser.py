"""Bộ giải mã (parser) và trích xuất kết quả Text-to-SQL từ văn bản sinh ra của LLM."""

from __future__ import annotations

import json
import re
from typing import Any

import sqlglot
from sqlglot import errors as sqlglot_errors
from sqlglot import exp

from .errors import Text2SQLParseError
from .types import Text2SQLResult


VALID_ANSWER_TYPES = frozenset(
    {"number", "percent", "string", "date", "boolean", "list", "table"}
)
_ANSWER_TYPE_ALIASES = {
    "integer": "number",
    "int": "number",
    "float": "number",
    "double": "number",
    "decimal": "number",
    "numeric": "number",
    "money": "number",
    "count": "number",
    "text": "string",
    "varchar": "string",
    "datetime": "date",
    "timestamp": "date",
    "bool": "boolean",
    "array": "list",
    "rows": "table",
}
_MAX_BRACE_STARTS = 200
_THINK_BLOCK = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_NON_TABLE_FROM = re.compile(
    r"\b(?:EXTRACT|TRIM|SUBSTRING|OVERLAY|POSITION)\s*\(\s*(?:\w+\s+)?(?:'[^']*'\s+)?FROM\b",
    re.IGNORECASE,
)


def extract_think_blocks(text: str) -> str | None:
    """Extract concatenated reasoning text inside <think>...</think> blocks or preambles."""
    if "</think>" in text:
        if "<think>" in text:
            matches = re.findall(r"<think>([\s\S]*?)</think>", text, flags=re.IGNORECASE)
            cleaned = [m.strip() for m in matches if m.strip()]
            return "\n\n".join(cleaned) if cleaned else None
        # In cases where prompt added <think>, completion begins directly inside think and ends with </think>
        parts = text.split("</think>", 1)
        return parts[0].strip() or None
    if "<think>" in text:
        parts = text.split("<think>", 1)
        return parts[1].strip() or None

    # If no tags, check if there is reasoning text before the first markdown code fence or JSON object
    match = re.search(r"```(?:json|sql)?|(?:\n\s*\{)", text)
    if match and match.start() > 20:
        preamble = text[:match.start()].strip()
        if preamble:
            return preamble
    return None


def strip_think_blocks(text: str) -> str:
    """Remove reasoning blocks emitted by thinking models before parsing."""
    if "</think>" in text:
        return text.rsplit("</think>", 1)[1].strip()
    if "<think>" in text:
        # Thẻ <think> chưa đóng (bị cắt cụt token): toàn bộ nội dung là suy nghĩ dở dang,
        # không chứa đáp án đã chốt. Tuyệt đối không lấy SQL nháp trong phần này.
        return ""

    cleaned = _THINK_BLOCK.sub("", text).strip()
    # Nếu không có thẻ <think>, kiểm tra xem có reasoning preamble (Thinking Process:, Analysis, etc.)
    # xuất hiện trước khối ```json, ```sql hoặc { không:
    m = re.search(r"```(?:json|sql)?|(?:\n\s*\{)", cleaned)
    if m and m.start() > 20:
        preamble = cleaned[:m.start()].strip()
        if any(w in preamble.lower() for w in ("think", "analyze", "xem xét", "suy luận", "bước 1", "task:", "role:", "the user wants")):
            return cleaned[m.start():].strip()
    return cleaned


def _regex_tables(sql: str) -> list[str]:
    masked = _NON_TABLE_FROM.sub("(", sql)
    pattern = r"\b(?:FROM|JOIN)\s+([\"`]?[\w\.]+[\"`]?)"
    found = []
    for match in re.findall(pattern, masked, re.IGNORECASE):
        tbl = match.strip("`\"' ")
        if tbl and tbl.upper() not in {"SELECT", "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT"}:
            found.append(tbl)
    return found


def extract_tables_from_sql(sql: str) -> tuple[str, ...]:
    """Trích xuất tên bảng thật (không gồm CTE, không gồm cột trong EXTRACT(... FROM col))."""
    if not sql:
        return ()
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot_errors.SqlglotError:
        statements = []
    if not statements:
        names = _regex_tables(sql)
    else:
        names = []
        for stmt in statements:
            ctes = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
            for table in stmt.find_all(exp.Table):
                if table.name and table.name.lower() not in ctes:
                    names.append(table.name)
    cleaned: list[str] = []
    for name in names:
        if name not in cleaned:
            cleaned.append(name)
    # AST traversal is breadth-first; report tables in order of appearance.
    def position(name: str) -> int:
        match = re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", sql, re.IGNORECASE)
        return match.start() if match else len(sql)

    cleaned.sort(key=position)
    return tuple(cleaned)


def _outer_select(sql: str) -> exp.Select | None:
    """Trả về SELECT ngoài cùng (bỏ qua CTE/subquery); None nếu không phân tích được."""
    try:
        root = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return None
    set_op = (exp.Union, getattr(exp, "SetOperation", exp.Union))
    while isinstance(root, set_op):
        root = root.this
    return root if isinstance(root, exp.Select) else None


def _outer_limit(sql: str) -> int | None:
    """LIMIT của SELECT ngoài cùng (không tính LIMIT trong CTE/subquery)."""
    node = _outer_select(sql)
    if node is None:
        match = re.search(r"\bLIMIT\s+(\d+)\s*;?\s*$", sql, re.IGNORECASE)
        return int(match.group(1)) if match else None
    limit = node.args.get("limit")
    if limit is None:
        return None
    expr = limit.args.get("expression")
    return int(expr.name) if expr is not None and expr.name.isdigit() else None


def _outer_has_aggregate_without_group(sql: str) -> bool:
    node = _outer_select(sql)
    if node is None or node.args.get("group") is not None:
        return False
    return any(proj.find(exp.AggFunc) for proj in node.expressions)


def _extract_projection(sql: str) -> str:
    """Trích xuất danh sách cột chiếu của SELECT ngoài cùng (bỏ alias); fallback regex."""
    node = _outer_select(sql)
    if node is not None and node.expressions:
        parts = []
        for proj in node.expressions:
            inner = proj.this if isinstance(proj, exp.Alias) else proj
            parts.append(inner.sql(dialect="duckdb"))
        return ", ".join(parts)
    parts = re.split(r"\bFROM\b", sql, maxsplit=1, flags=re.IGNORECASE)
    select_part = parts[0]
    m = re.search(r"\bSELECT\b\s+([\s\S]+)$", select_part, flags=re.IGNORECASE)
    return m.group(1).strip() if m else select_part.strip()


_MINMAX_DATE = re.compile(r"\b(?:MAX|MIN)\s*\(\s*(?:\w+\.)?\w*(?:ngay|date)\w*\s*\)", re.IGNORECASE)


def _looks_like_ratio(proj: str) -> bool:
    """Projection là phép chia/tỷ lệ (mới nên coi là percent theo từ khóa câu hỏi)."""
    low = proj.lower()
    return "/" in low or "100" in low or bool(re.search(r"percent|pct|ty_le|ti_le|ratio|rate", low))


def _has_multiple_columns(proj: str) -> bool:
    """Kiểm tra xem mệnh đề SELECT có nhiều hơn 1 cột hay không (bỏ qua dấu phẩy trong hàm)."""
    depth = 0
    in_single_quote = False
    for ch in proj:
        if ch == "'":
            in_single_quote = not in_single_quote
        elif not in_single_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif ch == "," and depth == 0:
                return True
    return False


def infer_answer_type_from_sql(sql: str) -> str:
    """Suy luận answer_type chuẩn xác dựa trên projection và LIMIT của câu SQL DuckDB."""
    sql_upper = sql.upper()
    proj = _extract_projection(sql)
    proj_upper = proj.upper()
    is_multi_col = _has_multiple_columns(proj)

    # Nếu chọn toàn bộ cột (*) hoặc có nhiều cột trong projection -> 'table'
    if proj == "*" or proj.endswith(".*") or is_multi_col:
        return "table"

    # Nếu có LIMIT > 1 với 1 cột chiếu (Top N) -> 'list'
    limit_n = _outer_limit(sql)
    if limit_n is not None and limit_n > 1 and not _outer_has_aggregate_without_group(sql):
        return "list"

    # Nếu projection chứa hàm / cột ngày tháng -> 'date'
    if (
        re.search(r"\b(DATE|STRFTIME|STRPTIME)\b", proj_upper)
        or re.search(r"\b(ngay|date|time|thang)\b", proj, re.IGNORECASE)
        or _MINMAX_DATE.search(proj)
    ):
        if not re.search(r"\b(COUNT|SUM|AVG)\s*\(", proj_upper):
            return "date"

    # Nếu projection chứa hàm đếm / tổng / trung bình -> 'number'
    if re.search(r"\b(COUNT|SUM|AVG|ROUND)\s*\(", proj_upper):
        return "number"

    # Nếu có LIMIT 1:
    if limit_n == 1:
        if re.search(r"\b(ngay|date|time|thang)\b", proj, re.IGNORECASE):
            return "date"
        return "string"

    return "number" if re.search(r"\b(COUNT|SUM|AVG)\b", sql_upper) else "string"


def normalize_answer_type(raw: Any, sql: str | None, question: str | None = None) -> str:
    """Map model output onto the nine B0.5 answer types with SQL-aware auto-correction."""
    ans: str | None = None
    if isinstance(raw, str):
        key = raw.strip().lower()
        if key in VALID_ANSWER_TYPES:
            ans = key
        elif key in _ANSWER_TYPE_ALIASES:
            ans = _ANSWER_TYPE_ALIASES[key]

    # 1. Ép kiểu bắt buộc dựa trên cú pháp SQL thực tế (chống SCALAR_SHAPE_MISMATCH và OUTPUT_TYPE_ERROR)
    if sql:
        sql_upper = sql.upper()
        proj = _extract_projection(sql)
        proj_upper = proj.upper()
        is_multi_col = _has_multiple_columns(proj)

        # A. Cột chiếu đơn với LIMIT > 1 (ví dụ Top 3, Top 5) -> BẮT BUỘC là 'list'
        outer_limit = _outer_limit(sql)
        if (
            not is_multi_col
            and proj != "*"
            and outer_limit is not None
            and outer_limit > 1
            and not _outer_has_aggregate_without_group(sql)
        ):
            return "list"

        # B. Cột chiếu ngày tháng (STRFTIME, DATE(col)) với LIMIT 1 hoặc không có aggregate số học -> BẮT BUỘC là 'date'
        if not is_multi_col:
            has_date_fn = bool(re.search(r"\b(DATE|STRFTIME|STRPTIME)\b", proj_upper))
            has_date_col = bool(re.search(r"\b(ngay|date|time|thang)\b", proj, re.IGNORECASE)) or bool(
                _MINMAX_DATE.search(proj)
            )
            has_numeric_agg = bool(re.search(r"\b(COUNT|SUM|AVG)\s*\(", proj_upper))
            if (has_date_fn or has_date_col) and not has_numeric_agg:
                return "date"

        # C. Cột chiếu tên thực thể (khách hàng, sản phẩm, mã) với LIMIT 1 và không có phép tính số -> BẮT BUỘC là 'string'
        if not is_multi_col and _outer_limit(sql) == 1:
            if re.search(r"(ten_|khach_|san_pham|mat_hang|ma_|dia_chi|name|customer)", proj, re.IGNORECASE):
                if not re.search(r"\b(COUNT|SUM|AVG|ROUND)\s*\(", proj_upper):
                    return "string"

    # 2. Auto-correction dựa trên câu hỏi tự nhiên:
    if question:
        q_norm = question.lower()
        percent_cues = ["%", "phần trăm", "phan tram", "tỉ lệ", "ti le", "tỷ lệ", "tỉ trọng", "ty trong"]
        if any(c in q_norm for c in percent_cues):
            if ans in ("number", "numeric", "decimal", "float", None):
                # Chỉ đổi sang percent khi SQL thực sự tính tỷ lệ (hoặc không có SQL để đối chiếu)
                if not sql or _looks_like_ratio(_extract_projection(sql)):
                    return "percent"

    if ans is not None:
        return ans
    return infer_answer_type_from_sql(sql) if sql else "table"


def clean_markdown_block(text: str) -> str:
    """Bóc tách nội dung bên trong block markdown ```...``` nếu có."""
    text = text.strip()
    match = re.search(r"```(?:json|sql)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


def _try_load_json(s: str) -> dict[str, Any] | None:
    """Thử parse chuỗi JSON với strict=False (cho phép xuống dòng trong SQL) và sửa trailing comma."""
    s = s.strip()
    first_brace = s.find("{")
    last_brace = s.rfind("}")
    if first_brace == -1 or last_brace == -1 or last_brace < first_brace:
        return None
    candidate = s[first_brace : last_brace + 1].strip()
    for text_to_try in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
        try:
            # strict=False là BẮT BUỘC để cho phép các ký tự điều khiển/xuống dòng thực tế trong chuỗi SQL
            obj = json.loads(text_to_try, strict=False)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


def _try_recover_truncated_json(s: str) -> dict[str, Any] | None:
    """Cứu vãn khối JSON nếu bị cắt cụt ở cuối do chạm trần token."""
    s = s.strip()
    first_brace = s.find("{")
    if first_brace == -1:
        return None
    candidate = s[first_brace:]

    status_m = re.search(r"\"status\"\s*:\s*\"(answerable|unanswerable)\"", candidate, re.IGNORECASE)
    if not status_m:
        return None
    status = status_m.group(1).lower()

    if status == "unanswerable":
        reason_m = re.search(r"\"reason\"\s*:\s*\"([^\"]+)", candidate)
        reason = reason_m.group(1) if reason_m else "Dữ liệu không đủ để trả lời."
        return {"status": "unanswerable", "reason": reason}

    sql_m = re.search(r'\"sql\"\s*:\s*(?:\"((?:[^"\\]|\\.)*)(?:\"|\Z)|```(?:sql)?\s*([\s\S]*?)(?:```|\Z))', candidate, re.IGNORECASE)
    if not sql_m:
        # Fallback tìm "sql": "..." dạng non-greedy
        sql_m = re.search(r"\"sql\"\s*:\s*\"([\s\S]*?)(?:\"|\Z)", candidate)
        if not sql_m:
            return None
        sql = sql_m.group(1).strip()
    else:
        sql = (sql_m.group(1) or sql_m.group(2) or "").strip()
    if not sql:
        return None
    sql = sql.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')

    type_m = re.search(r"\"answer_type\"\s*:\s*\"([a-zA-Z_]+)\"", candidate)
    ans_type = type_m.group(1).lower() if type_m else None

    tables_m = re.search(r"\"tables_used\"\s*:\s*\[(.*?)\]", candidate, re.DOTALL)
    tables = []
    if tables_m:
        tables = re.findall(r"\"([a-zA-Z0-9_]+)\"", tables_m.group(1))

    return {
        "status": "answerable",
        "answer_type": ans_type,
        "sql": sql,
        "tables_used": tables,
    }


def extract_json_contract_dict(text: str) -> dict[str, Any] | None:
    """
    Trích xuất từ điển JSON hợp lệ tuân thủ contract Text2SQL (có status, sql, hoặc missing_fields).
    Ưu tiên quét từ block code markdown cuối cùng lùi về trước, sau đó quét các cặp ngoặc {...}.
    """
    # 1. Tìm trong các block markdown code fences (duyệt từ block CUỐI CÙNG ngược về đầu)
    blocks = re.findall(r"```(?:json|sql)?\s*([\s\S]*?)(?:```|$)", text, re.IGNORECASE)
    for b in reversed(blocks):
        obj = _try_load_json(b)
        if obj and ("status" in obj or "sql" in obj or "missing_fields" in obj):
            return obj

    # 2. Quét các vị trí '{' từ cuối ngược lên đầu bằng raw_decode (tuyến tính theo số vị trí,
    #    không thử mọi cặp {..}); giới hạn số vị trí để tránh chi phí bậc hai trên output dài.
    decoder = json.JSONDecoder(strict=False)
    brace_starts = [m.start() for m in re.finditer(r"\{", text)][-_MAX_BRACE_STARTS:]
    for start in reversed(brace_starts):
        tail = text[start:]
        for source in (tail, re.sub(r",\s*([}\]])", r"\1", tail)):
            try:
                obj, _ = decoder.raw_decode(source)
            except ValueError:
                continue
            if isinstance(obj, dict) and ("status" in obj or "sql" in obj or "missing_fields" in obj):
                return obj

    # 3. Fallback cứu vãn nếu JSON bị cắt cụt do chạm trần token
    recovered = _try_recover_truncated_json(text)
    if recovered:
        return recovered

    return None


def parse_text2sql_response(raw_text: str, question: str | None = None) -> Text2SQLResult:
    """
    Parse chuỗi phản hồi của LLM thành đối tượng Text2SQLResult chuẩn mực.
    Xử lý linh hoạt cả trường hợp thinking model, markdown code block kép, JSON chuẩn,
    hoặc trường hợp fallback khi model chỉ trả về câu lệnh SQL thô.
    """
    if not raw_text or not raw_text.strip():
        raise Text2SQLParseError("Phản hồi từ LLM hoàn toàn rỗng.")

    has_think_tags = "<think>" in raw_text or "</think>" in raw_text
    if "<think>" in raw_text and "</think>" not in raw_text:
        raise Text2SQLParseError(
            "Phản hồi bị cắt cụt trong khối <think> (chưa có đáp án cuối): " + raw_text[:300]
        )

    thinking = extract_think_blocks(raw_text)
    visible_text = strip_think_blocks(raw_text)

    # 1. Thử giải mã JSON contract dictionary
    data: dict[str, Any] | None = None
    if visible_text:
        data = extract_json_contract_dict(visible_text)
    if data is None and not has_think_tags:
        # Có thẻ think thì raw_text chứa JSON nháp trong suy nghĩ -> không được dùng làm đáp án.
        data = extract_json_contract_dict(raw_text)

    if isinstance(data, dict):
        status = str(data.get("status", "answerable")).lower()
        if status == "needs_more_context":
            return Text2SQLResult(
                status="needs_more_context",
                answer_type=None,
                sql=None,
                tables_used=(),
                assumptions=tuple(data.get("assumptions") or ()),
                reason=data.get("reason") or "Planner yêu cầu bổ sung ngữ cảnh.",
                requested_context=tuple(str(item) for item in data.get("requested_context") or ()),
                structured_plan=data.get("structured_plan") if isinstance(data.get("structured_plan"), dict) else None,
                thinking=thinking,
                raw_response=raw_text,
            )
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
                missing_fields=tuple(str(f) for f in data.get("missing_fields") or ()),
                structured_plan=data.get("structured_plan") if isinstance(data.get("structured_plan"), dict) else None,
                thinking=thinking,
                raw_response=raw_text,
            )

        sql = data.get("sql")
        if isinstance(sql, str):
            sql = clean_markdown_block(sql).strip()
            # Xóa dấu chấm phẩy ở cuối nếu có
            sql = re.sub(r";+\s*$", "", sql)

        tables = data.get("tables_used") or ()
        if not tables and sql:
            tables = extract_tables_from_sql(sql)

        answer_type = normalize_answer_type(data.get("answer_type"), sql, question=question)
        semantics = data.get("answer_semantics")

        return Text2SQLResult(
            status="answerable",
            answer_type=answer_type,
            sql=sql,
            tables_used=tuple(tables),
            assumptions=tuple(data.get("assumptions") or ()),
            reason=None,
            answer_semantics=dict(semantics) if isinstance(semantics, dict) else None,
            structured_plan=data.get("structured_plan") if isinstance(data.get("structured_plan"), dict) else None,
            thinking=thinking,
            raw_response=raw_text,
        )

    # 2. Fallback: Nếu model sinh trực tiếp câu SQL hoặc bọc trong markdown block ```sql ... ```
    # Chỉ tìm kiếm trong visible_text nếu có thinking. Nếu mô hình đang dở dang trong thinking (visible_text rỗng)
    # thì TUYỆT ĐỐI không quét raw_text để tránh nhầm các câu đàm thoại tiếng Anh thành SQL gây EXECUTOR_FAILURE!
    search_text = visible_text if (thinking and visible_text is not None) else (visible_text or raw_text)

    # 2a. Thử tìm khối ```sql ... ```
    sql_block_m = re.search(r"```sql\s*([\s\S]*?)(?:```|$)", search_text, re.IGNORECASE)
    if sql_block_m:
        sql_candidate = sql_block_m.group(1).strip()
    else:
        # 2b. Thử tìm khối code markdown bất kỳ hoặc clean markdown
        cleaned_candidate = clean_markdown_block(search_text).strip()
        sql_candidate = cleaned_candidate

    if re.search(r"^\s*(?:SELECT|WITH)\b", sql_candidate, re.IGNORECASE):
        sql_clean = re.sub(r";+\s*$", "", sql_candidate)
        try:
            parsed_node = sqlglot.parse_one(sql_clean, read="duckdb")
            valid_sql = parsed_node is not None and parsed_node.key in ("select", "with")
        except Exception:
            valid_sql = False

        if valid_sql:
            tables = extract_tables_from_sql(sql_clean)
            ans_type = infer_answer_type_from_sql(sql_clean)
            if question:
                ans_type = normalize_answer_type(ans_type, sql_clean, question=question)
            return Text2SQLResult(
                status="answerable",
                answer_type=ans_type,
                sql=sql_clean,
                tables_used=tables,
                assumptions=(),
                reason=None,
                thinking=thinking,
                raw_response=raw_text,
            )

    # 2c. Tìm câu lệnh SELECT ... FROM ... ở bất cứ đâu trong visible_text (kể cả khi bị kẹt sau reasoning)
    any_select_m = re.search(r"\b((?:WITH\s+[a-zA-Z0-9_]+\s+AS\s*\([\s\S]+?\)\s*)?SELECT\s+[\s\S]+?\bFROM\s+[\s\S]+?)(?:;|\n\n```|\n\n\{|\Z)", search_text, re.IGNORECASE)
    if any_select_m:
        potential_sql = any_select_m.group(1).strip()
        if len(potential_sql) > 15 and not potential_sql.endswith("..."):
            sql_clean = re.sub(r";+\s*$", "", potential_sql)
            try:
                parsed_node = sqlglot.parse_one(sql_clean, read="duckdb")
                valid_sql = parsed_node is not None and parsed_node.key in ("select", "with")
            except Exception:
                valid_sql = False

            if valid_sql:
                tables = extract_tables_from_sql(sql_clean)
                if tables:
                    ans_type = infer_answer_type_from_sql(sql_clean)
                    if question:
                        ans_type = normalize_answer_type(ans_type, sql_clean, question=question)
                    return Text2SQLResult(
                        status="answerable",
                        answer_type=ans_type,
                        sql=sql_clean,
                        tables_used=tables,
                        assumptions=(),
                        reason=None,
                        thinking=thinking,
                        raw_response=raw_text,
                    )

    # 2d. Fallback tìm block ```sql ... ``` trong raw_text (chỉ khi KHÔNG có thẻ think,
    #     tránh lấy SQL nháp nằm trong phần suy nghĩ)
    if "```sql" in raw_text and not has_think_tags:
        sql_block_raw = re.search(r"```sql\s*([\s\S]*?)(?:```|$)", raw_text, re.IGNORECASE)
        if sql_block_raw:
            cand = sql_block_raw.group(1).strip()
            cand_clean = re.sub(r";+\s*$", "", cand)
            try:
                node = sqlglot.parse_one(cand_clean, read="duckdb")
                if node is not None and node.key in ("select", "with"):
                    tables = extract_tables_from_sql(cand_clean)
                    ans_type = infer_answer_type_from_sql(cand_clean)
                    if question:
                        ans_type = normalize_answer_type(ans_type, cand_clean, question=question)
                    return Text2SQLResult(
                        status="answerable",
                        answer_type=ans_type,
                        sql=cand_clean,
                        tables_used=tables,
                        assumptions=(),
                        reason=None,
                        thinking=thinking,
                        raw_response=raw_text,
                    )
            except Exception:
                pass

    # 3. Fallback: Nếu model trả lời bằng câu văn từ chối rõ ràng bằng tiếng Việt
    # Lưu ý: Tuyệt đối không dùng từ khóa tiếng Anh "unanswerable" vì mô hình suy luận
    # thường tự hỏi bằng tiếng Anh ("Is this unanswerable?") dẫn đến phán đoán nhầm bị phạt -1 điểm.
    lower_text = search_text.lower()
    vietnamese_rejections = ["không thể trả lời", "không đủ dữ liệu", "thiếu cột", "thiếu bảng", "cơ sở dữ liệu thiếu"]
    if any(cue in lower_text for cue in vietnamese_rejections):
        return Text2SQLResult(
            status="unanswerable",
            answer_type=None,
            sql=None,
            tables_used=(),
            assumptions=(),
            reason=search_text[:500],
            thinking=thinking,
            raw_response=raw_text,
        )

    # 4. Chặn hoàn toàn phán đoán mò 'unanswerable':
    # Nếu không có câu từ chối tiếng Việt rõ ràng hoặc không có SQL, ném Text2SQLParseError
    # để cổng B0.5 xử lý an toàn thành 'abstain' (0 điểm), bảo vệ điểm thi tuyệt đối.
    raise Text2SQLParseError(f"Không thể trích xuất JSON hoặc câu SQL hợp lệ từ phản hồi: {raw_text[:300]}")
