"""Validate independent claims, retain useful evidence and expose repair dependencies."""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from math import isfinite
import duckdb

from .neo_contracts import Proposal
from .calendar_resolver import CalendarResolutionError
from .proposal_recovery import rejected_claim


def verify_proposal(proposal: Proposal, request, index, value_verifier=None, *, rejected_claims=()):
    if request.business_id != index.business_id:
        raise ValueError('business mismatch')
    rejected = list(rejected_claims)
    unresolved = [dict(code='MODEL_UNRESOLVED', raw_text=x, affects=[]) for x in proposal.unresolved]
    warnings = []

    def reject(group, ref, exc, claim, *, code='CLAIM_REJECTED', affects=()):
        raw = claim.model_dump(mode='json') if hasattr(claim, 'model_dump') else claim
        if not affects and isinstance(raw, dict):
            affects = raw.get('applies_to') or raw.get('tables') or []
            if group == 'measures':
                affects = [raw['id']]
            elif group == 'cohort':
                affects = [raw['measure']]
            elif group == 'unit_plan':
                affects = [raw['quantity_column']]
            elif group == 'entity_keys':
                affects = [raw['scope']]
        rejected.append(rejected_claim(group, ref, exc, raw, code=code, affects=affects))

    tables = []
    for ref in dict.fromkeys(proposal.tables):
        if ref in index.tables:
            tables.append(ref)
        else:
            reject('tables', ref, 'unknown table reference', ref, affects=[ref])
    if not tables:
        raise ValueError('no valid grounding source remains')
    columns = {c for c in index.columns if c.rsplit('.', 1)[0] in tables}

    def column(ref):
        if ref not in columns:
            raise ValueError(f'unknown column reference: {ref}')

    def policies(refs, owner):
        result = []
        for ref in refs:
            if ref in index.policies:
                result.append(ref)
            else:
                reject('policy_refs', ref, 'unknown policy reference', ref, affects=[owner])
        return result

    root_policies = policies(proposal.policy_refs, 'intent')
    counts = Counter(m.id for m in proposal.measures)
    candidates = {}
    for m in proposal.measures:
        if counts[m.id] != 1 or m.id in columns:
            reject('measures', m.id, 'duplicate or colliding measure IDs', m, code='MEASURE_REJECTED', affects=[m.id])
        else:
            candidates[m.id] = m.model_copy(update={'policy_refs': policies(m.policy_refs, m.id)})
    measures, errors = {}, {}

    def visit(ident, path=()):
        if ident in measures:
            return
        if ident in path:
            raise ValueError('cyclic calculation')
        if ident in errors:
            raise ValueError(f'operand {ident} rejected: {errors[ident]}')
        if ident not in candidates:
            raise ValueError(f'missing measure operand: {ident}')
        m = candidates[ident]
        try:
            if bool(m.aggregate) == bool(m.operator):
                raise ValueError('measure needs exactly one aggregate or operator')
            for ref in m.columns + m.grain:
                column(ref)
            if m.operator:
                if len(m.operands) != 2 or m.columns:
                    raise ValueError('derived measure requires two operands and no columns')
                for operand in m.operands:
                    visit(operand, (*path, ident))
            else:
                if not m.columns or m.operands:
                    raise ValueError('aggregate needs explicit columns and no operands')
                if m.aggregate in ('sum', 'avg', 'min', 'max') and len(m.columns) != 1:
                    raise ValueError('aggregate requires one column')
                if m.aggregate in ('sum', 'avg'):
                    c = index.columns[m.columns[0]]
                    dtype = str(c.get('data_type', c.get('sql_type', c.get('dtype', '')))).upper()
                    if dtype and not any(t in dtype for t in ('INT', 'DECIMAL', 'NUMERIC', 'FLOAT', 'DOUBLE', 'REAL')):
                        raise ValueError('numeric measure bound to nonnumeric column')
        except ValueError as exc:
            errors[ident] = str(exc)
            raise
        measures[ident] = m

    for ident, m in candidates.items():
        try:
            visit(ident)
        except ValueError as exc:
            reject('measures', ident, exc, m, code='MEASURE_REJECTED', affects=[ident])
    # Preserve proposal order rather than depth-first traversal order.
    measures = {m.id: measures[m.id] for m in proposal.measures if m.id in measures}
    scopes = set(tables) | measures.keys()

    def unique(items, group):
        counts = Counter(x.id for x in items)
        for item in items:
            if counts[item.id] > 1:
                reject(group, item.id, 'duplicate claim ID', item)
            else:
                yield item

    dimensions = []
    for ref in proposal.dimensions:
        try:
            column(ref)
            dimensions.append(ref)
        except ValueError as exc:
            reject('dimensions', ref, exc, ref)
    order_by = []
    for ref, direction in proposal.order_by:
        if ref in measures or ref in dimensions:
            order_by.append((ref, direction))
        else:
            reject('order_by', ref, 'unknown ordering reference', [ref, direction], affects=[ref])

    def predicate(p, depth=0):
        if depth > 12:
            raise ValueError('predicate depth limit')
        if p.op in ('AND', 'OR', 'NOT'):
            if p.field is not None or p.value is not None or not p.children or (p.op == 'NOT' and len(p.children) != 1):
                raise ValueError('invalid boolean predicate')
            for child in p.children:
                predicate(child, depth + 1)
        else:
            if p.children or p.field not in columns | measures.keys():
                raise ValueError('invalid predicate reference')
            if p.op == 'IN' and not isinstance(p.value, list):
                raise ValueError('IN requires list')
            if p.op == 'LIKE' and not isinstance(p.value, str):
                raise ValueError('LIKE requires string')
            if p.op in ('IS NULL', 'IS NOT NULL'):
                if p.value is not None:
                    raise ValueError('IS NULL predicates do not take a value')
            elif p.value is None:
                raise ValueError('NULL comparison requires IS NULL')

    filters = []
    for f in unique(proposal.filters, 'filters'):
        try:
            if not set(f.applies_to) <= scopes:
                raise ValueError('unknown filter scope reference')
            predicate(f.predicate)
            filters.append(f)
        except ValueError as exc:
            # Never salvage individual children: dropping an OR/NOT child changes meaning.
            reject('filters', f.id, exc, f, code='FILTER_REJECTED', affects=f.applies_to)

    values, lookups = [], {}
    lookup_scopes = defaultdict(set)

    def collect(p, applies_to):
        if p.op in ('=', 'IN') and p.field in columns:
            literals = p.value if isinstance(p.value, list) else [p.value]
            if all(isinstance(v, str) for v in literals):
                lookups.setdefault(p.field, []).extend(literals)
                lookup_scopes[p.field].update(applies_to)
        for child in p.children:
            collect(child, applies_to)

    for f in filters:
        collect(f.predicate, f.applies_to)
    lookups = {k: list(dict.fromkeys(v)) for k, v in lookups.items()}
    try:
        observed = value_verifier.verify(lookups) if value_verifier and lookups else {}
    except (OSError, ValueError, duckdb.Error) as exc:
        observed = {}
        reject('value_bindings', 'value_bindings', exc, lookups, code='VALUE_LOOKUP_FAILED',
            affects=list(lookups))
    for ref, literals in lookups.items():
        for value in literals:
            if value in (observed.get(ref) or []):
                values.append(dict(id=f'V{len(values)}', raw_text=value, column=ref, resolved_value=value,
                    match_method='exact', verification_status='data_observed', evidence_refs=[],
                    evidence=dict(database_fingerprint=index.fingerprint)))
            else:
                unresolved.append(dict(code='VALUE_NOT_VERIFIED', raw_text=value,
                    affects=[ref, *sorted(lookup_scopes[ref])]))

    combinations = []
    for combo in unique(proposal.combinations, 'combinations'):
        try:
            if not set(combo.tables) <= set(tables):
                raise ValueError('unknown combination source')
            if combo.kind == 'join':
                if len(combo.tables) != 2 or not combo.key_pairs or len(set(combo.tables)) != 2:
                    raise ValueError('JOIN requires two distinct tables and explicit keys')
                for left, right in combo.key_pairs:
                    column(left)
                    column(right)
                    if left.rsplit('.', 1)[0] != combo.tables[0] or right.rsplit('.', 1)[0] != combo.tables[1]:
                        raise ValueError('JOIN keys must connect the declared sources')
            else:
                layouts = [{c['name']: c.get('data_type', c.get('sql_type', c.get('dtype')))
                            for c in index.tables[t]['columns']} for t in combo.tables]
                if any(layout != layouts[0] for layout in layouts[1:]):
                    raise ValueError('UNION requires compatible named columns')
            combinations.append(dict(**combo.model_dump(), trust_status='uncertain', verification_status='reference_valid'))
            if combo.kind == 'join':
                warnings.append(dict(code='JOIN_SEMANTICS_UNREVIEWED', refs=[combo.id], message='Keys exist; JOIN cardinality and meaning still need review.'))
        except ValueError as exc:
            reject('combinations', combo.id, exc, combo, code='COMBINATION_REJECTED', affects=combo.tables)

    entity_keys = []
    for n, entity in enumerate(proposal.entity_keys):
        try:
            if entity.scope not in tables:
                raise ValueError('unknown entity scope')
            for ref in entity.columns:
                column(ref)
                if ref.rsplit('.', 1)[0] != entity.scope:
                    raise ValueError('entity key must belong to its source')
            entity_keys.append(entity)
        except ValueError as exc:
            reject('entity_keys', f'entity_keys[{n}]', exc, entity, affects=[entity.scope])

    cohort = proposal.cohort
    if cohort:
        try:
            if cohort.measure not in measures:
                raise ValueError('cohort requires an existing measure')
            for ref in cohort.group_by:
                column(ref)
            if set(cohort.group_by) != set(measures[cohort.measure].grain):
                raise ValueError('cohort grouping must match the measure aggregation grain')
            if not measures[cohort.measure].aggregate or not isfinite(cohort.threshold):
                raise ValueError('cohort requires an aggregate and finite threshold')
        except ValueError as exc:
            reject('cohort', 'cohort', exc, cohort, code='COHORT_REJECTED', affects=[cohort.measure])
            cohort = None

    unit_plan = None
    unit = proposal.unit_plan
    if unit:
        try:
            column(unit.quantity_column)
            if unit.item_column:
                column(unit.item_column)
            if any(ref not in index.policies for ref in unit.policy_refs):
                raise ValueError('unknown conversion policy')
            if unit.already_converted and unit.conversion_refs:
                raise ValueError('cannot apply factor to already converted quantity')
            conversions = []
            for ref in unit.conversion_refs:
                if ref not in index.conversions:
                    raise ValueError('unknown unit conversion')
                conversion = index.conversions[ref]
                try:
                    factor = Decimal(str(conversion['factor']))
                    if not factor.is_finite() or factor <= 0:
                        raise ValueError('invalid conversion factor')
                except (InvalidOperation, KeyError) as exc:
                    raise ValueError('invalid conversion factor') from exc
                if conversion.get('to_unit') != unit.target or not unit.item_column:
                    raise ValueError('conversion target or item scope mismatch')
                conversions.append(dict(id=ref, **conversion))
            unit_plan = dict(**unit.model_dump(), conversions=conversions, verification_status='reference_valid', scope_status='semantic_unreviewed')
            unresolved.append(dict(code='UNIT_SCOPE_REQUIRES_REVIEW', raw_text=unit.target, affects=[unit.quantity_column]))
        except ValueError as exc:
            reject('unit_plan', 'unit_plan', exc, unit, code='UNIT_PLAN_REJECTED', affects=[unit.quantity_column])

    temporal, unbound_temporal = [], []
    for n, spec in enumerate(proposal.time):
        try:
            column(spec.column)
            metadata = index.columns[spec.column]
            dtype = str(metadata.get('data_type', metadata.get('sql_type', metadata.get('dtype', '')))).upper()
            if dtype and not any(kind in dtype for kind in ('DATE', 'TIME')):
                raise ValueError('temporal binding requires date/timestamp column')
            if spec.date_role not in ('order_date', 'payment_date', 'stock_event_date', 'expiry_date'):
                raise ValueError('unknown temporal date role')
            if spec.role != 'primary' and spec.comparison is not None:
                raise ValueError('comparison relation requires primary role')
        except ValueError as exc:
            reject('time', f'time[{n}]', exc, spec, code='TEMPORAL_BINDING_REJECTED', affects=spec.applies_to)
            continue
        unbound = not spec.applies_to or not set(spec.applies_to) <= scopes
        if unbound:
            reject('time', f'time[{n}]', 'unknown or empty temporal scope; date bounds retained as unbound evidence',
                spec, code='TEMPORAL_SCOPE_UNRESOLVED', affects=spec.applies_to)
        effective_spec = spec
        if spec.comparison == 'unknown':
            unresolved.append(dict(code='COMPARISON_RELATION_UNRESOLVED', raw_text=spec.raw_expression, affects=spec.applies_to))
            effective_spec = spec.model_copy(update={'comparison': None})
        try:
            ranges = index.calendar.resolve(effective_spec, request.as_of_date)
        except (CalendarResolutionError, TypeError, ValueError) as exc:
            reject('time', f'time[{n}]', exc, spec, code='TEMPORAL_UNRESOLVED', affects=spec.applies_to)
            continue
        for j, bounds in enumerate(ranges):
            if bounds.get('label', 'primary') == 'primary':
                bounds['label'] = spec.role
            constraint = dict(id=f'T{n}_{j}', raw_expression=spec.raw_expression, column=spec.column,
                applies_to=[] if unbound else spec.applies_to, date_role=spec.date_role, calendar_basis=spec.calendar,
                verification_status='reference_valid', calculation_status='calculated', semantic_status='semantic_unreviewed', policy_refs=root_policies,
                evidence=dict(calendar_sha256=index.calendar.fingerprint, spec=spec.model_dump(mode='json')), **bounds)
            if unbound:
                constraint.update(requested_applies_to=spec.applies_to, usage_status='requires_repair')
                unbound_temporal.append(constraint)
            else:
                temporal.append(constraint)

    # Every removed claim stays visible as an unmet requirement, including aliases
    # that failed before materialization. Rejected raw claims are not active plans.
    for claim in rejected:
        unresolved.append(dict(code=claim['code'], raw_text=f"{claim['group']} {claim['ref']}: {claim['reason']}", affects=claim['affects']))
        warnings.append(dict(code=claim['code'], refs=[claim['ref']], message=f"Removed {claim['group']}: {claim['reason']}"))
    from .temporal_validation import check_temporal_completeness
    checked = proposal.model_copy(update={'measures': list(measures.values())})
    temporal_plan, temporal_problems = check_temporal_completeness(checked, temporal, unresolved)
    temporal_plan['unbound_constraints'] = unbound_temporal
    if any(c['group'] == 'time' for c in rejected):
        temporal_plan['completeness_status'] = 'incomplete'
    unresolved.extend(temporal_problems)
    warnings.extend(dict(code=p['code'], refs=p['affects'], message=p['raw_text']) for p in temporal_problems)
    if not measures and proposal.operation not in ('lookup', 'existence', 'table_report'):
        unresolved.append(dict(code='MISSING_MEASURES', raw_text='No usable measure remains; reconstruct it from the question and source policies.', affects=['intent']))

    # Keep a useful binding, but never present it as executable after losing a
    # required filter, window, unit conversion, grouping or source combination.
    blocked = defaultdict(set)

    def block(refs, code):
        refs = set(refs)
        if not refs or 'intent' in refs:
            refs.update(measures)
        for ident, m in measures.items():
            dependencies = {ident, *m.columns, *m.grain}
            dependencies.update(c.rsplit('.', 1)[0] for c in m.columns + m.grain)
            if dependencies & refs:
                blocked[ident].add(code)

    for claim in rejected:
        if claim['group'] != 'measures':
            raw = claim['claim']
            scope = claim['affects']
            if not scope and isinstance(raw, dict):
                scope = raw.get('applies_to') or raw.get('tables') or []
            block(scope, claim['code'])
    for problem in unresolved:
        block(problem['affects'], problem['code'])
    changed = True
    while changed:
        changed = False
        for ident, m in measures.items():
            inherited = set().union(*(blocked.get(operand, set()) for operand in m.operands))
            if not inherited <= blocked[ident]:
                blocked[ident].update(inherited)
                changed = True
    warnings.append(dict(code='SEMANTIC_UNREVIEWED', refs=list(measures), message='Bindings, grain and formulas require review against policies. Repair blocked_refs before using them; partial does not prove unanswerable.'))
    policy_ids = set(root_policies) | {p for m in measures.values() for p in m.policy_refs} | index.core_policy_ids
    policy_ids.update(unit.policy_refs if unit_plan else [])
    accepted = dict(tables=len(tables), measures=len(measures), dimensions=len(dimensions), filters=len(filters),
                    combinations=len(combinations), entity_keys=len(entity_keys), cohort=int(cohort is not None),
                    unit_plan=int(unit_plan is not None), time=len(temporal), order_by=len(order_by),
                    policy_refs=len(policy_ids), value_bindings=len(values))
    rejected_counts = Counter(c['group'] for c in rejected)
    for group in rejected_counts:
        accepted.setdefault(group, 0)
    group_status = {group: dict(accepted=count, rejected=rejected_counts[group],
        status='partial' if rejected_counts[group] else ('reference_valid' if count else 'not_requested'))
        for group, count in accepted.items()}
    group_status['time']['status'] = temporal_plan['completeness_status']
    group_status['time']['unbound'] = len(unbound_temporal)
    group_status['measures']['blocked'] = sum(bool(blocked[ident]) for ident in measures)
    return dict(
        request=dict(contract_version='2.0', question_id=request.question_id, business_id=request.business_id, question=request.question, as_of_date=request.as_of_date),
        intent=dict(operation=proposal.operation, answer_type=proposal.answer_type,
                    order_by=[dict(ref=r, direction=d) for r, d in order_by], limit=proposal.limit, tie_break=None),
        source_plan=dict(sources=[dict(id=t, tables=[t], columns=[c['name'] for c in index.tables[t]['columns']], grain=None) for t in tables], combinations=combinations),
        semantic_plan=dict(measures=[dict(**m.model_dump(), verification_status='reference_valid', semantic_status='semantic_unreviewed',
                usage_status='requires_repair' if blocked[m.id] else 'candidate') for m in measures.values()],
            dimensions=[dict(id=c, column=c) for c in dimensions], filters=[f.model_dump() for f in filters],
            aggregation_grain=[dict(measure=m.id, keys=m.grain) for m in measures.values()],
            entity_keys=[e.model_dump() for e in entity_keys], unit_plan=unit_plan, cohort=cohort.model_dump() if cohort else None),
        temporal_plan=temporal_plan, value_bindings=values,
        policies=[index.policies[p] for p in sorted(policy_ids)],
        assessment=dict(validation_status='partial', coverage_status='unknown', warnings=warnings, unresolved=unresolved,
            rejected_claims=rejected, blocked_refs=[dict(ref=ref, reason_codes=sorted(codes)) for ref, codes in sorted(blocked.items()) if codes],
            group_status=group_status, missing_evidence_proof=None))
