"""Conservative typed parsing with explicit issues and no arithmetic defaults."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900, from_excel

from datamate.ingestion.readers import fold


def role_for(header: str, description: str = "") -> str:
    label = fold(header)
    compact = label.replace(" ", "")
    meaning = fold(description)
    if any(
        word in meaning
        for word in ("ma don", "ma hang", "ma khach", "so dien thoai", "ma phieu")
    ):
        return "identifier"
    if (
        label.startswith(("ma ", "id"))
        or compact.startswith("ma")
        or label
        in {"stt", "no", "sku", "phone", "so phieu", "so hoa don", "so ct", "so hd"}
        or any(word in label for word in ("dien thoai", "phone", "cccd"))
    ):
        return "identifier"
    if (
        "trang thai" in label
        or label
        in {"status", "ket qua", "xu ly", "tinh trang", "tinh trang don", "ghi chu tt"}
        or "trang thai don" in meaning
    ):
        return "status"
    if any(
        word in label
        for word in (
            "ngay",
            "thoi gian",
            "gio",
            "tao luc",
            "han su dung",
            "han tra",
            "han thanh toan",
            "date",
            "expiry",
        )
    ) and not any(
        word in label for word in ("so ngay", "han no ngay", "so ngay duoc no")
    ):
        return "date"
    if any(
        word in label
        for word in ("cach ", "hinh thuc", "phuong thuc", "nguoi ", "ten ", "tien te")
    ):
        return "text"
    if label in {"ke don", "thuoc ke don", "la thuoc ke don", "ban theo don"}:
        return "boolean"
    if (
        any(
            re.search(r"\b" + re.escape(word) + r"\b", label)
            for word in (
                "gia",
                "tien",
                "tri gia",
                "amount",
                "cost",
                "con no",
                "du no",
                "phai thu",
                "khach tra",
                "con lai",
                "chiet khau",
                "can tra",
            )
        )
        or "thanh tien" in meaning
    ):
        return "money"
    if (
        any(
            word in label
            for word in (
                "so luong",
                "he so",
                "ti le quy doi",
                "qty",
                "quantity",
                "ton kho",
                "ton cuoi",
                "ton thuc",
            )
        )
        or compact.startswith("sl")
        or label == "so khach"
    ):
        return "quantity"
    if any(
        word in label
        for word in (
            "khach",
            "ghi chu",
            "ten",
            "doi tac",
            "hang",
            "san pham",
            "noi dung",
            "dien giai",
            "don vi",
            "dvt",
            "unit",
            "loai",
            "nhom",
        )
    ):
        return "text"
    if "so luong" in meaning:
        return "quantity"
    return "unknown"


def descriptions(readme: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2)
        for match in re.finditer(r"^- \*\*(.+?)\*\*:\s*(.+)$", readme, re.MULTILINE)
    }


def is_order_key(header: str, description: str = "") -> bool:
    text = fold(header + " " + description)
    compact = text.replace(" ", "")
    return (
        any(
            word in text
            for word in (
                "ma don",
                "ma hoa don",
                "ma bill",
                "so hoa don",
                "ma chung tu",
                "so ct",
                "so hd",
            )
        )
        or "mahoadon" in compact
    )


def is_product(header: str, description: str = "") -> bool:
    text = fold(header + " " + description)
    return (
        "ten hang" in text
        or "ten san pham" in text
        or "ma hang" in text
        or "ma san pham" in text
        or fold(header) in {"hang", "noi dung", "mat hang", "san pham", "product"}
    )


def raw_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        # Preserve bytes without a lossy text decode; no blob data is guessed numeric.
        return "hex:" + value.hex()
    return str(value)


def parse_number(value: str, role: str) -> Decimal:
    text = value.strip().replace("\u00a0", " ").replace("−", "-")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    factor = Decimal(1)
    if role == "money":
        text = re.sub(r"(?i)\s*(vnd|vnđ|đ|₫)\s*$", "", text).strip()
        millions = re.fullmatch(r"(?i)([+-]?\d+)tr(\d{3})", text)
        if millions:
            text = millions.group(1) + "." + millions.group(2)
            factor = Decimal(1_000_000)
        elif re.search(r"(?i)(?:tr|trieu)$", text):
            factor = Decimal(1_000_000)
            text = re.sub(r"(?i)(?:tr|trieu)$", "", text).strip()
        elif re.search(r"(?i)k$", text):
            factor = Decimal(1000)
            text = text[:-1].strip()
    elif role == "quantity":
        text = re.sub(r"\s+[a-zA-ZÀ-ỹ][a-zA-ZÀ-ỹ0-9²³ .x×/]*$", "", text).strip()
    text = text.replace(" ", "")
    if "," in text and "." in text:
        decimal = "." if text.rfind(".") > text.rfind(",") else ","
        grouping = "," if decimal == "." else "."
        integer, fraction = text.rsplit(decimal, 1)
        if not fraction.isdigit() or not re.fullmatch(
            r"[+-]?\d{1,3}(?:" + re.escape(grouping) + r"\d{3})+", integer
        ):
            raise ValueError("ambiguous mixed numeric separators")
        text = integer.replace(grouping, "") + "." + fraction
    elif "," in text or "." in text:
        separator = "," if "," in text else "."
        parts = text.lstrip("+-").split(separator)
        # Exact thousands groups are interpreted as grouping only in declared numeric roles.
        if (
            factor == 1
            and len(parts) >= 2
            and all(len(part) == 3 and part.isdigit() for part in parts[1:])
            and 1 <= len(parts[0]) <= 3
        ):
            text = text.replace(separator, "")
        elif len(parts) == 2 and all(part.isdigit() for part in parts):
            text = text.replace(separator, ".")
        else:
            raise ValueError("ambiguous numeric separators")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        raise ValueError("not a numeric value")
    try:
        with localcontext() as context:
            context.prec = max(50, len(text) + 10)
            result = Decimal(text) * factor
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    if not result.is_finite():
        raise ValueError("non-finite decimal")
    return -result if negative else result


def parse_date(value: str, epoch: str, year: int | None) -> date | datetime | time:
    text = value.strip()
    try:
        if (
            "T" in text
            or re.search(r"\d{1,2}:\d{2}", text)
            and ("-" in text or "/" in text)
        ):
            return datetime.fromisoformat(text)
        return date.fromisoformat(text)
    except ValueError:
        pass
    for fmt in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    if ":" in text:
        try:
            return time.fromisoformat(text)
        except ValueError:
            pass
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    text = re.sub(r"(?i)^(\d{1,2})\s*thg\s*(\d{1,2})\s+(\d{4})$", r"\1/\2/\3", text)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if year is not None and re.fullmatch(r"\d{1,2}[/.-]\d{1,2}", text):
        day, month = re.split(r"[/.-]", text)
        return date(year, int(month), int(day))
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        serial = float(text)
        if math.isfinite(serial) and (0 <= serial < 1 or 20000 <= serial <= 110000):
            result = from_excel(
                serial, CALENDAR_MAC_1904 if epoch == "1904" else CALENDAR_WINDOWS_1900
            )
            if isinstance(result, datetime) and result.time() == time.min:
                return result.date()
            return result
    raise ValueError("unsupported or ambiguous date; no host-clock year inferred")


_STATUS = {
    "thanh cong": "completed",
    "da giao": "completed",
    "khach huy": "cancelled",
    "cancel": "cancelled",
    "da hoan hang": "returned",
    "tra lai": "returned",
    "shipping": "delivering",
    "dang van chuyen": "delivering",
    "dang gui": "delivering",
    "completed": "completed",
    "hoan thanh": "completed",
    "da hoan thanh": "completed",
    "xong": "completed",
    "da xong": "completed",
    "da lay": "completed",
    "ok": "completed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "huy": "cancelled",
    "huy don": "cancelled",
    "da huy": "cancelled",
    "da huy don": "cancelled",
    "returned": "returned",
    "tra hang": "returned",
    "da tra hang": "returned",
    "hoan tra": "returned",
    "doi tra": "returned",
    "hang tra ve": "returned",
    "delivering": "delivering",
    "dang giao": "delivering",
    "dang giao hang": "delivering",
}


class ColumnParser:
    """A role-aware parser and exact type accumulator for one logical column."""

    def __init__(self, role: str) -> None:
        if role not in {
            "identifier",
            "status",
            "date",
            "boolean",
            "money",
            "quantity",
            "text",
            "unknown",
        }:
            raise ValueError(f"unsupported column role: {role}")
        self.role = role
        self.scale = 0
        self.integer_digits = 1
        self.kinds: set[str] = set()

    def parse(
        self, value: str | None, epoch: str, year: int | None
    ) -> tuple[str | None, str | None]:
        if value is None or value.strip() == "":
            return None, None
        if self.role in {"identifier", "text"}:
            return value, None
        if self.role == "status":
            mapped = _STATUS.get(fold(value))
            return (mapped, None) if mapped else (value, "unmapped_status")
        try:
            if self.role in {"money", "quantity"}:
                result = parse_number(value, self.role)
                self.scale = max(self.scale, max(0, -result.as_tuple().exponent))
                self.integer_digits = max(
                    self.integer_digits, max(1, result.adjusted() + 1)
                )
                return format(result, "f"), None
            if self.role == "date":
                result = parse_date(value, epoch, year)
                kind = (
                    "TIMESTAMP"
                    if isinstance(result, datetime)
                    else "TIME"
                    if isinstance(result, time)
                    else "DATE"
                )
                self.kinds.add(kind)
                return result.isoformat(), None
            if self.role == "boolean":
                normalized = fold(value)
                if normalized not in {
                    "true",
                    "false",
                    "1",
                    "0",
                    "yes",
                    "no",
                    "co",
                    "khong",
                }:
                    raise ValueError("unknown boolean")
                return "true" if normalized in {
                    "true",
                    "1",
                    "yes",
                    "co",
                } else "false", None
            # Unknown fields stay text, including identifiers with leading zeroes.
            return value, None
        except ValueError:
            return None, "parse_failure"

    def sql_type(self) -> str:
        if self.role in {"money", "quantity"}:
            return (
                f"DECIMAL(38,{self.scale})"
                if self.scale <= 38 and self.integer_digits + self.scale <= 38
                else "VARCHAR"
            )
        if self.role == "date":
            if len(self.kinds) > 1 and "TIME" in self.kinds:
                return "VARCHAR"
            return (
                "TIMESTAMP"
                if "TIMESTAMP" in self.kinds
                else "TIME"
                if "TIME" in self.kinds
                else "DATE"
            )
        if self.role == "boolean":
            return "BOOLEAN"
        return "VARCHAR"
