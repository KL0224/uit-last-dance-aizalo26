"""Recover independent typed claims without repairing or guessing their contents."""
from __future__ import annotations

import json

from .compact_proposal import WireProposal
from .neo_contracts import Proposal


def rejected_claim(group, ref, reason, claim, *, code='CLAIM_REJECTED', affects=()):
    return dict(group=group, ref=ref, code=code, reason=str(reason)[:1200],
                claim=claim, affects=list(affects))


def parse_partial_proposal(raw, refs=None):
    """Root identity/intent stay strict; optional items fail independently.

    JSON syntax, root types and the presence of required wire fields remain fatal.
    Each item is checked with the original bounded model and alias mapper. Failed
    items remain diagnostics, never silently become active constraints.
    """
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('proposal must be a JSON object')
    model = WireProposal if refs is not None else Proposal
    root_fields = {'operation', 'answer_type', 'temporal_intent', 'tables'}
    unknown = set(data) - model.model_fields.keys()
    if unknown:
        raise ValueError(f'unknown proposal fields: {sorted(unknown)}')
    if refs is not None and 'time' not in data:
        raise ValueError('wire proposal requires time')
    base = {key: value for key, value in data.items() if key in root_fields}
    base['time'] = []
    issues = []

    def reject_item(field, ref, reason, item):
        affects = []
        if isinstance(item, dict):
            affects = item.get('applies_to') or item.get('tables') or []
            if field == 'measures':
                affects = [item.get('id', str(ref))]
            elif field == 'cohort':
                affects = [item.get('measure', 'intent')]
            elif field == 'unit_plan':
                affects = [item.get('quantity_column', 'intent')]
        if not isinstance(affects, list) or not all(isinstance(x, str) for x in affects):
            affects = []
        if refs is not None:
            affects = [refs.tables.get(x, refs.columns.get(x, x)) for x in affects]
        issues.append(rejected_claim(field, str(ref), reason, item,
            code='INVALID_PROPOSAL_ITEM', affects=affects))
    # Keep known selected sources, without inventing a source for an unknown ID.
    if refs is not None and isinstance(base.get('tables'), list):
        known = []
        for ref in base['tables']:
            if isinstance(ref, str) and ref in refs.tables:
                known.append(ref)
            else:
                issues.append(rejected_claim('tables', str(ref), 'unknown table reference', ref))
        base['tables'] = known
    root = model.model_validate(base)
    materialized = refs.materialize(root) if refs is not None else root
    result = materialized.model_dump(mode='json')
    for field, value in data.items():
        if field in root_fields:
            continue
        is_list = isinstance(getattr(root, field), list)
        if is_list and not isinstance(value, list):
            reject_item(field, field, 'expected a list', value)
            continue
        limit = next((m.max_length for m in model.model_fields[field].metadata
                      if hasattr(m, 'max_length')), None)
        items = value if is_list else [value]
        if is_list and limit is not None and len(items) > limit:
            reject_item(field, field, f'item limit is {limit}', items[limit:])
            items = items[:limit]
        for position, item in enumerate(items):
            ref = item.get('id', f'{field}[{position}]') if isinstance(item, dict) else f'{field}[{position}]'
            try:
                candidate = model.model_validate({**base, field: [item] if is_list else item})
                mapped = refs.materialize(candidate) if refs is not None else candidate
                parsed = getattr(mapped, field)
            except (ValueError, TypeError) as exc:
                reject_item(field, ref, exc, item)
                continue
            if is_list:
                result[field].extend(x.model_dump(mode='json') if hasattr(x, 'model_dump') else x for x in parsed)
            else:
                result[field] = parsed.model_dump(mode='json') if hasattr(parsed, 'model_dump') else parsed
    return Proposal.model_validate(result), issues
