"""C2: Question-level Temporal Resolver anchored to as_of_date and business calendar."""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, timedelta

from .contracts import DateRole, ResolvedTimeRange
from .protocols import BusinessContextProtocol

_PAYMENT_KEYWORDS = (
    "thực thu",
    "thu tiền",
    "thu được bao nhiêu tiền",
    "thanh toán",
    "tiền mặt thu",
    "nộp tiền",
)
_STOCK_KEYWORDS = (
    "nhập kho",
    "xuất kho",
    "kiểm kho",
    "tồn kho",
    "nhập hàng",
)
_EXPIRY_KEYWORDS = (
    "hết hạn",
    "hạn sử dụng",
    "cận date",
)


def _last_day_of_month(year: int, month: int) -> date:
    _, last_day = calendar.monthrange(year, month)
    return date(year, month, last_day)


def _quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    return date(year, start_month, 1), _last_day_of_month(year, end_month)


def _shift_year_safe(d: date, years: int) -> date:
    target_year = d.year + years
    try:
        return d.replace(year=target_year)
    except ValueError:
        # Handle Feb 29 -> Feb 28
        return d.replace(year=target_year, day=28)


class QuestionTemporalResolver:
    """Deterministic temporal resolver translating Vietnamese time phrases into ISO date bounds."""

    def infer_date_role(
        self,
        question: str,
        preferred_date_role: DateRole | None = None,
    ) -> DateRole:
        """Determine semantic DateRole from explicit hint or question keywords."""
        if preferred_date_role is not None:
            return preferred_date_role
        q_norm = unicodedata.normalize("NFC", question).lower()
        if any(kw in q_norm for kw in _PAYMENT_KEYWORDS):
            return DateRole.PAYMENT_DATE
        if any(kw in q_norm for kw in _STOCK_KEYWORDS):
            return DateRole.STOCK_EVENT_DATE
        if any(kw in q_norm for kw in _EXPIRY_KEYWORDS):
            return DateRole.EXPIRY_DATE
        return DateRole.ORDER_DATE

    def resolve(
        self,
        question: str,
        as_of_date: str,
        context: BusinessContextProtocol | None = None,
        preferred_date_role: DateRole | None = None,
    ) -> tuple[ResolvedTimeRange, ...]:
        """Resolve temporal expressions in the question relative to as_of_date."""
        anchor = date.fromisoformat(as_of_date.strip())
        q_norm = unicodedata.normalize("NFC", question).lower()
        role = self.infer_date_role(question, preferred_date_role)

        # 1. Check Calendar / Tết events first
        if context is not None and "tết" in q_norm:
            target_year = anchor.year
            if "năm ngoái" in q_norm or "năm trước" in q_norm:
                target_year = anchor.year - 1
            else:
                year_m = re.search(r"tết\s*(?:năm\s*)?(20\d{2})", q_norm)
                if year_m:
                    target_year = int(year_m.group(1))

            for ev in context.get_calendar_events():
                if ev.year == target_year and any(alias in q_norm for alias in ev.aliases):
                    return (
                        ResolvedTimeRange(
                            raw_expression=ev.event_key,
                            start_date=ev.start_date,
                            end_date=ev.end_date,
                            date_role=role,
                            inclusive=True,
                            interpretation=f"Sự kiện lịch {ev.event_key} ({ev.start_date}..{ev.end_date})",
                        ),
                    )

        # 2. Check explicit date: dd/mm/yyyy or yyyy-mm-dd
        m_dmy = re.search(r"(?:ngày\s*)?(\d{1,2})[/-](\d{1,2})[/-](20\d{2})", q_norm)
        if m_dmy:
            day_i, month_i, year_i = int(m_dmy.group(1)), int(m_dmy.group(2)), int(m_dmy.group(3))
            explicit_d = date(year_i, month_i, day_i).isoformat()
            return (
                ResolvedTimeRange(
                    raw_expression=m_dmy.group(0),
                    start_date=explicit_d,
                    end_date=explicit_d,
                    date_role=role,
                    inclusive=True,
                    interpretation=f"Ngày cụ thể {explicit_d}",
                ),
            )

        m_iso = re.search(r"(20\d{2})-(\d{2})-(\d{2})", q_norm)
        if m_iso:
            explicit_d = date.fromisoformat(m_iso.group(0)).isoformat()
            return (
                ResolvedTimeRange(
                    raw_expression=m_iso.group(0),
                    start_date=explicit_d,
                    end_date=explicit_d,
                    date_role=role,
                    inclusive=True,
                    interpretation=f"Ngày ISO {explicit_d}",
                ),
            )

        # 3. Check explicit quarter: quý Q năm YYYY / quý Q/YYYY
        m_q_explicit = re.search(r"quý\s*([1-4])\s*(?:năm|/|-)\s*(20\d{2})", q_norm)
        if m_q_explicit:
            q_num = int(m_q_explicit.group(1))
            y_num = int(m_q_explicit.group(2))
            q_start, q_end = _quarter_bounds(y_num, q_num)
            if y_num == anchor.year and q_start <= anchor <= q_end:
                q_end = anchor
            return (
                ResolvedTimeRange(
                    raw_expression=m_q_explicit.group(0),
                    start_date=q_start.isoformat(),
                    end_date=q_end.isoformat(),
                    date_role=role,
                    inclusive=True,
                    interpretation=f"Quý {q_num}/{y_num}",
                ),
            )

        # 4. Check explicit month: tháng M/YYYY or tháng M năm YYYY
        m_month_explicit = re.search(
            r"tháng\s*(\d{1,2})\s*(?:năm|/|-)\s*(20\d{2})", q_norm
        )
        if m_month_explicit:
            m_num = int(m_month_explicit.group(1))
            y_num = int(m_month_explicit.group(2))
            if 1 <= m_num <= 12:
                m_start = date(y_num, m_num, 1)
                m_end = (
                    anchor
                    if (y_num == anchor.year and m_num == anchor.month)
                    else _last_day_of_month(y_num, m_num)
                )
                return (
                    ResolvedTimeRange(
                        raw_expression=m_month_explicit.group(0),
                        start_date=m_start.isoformat(),
                        end_date=m_end.isoformat(),
                        date_role=role,
                        inclusive=True,
                        interpretation=f"Tháng {m_num:02d}/{y_num}",
                    ),
                )

        # 5. Relative N days: "7 ngày gần đây", "30 ngày qua", "14 ngày gần nhất"
        m_ndays = re.search(r"(\d+)\s*ngày\s*(?:gần đây|qua|gần nhất|vừa qua)", q_norm)
        if m_ndays:
            n_days = max(1, int(m_ndays.group(1)))
            start_d = anchor - timedelta(days=n_days - 1)
            return (
                ResolvedTimeRange(
                    raw_expression=m_ndays.group(0),
                    start_date=start_d.isoformat(),
                    end_date=anchor.isoformat(),
                    date_role=role,
                    inclusive=True,
                    interpretation=f"{n_days} ngày tính đến as_of_date {anchor.isoformat()}",
                ),
            )

        # 6. Relative standard phrases (today, yesterday, this month, last month, this quarter, this year)
        primary_start: date | None = None
        primary_end: date | None = None
        raw_expr = ""
        interp = ""

        if "hôm nay" in q_norm or "ngày nay" in q_norm:
            primary_start = anchor
            primary_end = anchor
            raw_expr = "hôm nay"
            interp = f"Ngày as_of_date {anchor.isoformat()}"
        elif "hôm qua" in q_norm:
            yest = anchor - timedelta(days=1)
            primary_start = yest
            primary_end = yest
            raw_expr = "hôm qua"
            interp = f"Ngày hôm qua {yest.isoformat()}"
        elif "tháng này" in q_norm or "đầu tháng đến nay" in q_norm:
            primary_start = date(anchor.year, anchor.month, 1)
            primary_end = anchor
            raw_expr = "tháng này"
            interp = f"Từ đầu tháng {primary_start.isoformat()} đến as_of_date {anchor.isoformat()}"
        elif "tháng trước" in q_norm or "tháng vừa rồi" in q_norm:
            first_this = date(anchor.year, anchor.month, 1)
            last_prev = first_this - timedelta(days=1)
            first_prev = date(last_prev.year, last_prev.month, 1)
            primary_start = first_prev
            primary_end = last_prev
            raw_expr = "tháng trước"
            interp = f"Tháng trước ({first_prev.isoformat()}..{last_prev.isoformat()})"
        elif "quý này" in q_norm or "đầu quý đến nay" in q_norm:
            curr_q = (anchor.month - 1) // 3 + 1
            q_start, _ = _quarter_bounds(anchor.year, curr_q)
            primary_start = q_start
            primary_end = anchor
            raw_expr = "quý này"
            interp = f"Từ đầu quý {curr_q}/{anchor.year} đến as_of_date {anchor.isoformat()}"
        elif "quý trước" in q_norm:
            curr_q = (anchor.month - 1) // 3 + 1
            prev_q = 4 if curr_q == 1 else curr_q - 1
            prev_y = anchor.year - 1 if curr_q == 1 else anchor.year
            q_start, q_end = _quarter_bounds(prev_y, prev_q)
            primary_start = q_start
            primary_end = q_end
            raw_expr = "quý trước"
            interp = f"Quý trước Q{prev_q}/{prev_y}"
        elif "năm nay" in q_norm or "đầu năm đến nay" in q_norm:
            primary_start = date(anchor.year, 1, 1)
            primary_end = anchor
            raw_expr = "năm nay"
            interp = f"Từ đầu năm {anchor.year}-01-01 đến as_of_date {anchor.isoformat()}"
        elif ("năm ngoái" in q_norm or "năm trước" in q_norm) and "cùng kỳ" not in q_norm:
            prev_y = anchor.year - 1
            primary_start = date(prev_y, 1, 1)
            primary_end = date(prev_y, 12, 31)
            raw_expr = "năm ngoái"
            interp = f"Cả năm trước ({prev_y})"

        if primary_start is not None and primary_end is not None:
            comp_start: str | None = None
            comp_end: str | None = None

            if "cùng kỳ năm ngoái" in q_norm or "cùng kỳ năm trước" in q_norm:
                comp_start = _shift_year_safe(primary_start, -1).isoformat()
                comp_end = _shift_year_safe(primary_end, -1).isoformat()
            elif "so với tháng trước" in q_norm and raw_expr == "tháng này":
                first_this = date(anchor.year, anchor.month, 1)
                last_prev = first_this - timedelta(days=1)
                first_prev = date(last_prev.year, last_prev.month, 1)
                comp_start = first_prev.isoformat()
                comp_end = last_prev.isoformat()

            return (
                ResolvedTimeRange(
                    raw_expression=raw_expr,
                    start_date=primary_start.isoformat(),
                    end_date=primary_end.isoformat(),
                    date_role=role,
                    inclusive=True,
                    comparison_start_date=comp_start,
                    comparison_end_date=comp_end,
                    interpretation=interp,
                ),
            )

        return ()


__all__ = ["QuestionTemporalResolver"]

