"""Short reference namespace, bounded decoding schema and exact materialization.

Aliases replace reference fields only, never literals, question text or policy text.
The final Planner contract continues to use physical references.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Literal
from pydantic import Field
from .neo_contracts import Proposal, Measure


class CompactMeasure(Measure):
    id: Literal['M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7', 'M8']
    concept: str = Field(max_length=120)
    columns: list[str] = Field(default_factory=list, max_length=8)
    grain: list[str] = Field(default_factory=list, max_length=8)


class CompactProposal(Proposal):
    measures: list[CompactMeasure] = Field(default_factory=list, max_length=8)
    unresolved: list[str] = Field(default_factory=list, max_length=8)


# Avoid changing the temporal semantics or duplicating its schema.
from .calendar_resolver import TemporalSpec
class WireTimeSpec(TemporalSpec):
    period_extent: Literal['full_period', 'to_as_of', 'snapshot', 'unknown']
    comparison: Literal['none', 'previous_equal_days', 'previous_year', 'previous_month_matched', 'unknown']
    role: Literal['primary', 'comparison', 'series']
    applies_to: list[str] = Field(min_length=1, max_length=8)

class WireProposal(CompactProposal):
    temporal_intent: Literal['none', 'single_period', 'compare_periods', 'compare_measures', 'unknown']
    time: list[WireTimeSpec] = Field(max_length=8)


class ReferenceMap:
    def __init__(self, index):
        self.tables = {f'T{i}': name for i, name in enumerate(sorted(index.tables))}
        self.columns = {f'C{i}': name for i, name in enumerate(sorted(index.columns))}
        self.reverse = {name: ref for ref, name in (self.tables | self.columns).items()}

    def column(self, ref):
        if ref not in self.columns:
            raise ValueError(f'unknown compact column reference: {ref}')
        return self.columns[ref]

    def table(self, ref):
        if ref not in self.tables:
            raise ValueError(f'unknown compact table reference: {ref}')
        return self.tables[ref]

    def scoped(self, ref):
        return self.table(ref) if ref in self.tables else ref

    def context(self, evidence):
        evidence = deepcopy(evidence)
        evidence['directory'] = [dict(id=self.reverse[name], name=name) for name in evidence['directory']]
        for table in evidence['tables']:
            name = table['name']
            table['id'] = self.reverse[name]
            for column in table['columns']:
                column['id'] = self.reverse[name + '.' + column['name']]
        for metric in evidence['metric_candidates']:
            table = metric.pop('preferred_table', None)
            names = metric.pop('required_columns', [])
            metric['source'] = self.reverse.get(table)
            metric['column_refs'] = [self.reverse[table + '.' + name] for name in names
                                     if table and table + '.' + name in self.reverse]
        # Evidence keeps physical source text as evidence; IDs are explicit in cards.
        return evidence

    def materialize(self, wire: WireProposal):
        data = wire.model_dump(mode='json')
        data['tables'] = [self.table(t) for t in data['tables']]
        for measure in data['measures']:
            for field in ('columns', 'grain'):
                measure[field] = [self.column(ref) for ref in measure[field]]
        data['dimensions'] = [self.column(ref) for ref in data['dimensions']]
        def predicate(p):
            if p['field'] is not None and p['field'] not in {f'M{i}' for i in range(1, 9)}:
                p['field'] = self.column(p['field'])
            for child in p['children']:
                predicate(child)
        for f in data['filters']:
            f['applies_to'] = [self.scoped(ref) for ref in f['applies_to']]
            predicate(f['predicate'])
        for t in data['time']:
            # Unknown relation is retained as a requirement for the verifier.
            if t['comparison'] == 'none':
                t['comparison'] = None
            t['column'] = self.column(t['column'])
            t['applies_to'] = [self.scoped(ref) for ref in t['applies_to']]
        for combo in data['combinations']:
            combo['tables'] = [self.table(ref) for ref in combo['tables']]
            combo['key_pairs'] = [[self.column(a), self.column(b)] for a,b in combo['key_pairs']]
        for e in data['entity_keys']:
            e['columns'] = [self.column(ref) for ref in e['columns']]
            e['scope'] = self.scoped(e['scope'])
        if data['unit_plan']:
            u = data['unit_plan']
            u['quantity_column'] = self.column(u['quantity_column'])
            if u['item_column']:
                u['item_column'] = self.column(u['item_column'])
        if data['cohort']:
            data['cohort']['group_by'] = [self.column(ref) for ref in data['cohort']['group_by']]
        data['order_by'] = [[self.column(r) if r in self.columns else r, d] for r,d in data['order_by']]
        return Proposal.model_validate(data)

    def decoding_schema(self, evidence, index):
        """Enums include only references actually sent, not hidden catalog columns."""
        schema = WireProposal.model_json_schema()
        tables = [t['id'] for t in evidence['tables']]
        columns = [c['id'] for t in evidence['tables'] for c in t['columns']]
        measures = [f'M{i}' for i in range(1, 9)]
        policies = [p['id'] for field in ('policies', 'extra_policies', 'business_policies') for p in evidence[field]]
        def enum(values):
            return dict(type='string', enum=values) if values else dict(type='string', enum=['__NO_VISIBLE_REFERENCE__'])
        props = schema['properties']
        defs = schema['$defs']
        props['tables']['items'] = enum(tables)
        props['dimensions']['items'] = enum(columns)
        for name in ('CompactMeasure', 'EntityKey', 'Cohort'):
            p = defs[name]['properties']
            for field in ('columns', 'grain', 'group_by'):
                if field in p:
                    p[field]['items'] = enum(columns)
        defs['CompactMeasure']['properties']['operands']['items'] = enum(measures)
        defs['Cohort']['properties']['measure'] = enum(measures)
        defs['EntityKey']['properties']['scope'] = enum(tables)
        p = defs['Predicate']['properties']
        p['field'] = dict(anyOf=[enum(columns + measures), dict(type='null')])
        # Predicate literals are scalar or flat scalar arrays, not arbitrary JSON objects.
        scalar = dict(anyOf=[dict(type='string'), dict(type='number'), dict(type='boolean'), dict(type='null')])
        p['value'] = dict(anyOf=scalar['anyOf'] + [dict(type='array', items=scalar, maxItems=32)])
        for name in ('WireTimeSpec', 'Filter'):
            p = defs[name]['properties']
            p['applies_to']['items'] = enum(tables + measures)
        date_columns = [c['id'] for t in evidence['tables'] for c in t['columns']
                        if any(kind in str(c.get('type', '')).upper() for kind in ('DATE', 'TIME'))]
        defs['WireTimeSpec']['properties']['column'] = enum(date_columns)
        if not date_columns:
            props['time']['maxItems'] = 0
        defs['WireTimeSpec']['properties']['date_role'] = enum(['order_date', 'payment_date', 'stock_event_date', 'expiry_date'])
        p = defs['Combination']['properties']
        p['tables']['items'] = enum(tables)
        p['key_pairs']['items'] = dict(type='array', items=enum(columns), minItems=2, maxItems=2)
        # Avoid prefixItems tuple schemas in the constrained backend.
        props['order_by']['items'] = dict(type='array', items=enum(columns + measures + ['asc', 'desc']), minItems=2, maxItems=2)
        p = defs['UnitPlan']['properties']
        p['quantity_column'] = enum(columns)
        p['item_column'] = dict(anyOf=[enum(columns), dict(type='null')])
        units = [u['id'] for u in evidence['unit_candidates']]
        p['conversion_refs']['items'] = enum(units)
        if not units:
            p['conversion_refs']['maxItems'] = 0
        for p in [props, defs['CompactMeasure']['properties'], defs['UnitPlan']['properties']]:
            p['policy_refs']['items'] = enum(policies)
            if not policies:
                p['policy_refs']['maxItems'] = 0
        # JsonValue was replaced above; discard its unused self-recursive definition.
        defs.pop('JsonValue', None)
        return schema
