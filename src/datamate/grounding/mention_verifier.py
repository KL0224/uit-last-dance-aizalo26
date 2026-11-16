"""Check extraction provenance and calculate dates without planning SQL semantics."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import unicodedata

from .context_index import normalized as _fold_vi
from .mention_contracts import MentionProposal
from .proposal_recovery import rejected_claim


def _find_span_index(haystack_nfc: str, haystack_folded: str, needle: str) -> int:
    """Locate span in question, falling back to case/accent-folded matching."""
    norm_nfc = ' '.join(unicodedata.normalize('NFC', needle).split())
    if not norm_nfc:
        return -1
    pos = haystack_nfc.find(norm_nfc)
    if pos >= 0:
        return pos
    folded = ' '.join(_fold_vi(norm_nfc).split())
    return haystack_folded.find(folded) if folded else -1


def parse_mentions(raw):
    """A malformed optional item must not discard independent mentions/windows."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('proposal must be a JSON object')
    expected = set(MentionProposal.model_fields)
    if set(data) != expected:
        raise ValueError(f'grounding v3 requires exactly {sorted(expected)}')
    base = {key: [] for key in expected if key != 'temporal_intent'}
    base['temporal_intent'] = data['temporal_intent']
    MentionProposal.model_validate(base)
    rejected = []
    for field in MentionProposal.model_fields:
        if field == 'temporal_intent':
            continue
        items = data[field]
        if not isinstance(items, list):
            rejected.append(rejected_claim(field, field, 'expected a list', items))
            continue
        limit = next(m.max_length for m in MentionProposal.model_fields[field].metadata if hasattr(m, 'max_length'))
        if len(items) > limit:
            rejected.append(rejected_claim(field, field, f'item limit is {limit}', items[limit:]))
        for n, item in enumerate(items[:limit]):
            try:
                parsed = MentionProposal.model_validate({**base, field: [item]})
            except ValueError as exc:
                affects = item.get('applies_to', []) if isinstance(item, dict) else []
                if not isinstance(affects, list) or not all(isinstance(ref, str) for ref in affects):
                    affects = []
                rejected.append(rejected_claim(field, f'{field}[{n}]', exc, item,
                    affects=affects))
            else:
                base[field] = [*base[field], getattr(parsed, field)[-1].model_dump(mode='json')
                    if hasattr(getattr(parsed, field)[-1], 'model_dump') else getattr(parsed, field)[-1]]
    return MentionProposal.model_validate(base), rejected


def verify_mentions(proposal, request, index, *, rejected_claims=()):
    if request.business_id != index.business_id:
        raise ValueError('business mismatch')
    rejected = list(rejected_claims)
    unresolved = [dict(code='MODEL_UNRESOLVED', raw_text=text, affects=[]) for text in proposal.unresolved]
    normalize = lambda text: ' '.join(unicodedata.normalize('NFC', text).split())
    question = normalize(request.question)
    question_folded = ' '.join(_fold_vi(question).split())
    all_items = [x for group in ('metric_mentions', 'entity_mentions', 'condition_mentions', 'time')
                 for x in getattr(proposal, group)]
    counts = Counter(x.id for x in all_items)

    def reject(group, item, reason, code='MENTION_REJECTED'):
        rejected.append(rejected_claim(group, item.id, reason, item.model_dump(mode='json'),
            code=code, affects=getattr(item, 'applies_to', [])))

    mentions = {}
    for group in ('metric_mentions', 'entity_mentions', 'condition_mentions'):
        kept = []
        for item in getattr(proposal, group):
            if counts[item.id] != 1:
                reject(group, item, 'duplicate ID')
            elif _find_span_index(question, question_folded, item.text) < 0:
                reject(group, item, 'mention must be a verbatim question span')
            else:
                kept.append(item.model_dump())
        # Question order is preserved even if the model emits items out of order.
        mentions[group] = sorted(kept, key=lambda m: _find_span_index(question, question_folded, m['text']))
    refs = {m['id'] for items in mentions.values() for m in items}
    times, windows = [], []
    for spec in proposal.time:
        try:
            if counts[spec.id] != 1:
                raise ValueError('duplicate ID')
            if _find_span_index(question, question_folded, spec.raw_expression) < 0:
                raise ValueError('raw_expression must be a verbatim question span')
            # Do not drop valid time windows just because an unquoted/shorthand mention in applies_to was rejected.
            valid_applies = [ref for ref in spec.applies_to if ref in refs]
            resolved_spec = spec if valid_applies == spec.applies_to else spec.model_copy(update={'applies_to': valid_applies})
            ranges = index.calendar.resolve(resolved_spec.calculation_spec(), request.as_of_date)
        except (ValueError, TypeError) as exc:
            reject('time', spec, str(exc), 'TEMPORAL_UNRESOLVED')
            continue
        times.append(resolved_spec.model_dump(mode='json', exclude_none=True))
        for n, bounds in enumerate(ranges):
            label = bounds.pop('label', 'primary')
            windows.append(dict(id=f'{resolved_spec.id}_{n}', source_time_id=resolved_spec.id,
                raw_expression=resolved_spec.raw_expression, applies_to=resolved_spec.applies_to,
                role=resolved_spec.role if label == 'primary' else label,
                calculation_status='calculated', calendar_sha256=index.calendar.fingerprint, **bounds))

    def issue(code, text, affects=()):
        unresolved.append(dict(code=code, raw_text=text, affects=list(affects)))

    intent = proposal.temporal_intent
    if intent == 'unknown':
        issue('TEMPORAL_INTENT_UNRESOLVED', 'Temporal intent remains unknown.')
    if intent == 'none' and proposal.time:
        issue('TEMPORAL_INTENT_CONFLICT', 'Time expressions contradict temporal_intent=none.')
    if intent in ('single_period', 'compare_periods') and not windows:
        issue('MISSING_TEMPORAL_WINDOW', 'No usable date window remains.')
    if intent == 'single_period' and any(w['role'] == 'comparison' for w in windows):
        issue('TEMPORAL_INTENT_CONFLICT', 'Comparison windows contradict single_period intent.')
    if intent == 'compare_periods':
        scopes = defaultdict(set)
        for window in windows:
            scopes[tuple(sorted(window['applies_to']))].add(window['role'])
        if not scopes or any(not {'primary', 'comparison'} <= roles for roles in scopes.values()):
            issue('MISSING_COMPARISON_WINDOW', 'Each comparison scope needs primary and comparison windows.')
    for claim in rejected:
        issue(claim['code'], f"{claim['group']} {claim['ref']}: {claim['reason']}", claim['affects'])
    temporal_errors = any(p['code'].startswith(('TEMPORAL', 'MISSING_COMPARISON', 'MISSING_TEMPORAL')) for p in unresolved)
    temporal_errors |= any(c['group'] == 'time' for c in rejected)
    return dict(
        request=dict(contract_version='3.0', question_id=request.question_id, business_id=request.business_id,
                     question=request.question, as_of_date=request.as_of_date),
        **mentions, temporal_intent=intent, time=times,
        temporal_plan=dict(completeness_status='incomplete' if temporal_errors else 'complete',
                           intent=intent, resolved_windows=windows),
        assessment=dict(validation_status='partial' if unresolved else 'valid', coverage_status='unknown',
                        unresolved=unresolved, rejected_claims=rejected,
                        warnings=[], missing_evidence_proof=None))
