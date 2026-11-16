"""Grounding v3: verbatim mentions and source-independent temporal expressions."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .calendar_resolver import TemporalExpression


class Mention(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=1000)


class MentionTime(TemporalExpression):
    id: str = Field(min_length=1, max_length=32)
    raw_expression: str = Field(min_length=1, max_length=1000)
    period_extent: Literal['full_period', 'to_as_of', 'snapshot', 'unknown']
    comparison: Literal['none', 'previous_equal_days', 'previous_year', 'previous_month_matched', 'unknown']
    role: Literal['primary', 'comparison', 'series']
    applies_to: list[str] = Field(max_length=32)

    @model_validator(mode='after')
    def coherent_expression(self):
        allowed_components = {
            'date': {'year', 'month', 'day'}, 'month': {'year', 'month'},
            'quarter': {'year', 'quarter'}, 'year': {'year'}, 'tet': {'year'},
            'recurring_day': {'month', 'day'},
        }.get(self.kind, set())
        for field in ('year', 'month', 'quarter', 'day'):
            if getattr(self, field) is not None and field not in allowed_components:
                raise ValueError(f'{field} is not used by {self.kind}; use the appropriate endpoint fields')
        if self.kind not in ('range', 'snapshot', 'recurring_day') and (self.start or self.end):
            raise ValueError('start/end are only used by range, snapshot and recurring_day')
        if self.kind == 'snapshot' and self.start:
            raise ValueError('snapshot retains all history; it cannot have a start')
        if self.kind != 'range' and (self.lunar_start or self.lunar_end_inclusive):
            raise ValueError('lunar endpoints are only used by range')
        if self.count is not None and self.kind != 'recent_days':
            raise ValueError('count is only used by recent_days')
        if self.comparison_days is not None and self.comparison != 'previous_equal_days':
            raise ValueError('comparison_days requires previous_equal_days')
        if self.relative and any(v is not None for v in (self.year, self.month, self.quarter, self.day)):
            raise ValueError('explicit date components cannot coexist with relative')
        if self.relative and self.kind not in ('month', 'year', 'week'):
            raise ValueError('relative is only supported for month/year/week')
        if self.kind == 'week' and self.relative is None:
            raise ValueError('week requires this/previous; explicit weeks use range')
        if self.kind == 'month' and self.relative is None and self.month is None:
            raise ValueError('explicit month requires month')
        if self.kind == 'date' and (self.month is None or self.day is None):
            raise ValueError('date requires month and day; today/yesterday use range')
        if self.kind == 'quarter' and self.quarter is None:
            raise ValueError('quarter requires quarter number')
        if self.role != 'primary' and self.comparison != 'none':
            raise ValueError('only primary may generate comparison windows')
        if self.period_extent == 'full_period' and self.relative == 'this':
            raise ValueError('this period uses to_as_of')
        if (self.kind == 'snapshot') != (self.period_extent == 'snapshot'):
            raise ValueError('snapshot kind and extent must agree')
        return self

    def calculation_spec(self):
        # The calendar resolver owns arithmetic; no column/date-role is needed.
        return TemporalExpression.model_validate({
            **self.model_dump(exclude={'id', 'comparison'}),
            'comparison': None if self.comparison == 'none' else self.comparison,
        })


class MentionProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    metric_mentions: list[Mention] = Field(max_length=16)
    entity_mentions: list[Mention] = Field(max_length=24)
    condition_mentions: list[Mention] = Field(max_length=24)
    temporal_intent: Literal['none', 'single_period', 'compare_periods', 'compare_measures', 'unknown']
    time: list[MentionTime] = Field(max_length=8)
    unresolved: list[str] = Field(max_length=16)
