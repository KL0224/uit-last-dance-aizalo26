"""Strict, bounded proposal models. Trust and dates are materialized by code."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from .calendar_resolver import TemporalSpec

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Measure(StrictModel):
    id: str
    concept: str
    aggregate: Literal['sum', 'count', 'count_distinct', 'avg', 'min', 'max'] | None = None
    columns: list[str] = Field(default_factory=list, max_length=16)
    operator: Literal['add', 'subtract', 'multiply', 'divide', 'percent_change'] | None = None
    operands: list[str] = Field(default_factory=list, max_length=16)
    grain: list[str] = Field(default_factory=list, max_length=16)
    policy_refs: list[str] = Field(default_factory=list, max_length=32)

class Predicate(StrictModel):
    op: Literal['AND', 'OR', 'NOT', '=', '!=', '<', '<=', '>', '>=', 'IN', 'LIKE', 'IS NULL', 'IS NOT NULL']
    field: str | None = None
    value: JsonValue = None
    children: list[Predicate] = Field(default_factory=list, max_length=32)

class Filter(StrictModel):
    id: str
    scope: Literal['row', 'group', 'measure', 'order']
    applies_to: list[str] = Field(min_length=1, max_length=32)
    predicate: Predicate

class Combination(StrictModel):
    id: str
    kind: Literal['join', 'union_all']
    tables: list[str] = Field(min_length=2, max_length=64)
    key_pairs: list[tuple[str, str]] = Field(default_factory=list, max_length=16)
    join_type: Literal['inner', 'left', 'full'] = 'inner'

class EntityKey(StrictModel):
    entity: str
    columns: list[str] = Field(min_length=1, max_length=16)
    scope: str

class UnitPlan(StrictModel):
    target: str
    quantity_column: str
    already_converted: bool = False
    conversion_refs: list[str] = Field(default_factory=list, max_length=64)
    item_column: str | None = None
    policy_refs: list[str] = Field(default_factory=list, max_length=32)

class Cohort(StrictModel):
    group_by: list[str] = Field(min_length=1, max_length=8)
    measure: str
    operator: Literal['>=', '>', '=', '<', '<=']
    threshold: float
    result: Literal['count_groups', 'list_groups'] = 'count_groups'

class Proposal(StrictModel):
    operation: Literal['sum', 'count', 'count_distinct', 'avg', 'argmax', 'argmin', 'top_k', 'percent_change', 'ratio', 'comparison', 'lookup', 'existence', 'table_report']
    answer_type: Literal['number', 'percent', 'string', 'date', 'boolean', 'list', 'table']
    temporal_intent: Literal['none', 'single_period', 'compare_periods', 'compare_measures', 'unknown'] = 'unknown'
    tables: list[str] = Field(min_length=1, max_length=64)
    measures: list[Measure] = Field(default_factory=list, max_length=32)
    dimensions: list[str] = Field(default_factory=list, max_length=32)
    filters: list[Filter] = Field(default_factory=list, max_length=32)
    combinations: list[Combination] = Field(default_factory=list, max_length=32)
    time: list[TemporalSpec] = Field(default_factory=list, max_length=32)
    policy_refs: list[str] = Field(default_factory=list, max_length=64)
    order_by: list[tuple[str, Literal['asc', 'desc']]] = Field(default_factory=list, max_length=16)
    limit: int | None = Field(default=None, ge=1)
    entity_keys: list[EntityKey] = Field(default_factory=list, max_length=16)
    unit_plan: UnitPlan | None = None
    cohort: Cohort | None = None
    unresolved: list[str] = Field(default_factory=list, max_length=32)
