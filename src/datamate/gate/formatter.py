"""Typed Output Formatter for B0.5 Basic Output Gate (DataMate 2026)."""

import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import re
from typing import Any, Dict, List, Optional
import unicodedata

from .contracts import AnswerType, NumericKind, PercentUnit
from .errors import ErrorCode, FormattingError


def normalize_match_key(value: str) -> str:
    """Normalize string for internal comparison/evaluation matching.
    
    NFC -> lowercase -> non-alphanumeric to space -> collapse spaces -> strip.
    NOTE: Never use this to alter submission output string.
    """
    if not isinstance(value, str):
        value = str(value)
    s = unicodedata.normalize("NFC", value).lower()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def _to_decimal(value: Any) -> Decimal:
    """Convert input to Decimal safely, rejecting bool, None, NaN, Inf."""
    if isinstance(value, bool):
        raise FormattingError("Boolean cannot be converted to number/decimal", code=ErrorCode.OUTPUT_TYPE_ERROR)
    if value is None:
        raise FormattingError("Null value cannot be converted to number/decimal", code=ErrorCode.NULL_RESULT)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise FormattingError("NaN/Inf cannot be converted to number/decimal", code=ErrorCode.OUTPUT_TYPE_ERROR)
    try:
        d = Decimal(str(value))
        if not d.is_finite():
            raise FormattingError("Non-finite decimal encountered", code=ErrorCode.OUTPUT_TYPE_ERROR)
        return d
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise FormattingError(f"Cannot parse decimal from {value}: {exc}", code=ErrorCode.OUTPUT_TYPE_ERROR)


def format_number(value: Any, semantics: Dict[str, Any]) -> int | float:
    """Format numeric values according to specific numeric_kind."""
    d = _to_decimal(value)
    numeric_kind = semantics.get("numeric_kind")

    if numeric_kind == NumericKind.COUNT:
        if d % Decimal("1") != Decimal("0"):
            raise FormattingError(f"Count must be an exact integer, got decimal: {value}", code=ErrorCode.OUTPUT_TYPE_ERROR)
        return int(d)

    elif numeric_kind in (NumericKind.MONEY_VND, NumericKind.AVERAGE_MONEY_VND):
        rounded = d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return int(rounded)

    elif numeric_kind == NumericKind.AVERAGE_NONMONEY:
        rounded = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return float(rounded)

    elif numeric_kind == NumericKind.QUANTITY:
        if d % Decimal("1") == Decimal("0"):
            return int(d)
        rounded = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return float(rounded)

    else:
        # generic / default
        if d % Decimal("1") == Decimal("0"):
            return int(d)
        rounded = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return float(rounded)


def format_percent(value: Any, semantics: Dict[str, Any]) -> int | float:
    """Format percent to percentage points rounded to 2 decimal places with HALF_UP."""
    d = _to_decimal(value)
    percent_unit = semantics.get("percent_unit")

    if percent_unit == PercentUnit.FRACTION:
        d = d * Decimal("100")

    rounded = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Avoid -0.0 in JSON
    if rounded == Decimal("0.00"):
        return 0

    if rounded % Decimal("1") == Decimal("0"):
        return int(rounded)
    return float(rounded)


def format_string(value: Any) -> str:
    """Format string: NFC, trimmed, preserving casing and Vietnamese diacritics."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()[:10]
    if not isinstance(value, str):
        raise FormattingError(f"Expected string, got {type(value).__name__}", code=ErrorCode.OUTPUT_TYPE_ERROR)
    s = unicodedata.normalize("NFC", value).strip()
    if not s:
        raise FormattingError("Empty string result is invalid for answer_type=string", code=ErrorCode.EMPTY_RESULT)
    return s


def format_date(value: Any, semantics: Dict[str, Any]) -> str:
    """Format date to ISO YYYY-MM-DD or YYYY-MM."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()[:10]

    s = str(value).strip()
    # ISO timestamps produced by the executor (B0.4): keep only the calendar date.
    if re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d", s):
        try:
            return datetime.datetime.fromisoformat(s).date().isoformat()
        except ValueError as exc:
            raise FormattingError(f"Invalid timestamp '{s}': {exc}", code=ErrorCode.OUTPUT_TYPE_ERROR)

    # Check YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            parsed = datetime.date.fromisoformat(s)
            return parsed.isoformat()
        except ValueError as exc:
            raise FormattingError(f"Invalid calendar date '{s}': {exc}", code=ErrorCode.OUTPUT_TYPE_ERROR)

    # Check YYYY-MM
    if re.match(r"^\d{4}-\d{2}$", s):
        year, month = map(int, s.split("-"))
        if 1 <= month <= 12:
            return s
        raise FormattingError(f"Invalid month in date '{s}'", code=ErrorCode.OUTPUT_TYPE_ERROR)

    raise FormattingError(f"Invalid date format '{s}', expected ISO YYYY-MM-DD or YYYY-MM", code=ErrorCode.OUTPUT_TYPE_ERROR)


def format_boolean(value: Any) -> bool:
    """Format boolean: strictly bool True or False."""
    if not isinstance(value, bool):
        raise FormattingError(f"Expected boolean True/False, got {type(value).__name__}: {value}", code=ErrorCode.OUTPUT_TYPE_ERROR)
    return value


def _json_scalar(item: Any) -> Any:
    """Convert Decimal/date/time cells to JSON-safe primitives."""
    if isinstance(item, bool):
        return item
    if isinstance(item, Decimal):
        if not item.is_finite():
            raise FormattingError("Non-finite decimal element", code=ErrorCode.OUTPUT_TYPE_ERROR)
        return int(item) if item % 1 == 0 else float(item)
    if isinstance(item, (datetime.datetime, datetime.date, datetime.time)):
        return item.isoformat()
    if isinstance(item, str):
        return unicodedata.normalize("NFC", item).strip()
    return item


def format_list(value: Any, semantics: Dict[str, Any]) -> List[Any]:
    """Format list: ordered, preserving query order, validating elements."""
    if not isinstance(value, (list, tuple)):
        raise FormattingError(f"Expected list/tuple, got {type(value).__name__}", code=ErrorCode.OUTPUT_TYPE_ERROR)

    res = list(value)
    if len(res) == 0:
        if semantics.get("empty_set_policy") == "allowed":
            return []
        raise FormattingError("Empty list returned without explicit empty_set_policy=allowed", code=ErrorCode.EMPTY_RESULT)

    # Clean/validate items
    formatted_items = []
    for item in res:
        if item is None:
            raise FormattingError("List contains null element", code=ErrorCode.NULL_RESULT)
        if isinstance(item, float) and (math.isnan(item) or math.isinf(item)):
            raise FormattingError("List contains NaN/Inf element", code=ErrorCode.OUTPUT_TYPE_ERROR)
        formatted_items.append(_json_scalar(item))
    return formatted_items


def format_table(value: Any, semantics: Dict[str, Any]) -> Dict[str, Any]:
    """Format table: columns and rows matching dimensions, no NaN/Inf."""
    if not isinstance(value, dict):
        raise FormattingError(f"Table must be dict with 'columns' and 'rows', got {type(value).__name__}", code=ErrorCode.TABLE_SHAPE_ERROR)

    columns = value.get("columns")
    rows = value.get("rows")

    if not isinstance(columns, list) or not all(isinstance(c, str) and c.strip() for c in columns):
        raise FormattingError("Table columns must be a non-empty list of non-empty strings", code=ErrorCode.TABLE_SHAPE_ERROR)

    if not isinstance(rows, list):
        raise FormattingError("Table rows must be a list of rows", code=ErrorCode.TABLE_SHAPE_ERROR)

    num_cols = len(columns)
    if len(rows) == 0:
        if semantics.get("empty_set_policy") == "allowed":
            return {"columns": columns, "rows": []}
        raise FormattingError("Empty table rows without empty_set_policy=allowed", code=ErrorCode.EMPTY_RESULT)

    clean_rows = []
    for r_idx, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != num_cols:
            raise FormattingError(f"Table row {r_idx} width {len(row) if isinstance(row, list) else 0} != columns count {num_cols}", code=ErrorCode.TABLE_SHAPE_ERROR)

        clean_row = []
        for cell in row:
            if cell is None:
                raise FormattingError(f"Table row {r_idx} contains NULL cell", code=ErrorCode.NULL_RESULT)
            if isinstance(cell, float) and (math.isnan(cell) or math.isinf(cell)):
                raise FormattingError(f"Table row {r_idx} contains NaN/Inf cell", code=ErrorCode.OUTPUT_TYPE_ERROR)
            clean_row.append(_json_scalar(cell))
        clean_rows.append(clean_row)

    return {"columns": columns, "rows": clean_rows}


def format_answer(answer_type: str, value: Any, semantics: Optional[Dict[str, Any]] = None) -> Any:
    """Format raw candidate value according to one of the 9 official answer types.
    
    Raises FormattingError if value cannot be safely and unambiguously formatted.
    """
    if semantics is None:
        semantics = {}

    if answer_type == AnswerType.NUMBER:
        return format_number(value, semantics)
    elif answer_type == AnswerType.PERCENT:
        return format_percent(value, semantics)
    elif answer_type == AnswerType.STRING:
        return format_string(value)
    elif answer_type == AnswerType.DATE:
        return format_date(value, semantics)
    elif answer_type == AnswerType.BOOLEAN:
        return format_boolean(value)
    elif answer_type == AnswerType.LIST:
        return format_list(value, semantics)
    elif answer_type == AnswerType.TABLE:
        return format_table(value, semantics)
    elif answer_type == AnswerType.UNANSWERABLE:
        return None
    elif answer_type == AnswerType.ABSTAIN:
        return None
    else:
        raise FormattingError(f"Unknown answer_type '{answer_type}'", code=ErrorCode.CONTRACT_ERROR)

