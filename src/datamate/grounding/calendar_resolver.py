"""Resolve structured Gregorian/Vietnamese lunar expressions against an immutable calendar."""
from __future__ import annotations

import calendar
import csv
import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class LunarEndpoint(BaseModel):
    model_config = ConfigDict(extra='forbid')
    year: int
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=30)
    leap: Literal['regular', 'leap', 'unspecified'] = 'unspecified'

class TemporalSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    raw_expression: str
    calendar: Literal['gregorian', 'vietnamese_lunar'] = 'gregorian'
    kind: Literal['date', 'month', 'quarter', 'year', 'tet', 'range', 'recent_days', 'week', 'snapshot', 'recurring_day']
    year: int | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    quarter: int | None = Field(default=None, ge=1, le=4)
    day: int | None = Field(default=None, ge=1, le=31)
    leap: Literal['regular', 'leap', 'unspecified'] = 'unspecified'
    relative: Literal['this', 'previous'] | None = None
    period_extent: Literal['full_period', 'to_as_of', 'snapshot', 'unknown'] | None = None
    role: Literal['primary', 'comparison', 'series'] = 'primary'
    count: int | None = Field(default=None, ge=1, le=3660)
    start: date | None = None
    end: date | None = None
    lunar_start: LunarEndpoint | None = None
    lunar_end_inclusive: LunarEndpoint | None = None
    comparison: Literal['previous_equal_days', 'previous_year', 'previous_month_matched', 'unknown'] | None = None
    comparison_days: int | None = Field(default=None, ge=1, le=3660)
    column: str
    applies_to: list[str] = Field(default_factory=list)
    date_role: str = 'order_date'


class CalendarResolutionError(ValueError):
    pass


class CalendarResolver:
    def __init__(self, path: str | Path):
        path = Path(path)
        self.fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        self.rows = []
        self.by_date = {}
        self.by_lunar = {}
        with path.open(encoding='utf-8', newline='') as stream:
            for raw in csv.DictReader(stream):
                d = date.fromisoformat(raw['date'])
                if raw['lunar_leap'].lower() not in ('true', 'false'):
                    raise ValueError('invalid lunar_leap')
                key = (int(raw['lunar_year']), int(raw['lunar_month']), int(raw['lunar_day']), raw['lunar_leap'].lower() == 'true')
                if d in self.by_date or key in self.by_lunar:
                    raise ValueError('duplicate calendar mapping')
                if not 1 <= key[1] <= 12 or not 1 <= key[2] <= 30:
                    raise ValueError('invalid lunar fields')
                self.rows.append((d, key))
                self.by_date[d] = key
                self.by_lunar[key] = d
        self.rows.sort()
        if not self.rows or any(b[0] - a[0] != timedelta(days=1) for a, b in zip(self.rows, self.rows[1:])):
            raise ValueError('calendar must be nonempty and continuous')

    def lunar_date(self, year, month, day, leap='unspecified'):
        matches = [d for (y, m, n, flag), d in self.by_lunar.items()
                   if (y, m, n) == (year, month, day) and (leap == 'unspecified' or flag == (leap == 'leap'))]
        if len(matches) > 1:
            raise CalendarResolutionError('ambiguous_lunar_date')
        if not matches:
            years = {k[0] for k in self.by_lunar}
            raise CalendarResolutionError('calendar_out_of_range' if year not in years else 'invalid_or_uncovered_lunar_date')
        return matches[0]

    def _period(self, year, month=None, leap='unspecified'):
        selected = [(d, k) for d, k in self.rows if k[0] == year and (month is None or k[1] == month)
                    and (month is None or leap == 'unspecified' or k[3] == (leap == 'leap'))]
        if not selected:
            raise CalendarResolutionError('calendar_out_of_range')
        if month is not None and len({k[3] for _, k in selected}) > 1:
            raise CalendarResolutionError('ambiguous_lunar_month')
        start, end = selected[0][0], selected[-1][0] + timedelta(days=1)
        if selected[0][1][2] != 1 or (month is None and selected[0][1][1] != 1) or end not in self.by_date or self.by_date[end][2] != 1:
            raise CalendarResolutionError('incomplete_calendar_period')
        if month is None and self.by_date[end][0] != year + 1:
            raise CalendarResolutionError('incomplete_calendar_period')
        return start, end

    def resolve(self, spec: TemporalSpec, as_of: str):
        anchor = date.fromisoformat(as_of)
        if spec.comparison == 'unknown':
            raise CalendarResolutionError('comparison_relation_unresolved')
        if spec.period_extent == 'unknown':
            raise CalendarResolutionError('period_extent_unresolved')
        if spec.period_extent == 'snapshot' and spec.kind != 'snapshot':
            raise CalendarResolutionError('snapshot_extent_requires_snapshot_kind')
        if spec.kind == 'snapshot' and spec.period_extent not in (None, 'snapshot'):
            raise CalendarResolutionError('snapshot_requires_snapshot_extent')
        if spec.period_extent == 'full_period' and spec.relative == 'this':
            raise CalendarResolutionError('full_period_conflicts_with_this_period_policy')
        lunar = spec.calendar == 'vietnamese_lunar' or spec.kind == 'tet'
        key = self.by_date.get(anchor)
        if lunar and spec.year is None and key is None:
            raise CalendarResolutionError('calendar_out_of_range')
        year = spec.year if spec.year is not None else (key[0] if lunar else anchor.year)
        month = spec.month
        leap = spec.leap
        if spec.relative and spec.kind in ('month', 'year'):
            year = key[0] if lunar else anchor.year
            month = (key[1] if lunar else anchor.month) if spec.kind == 'month' else None
            if lunar and spec.kind == 'month':
                leap = 'leap' if key[3] else 'regular'
            if spec.relative == 'previous':
                if spec.kind == 'year':
                    year -= 1
                elif lunar:
                    first = self._period(year, month, leap)[0]
                    prev = self.by_date.get(first - timedelta(days=1))
                    if prev is None:
                        raise CalendarResolutionError('calendar_out_of_range')
                    year, month, _, flag = prev
                    leap = 'leap' if flag else 'regular'
                else:
                    year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        if spec.kind in ('snapshot', 'recurring_day') and spec.comparison:
            raise CalendarResolutionError('comparison_not_supported_for_this_kind')
        if spec.kind == 'tet':
            start = self.lunar_date(year - 1, 12, 23, 'regular')
            end = self.lunar_date(year, 1, 10, 'regular') + timedelta(days=1)
        elif spec.kind == 'date':
            start = self.lunar_date(year, month, spec.day, leap) if lunar else date(year, month, spec.day)
            end = start + timedelta(days=1)
        elif spec.kind == 'quarter':
            if lunar or spec.quarter is None:
                raise CalendarResolutionError('quarter_requires_gregorian_quarter_number')
            start = date(year, 3 * (spec.quarter - 1) + 1, 1)
            end = date(year + 1, 1, 1) if spec.quarter == 4 else date(year, 3 * spec.quarter + 1, 1)
        elif spec.kind in ('month', 'year'):
            if lunar:
                start, end = self._period(year, month if spec.kind == 'month' else None, leap)
            elif spec.kind == 'year':
                start, end = date(year, 1, 1), date(year + 1, 1, 1)
            else:
                start = date(year, month, 1)
                end = start + timedelta(days=calendar.monthrange(year, month)[1])
            if spec.relative == 'this' and spec.period_extent is None:
                end = anchor + timedelta(days=1)
        elif spec.kind == 'recent_days':
            if spec.count is None:
                raise CalendarResolutionError('missing_day_count')
            start, end = anchor - timedelta(days=spec.count - 1), anchor + timedelta(days=1)
        elif spec.kind == 'week':
            start = anchor - timedelta(days=anchor.weekday())
            end = start + timedelta(days=7) if spec.period_extent == 'full_period' else anchor + timedelta(days=1)
            if spec.relative == 'previous':
                end, start = start, start - timedelta(days=7)
        elif spec.kind == 'snapshot':
            return [{'mode': 'snapshot', 'as_of_exclusive': ((spec.end or anchor) + timedelta(days=1)).isoformat(), 'history_start': 'unbounded'}]
        elif spec.kind == 'range':
            if lunar:
                if not spec.lunar_start or not spec.lunar_end_inclusive:
                    raise CalendarResolutionError('lunar_range_requires_endpoints')
                start = self.lunar_date(**spec.lunar_start.model_dump())
                end = self.lunar_date(**spec.lunar_end_inclusive.model_dump()) + timedelta(days=1)
            else:
                start, end = spec.start, spec.end
        elif spec.kind == 'recurring_day':
            if not lunar or not spec.start or not spec.end or not spec.day:
                raise CalendarResolutionError('recurrence_requires_lunar_day_and_gregorian_scope')
            if spec.start < self.rows[0][0] or spec.end > self.rows[-1][0] + timedelta(days=1):
                raise CalendarResolutionError('calendar_out_of_range')
            days = [d for d, k in self.rows if spec.start <= d < spec.end and k[2] == spec.day
                    and (spec.month is None or k[1] == spec.month)
                    and (spec.leap == 'unspecified' or k[3] == (spec.leap == 'leap'))]
            if not days:
                raise CalendarResolutionError('empty_recurrence')
            return [dict(mode='event', ranges=[dict(start_inclusive=d.isoformat(), end_exclusive=(d + timedelta(days=1)).isoformat()) for d in days], range_operator='or', label='primary')]
        if start is None or end is None or start >= end:
            raise CalendarResolutionError('invalid_time_range')
        if spec.period_extent == 'to_as_of':
            if spec.kind not in ('month', 'quarter', 'year', 'week', 'range'):
                raise CalendarResolutionError('to_as_of_not_supported_for_this_kind')
            if not start <= anchor < end:
                raise CalendarResolutionError('as_of_outside_selected_period')
            end = anchor + timedelta(days=1)
        # A year omitted from a named period must not silently select a future period.
        if spec.year is None and not spec.relative and spec.kind in ('date', 'month', 'quarter', 'tet') and start > anchor:
            return self.resolve(spec.model_copy(update={'year': year - 1}), as_of)
        result = [dict(mode='event', start_inclusive=start.isoformat(), end_exclusive=end.isoformat(), label='primary')]
        if spec.comparison == 'previous_equal_days':
            previous = start - timedelta(days=spec.comparison_days or (end - start).days)
            result.append(dict(mode='event', start_inclusive=previous.isoformat(), end_exclusive=start.isoformat(), label='comparison'))
        elif spec.comparison == 'previous_year':
            if lunar:
                if spec.relative == 'this' or spec.period_extent == 'to_as_of':
                    raise CalendarResolutionError('lunar_ytd_comparison_requires_explicit_policy')
                previous = self.resolve(spec.model_copy(update={'year': year - 1, 'relative': None, 'comparison': None}), as_of)
                result.extend(dict(p, label='comparison') for p in previous)
            else:
                try:
                    a = start.replace(year=start.year - 1)
                    b = (anchor.replace(year=anchor.year - 1) + timedelta(days=1)
                         if spec.period_extent == 'to_as_of' or spec.relative == 'this'
                         else end.replace(year=end.year - 1))
                except ValueError as exc:
                    raise CalendarResolutionError('comparison_requires_leap_day_policy') from exc
                result.append(dict(mode='event', start_inclusive=a.isoformat(), end_exclusive=b.isoformat(), label='comparison'))
        elif spec.comparison == 'previous_month_matched':
            if lunar:
                raise CalendarResolutionError('lunar_matched_comparison_requires_policy')
            y, m = (start.year - 1, 12) if start.month == 1 else (start.year, start.month - 1)
            a = date(y, m, 1)
            b = a + timedelta(days=min((end - start).days, calendar.monthrange(y, m)[1]))
            result.append(dict(mode='event', start_inclusive=a.isoformat(), end_exclusive=b.isoformat(), label='comparison'))
        return result
