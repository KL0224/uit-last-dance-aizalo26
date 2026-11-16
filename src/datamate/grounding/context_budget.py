"""Rank schema capabilities and protect source/column evidence before token trimming.

Role matching is retrieval only: it never decides the answer, binds a measure or
trusts a registry preference. The model and verifier still review every binding.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re

from .context_index import normalized


ROLE_PATTERNS = {
    'revenue': r'thanh tien|amount|line net|net amount|tien hang|doanh thu|doanh so|revenue|line total|net sales',
    'payment': r'tien thu|thuc thu|received|paid|payment|thanh toan|thu no|tra no',
    'customer': r'khach|customer|client',
    'order': r'ma don|ma hoa don|order.*(?:id|key|code)|invoice|\bhd\b',
    'quantity': r'so luong|\bsl\b|quantity|qty',
    'cost': r'gia von|cost|chi phi|expense|lai gop|lai rong',
    'stock': r'\bton\b|inventory|stock|balance',
}
STOP_WORDS = set('tu den het hom nay nay truoc cung ky so voi bao nhieu la thi cua cac mot nhung va hay len xuong thay doi tang giam phan tram trong thang nam quy ngay mua ban tong'.split())


def _text(value):
    return normalized(str(value or '')).replace('_', ' ')


def _words(question):
    return {w for w in re.findall(r'\w+', _text(question)) if len(w) > 2 and w not in STOP_WORDS}


def _overlap(text, words):
    return sum(w in text for w in words)


def required_roles(question):
    """Broad role coverage for retrieval; uncertainty remains model-owned."""
    q = _text(question)
    roles = {role for role, pattern in ROLE_PATTERNS.items() if re.search(pattern, q)}
    if re.search(r'\bdon\b|hoa don|invoice|order', q):
        roles.add('order')
    if re.search(r'ngay|thang|nam|quy|tuan|tet|hom nay|hom qua|\d\s*/\s*\d', q):
        roles.add('time')
    if re.search(r'ban chay|ban nhieu', q):
        roles.add('quantity')
    return roles


def _column_roles(column):
    text = _text(column['name']) + ' ' + _text(column.get('original'))
    roles = {role for role, pattern in ROLE_PATTERNS.items() if re.search(pattern, text)}
    dtype = str(column.get('type', '')).upper()
    if any(t in dtype for t in ('DATE', 'TIME')):
        roles.add('time')
    if re.search(r'\bma\b|\bid\b|\bkey\b|\bcode\b|so phieu', text):
        roles.add('key')
    if re.search(r'trang thai|status|state|ghi chu|note', text):
        roles.add('status')
    return roles


def _family(table):
    # Retain plausible time partitions; this does not authorize their UNION.
    name = re.sub(r'_[0-9a-f]{8,64}$', '', table['name'].lower())
    name = re.sub(r'\d+', '', name)
    return name, frozenset((c['name'], str(c.get('type', '')).upper()) for c in table['columns'])


def rank_evidence(evidence, question):
    """Protect the best source plus sources needed for uncovered query roles."""
    evidence = deepcopy(evidence)
    roles, words = required_roles(question), _words(question)
    capabilities = {}
    for table in evidence['tables']:
        capabilities[table['name']] = set().union(*(_column_roles(c) for c in table['columns']))

    def score(table):
        caps = capabilities[table['name']]
        text = _text(table['name'])
        matched = sum(_overlap(_text(c['name']) + ' ' + _text(c.get('original')), words) for c in table['columns'])
        # Coverage dominates repeated generic words in a large product catalog.
        return (len(caps & roles) * 20 + min(matched, 10) + _overlap(text, words),
                len(caps & {'time', 'order'}))

    evidence['tables'].sort(key=score, reverse=True)
    protected_tables, protected_columns = set(), set()
    if evidence['tables']:
        primary = evidence['tables'][0]
        protected_tables.add(primary['name'])
        if 'time' in roles:
            protected_tables.update(t['name'] for t in evidence['tables'] if _family(t) == _family(primary))
        missing = roles - capabilities[primary['name']]
        for table in evidence['tables'][1:]:
            covered = capabilities[table['name']] & missing
            if covered:
                protected_tables.add(table['name'])
                missing -= covered
        for table in evidence['tables']:
            if table['name'] not in protected_tables:
                continue
            for c in table['columns']:
                caps = _column_roles(c)
                text = _text(c['name']) + ' ' + _text(c.get('original'))
                if caps & (roles | {'key', 'status'}) or _overlap(text, words):
                    protected_columns.add((table['name'], c['name']))
            # An unfamiliar amount header must not disappear merely because the
            # lexical role dictionary does not recognize it.
            if roles & {'revenue', 'payment', 'quantity', 'cost', 'stock'}:
                for c in table['columns']:
                    dtype = str(c.get('type', '')).upper()
                    if any(t in dtype for t in ('INT', 'DECIMAL', 'NUMERIC', 'FLOAT', 'DOUBLE', 'REAL')):
                        protected_columns.add((table['name'], c['name']))
            if not any(t == table['name'] for t, _ in protected_columns) and table['columns']:
                protected_columns.add((table['name'], table['columns'][0]['name']))
    else:
        missing = roles
    # Prefer README clauses about the requested roles and record structure over
    # unrelated conversion rows with coincidental lexical overlap.
    def policy_score(policy):
        text = _text(policy.get('text'))
        return (_overlap(text, words) + sum(bool(re.search(ROLE_PATTERNS[r], text)) for r in roles if r in ROLE_PATTERNS)
                + 2 * bool(re.search(r'dong hang|hoa don|ngay dat|trang thai|grain', text)))
    evidence['business_policies'].sort(key=policy_score, reverse=True)
    return evidence, protected_tables, protected_columns, missing


def fit_context(evidence, question, as_of_date, system, count_tokens, budget):
    evidence, protected_tables, protected_columns, missing = rank_evidence(evidence, question)
    original_tables = len(evidence['tables'])
    original_columns = sum(len(t['columns']) for t in evidence['tables'])

    def user_text():
        return json.dumps(dict(context=evidence, as_of_date=as_of_date, question=question), ensure_ascii=False, separators=(',', ':'))

    initial_tokens = count_tokens(system, user_text())
    trimmed = False
    while count_tokens(system, user_text()) > budget:
        if not trimmed:
            evidence['context_limits'] = 'Some candidates may be omitted for budget; omission is not evidence of unavailable data.'
            trimmed = True
        if evidence['candidate_joins']:
            evidence['candidate_joins'] = []
        elif evidence['extra_policies']:
            evidence['extra_policies'].pop()
        elif len(evidence['business_policies']) > 2:
            evidence['business_policies'].pop()
        elif evidence['unit_candidates']:
            evidence['unit_candidates'].pop()
        elif evidence['metric_candidates']:
            evidence['metric_candidates'].pop()
        elif evidence['directory']:
            # Cards carry source IDs/names; a full directory is optional discovery.
            evidence['directory'] = []
        else:
            optional = [t for t in evidence['tables'] if t['name'] not in protected_tables]
            if optional:
                evidence['tables'].remove(optional[-1])
                continue
            removable = [(t, c) for t in reversed(evidence['tables']) for c in reversed(t['columns'])
                         if (t['name'], c['name']) not in protected_columns and len(t['columns']) > 1]
            if removable:
                table, column = removable[0]
                table['columns'].remove(column)
            else:
                raise ValueError('essential prompt exceeds input budget; protected source/column evidence cannot be removed')
    if not evidence['tables']:
        raise ValueError('grounding requires at least one schema table card')
    diagnostics = dict(initial_tokens=initial_tokens, trimmed=trimmed,
        protected_tables=sorted(protected_tables), protected_columns=[f'{t}.{c}' for t, c in sorted(protected_columns)],
        uncovered_retrieval_roles=sorted(missing), removed_tables=original_tables-len(evidence['tables']),
        removed_columns=original_columns-sum(len(t['columns']) for t in evidence['tables']))
    return evidence, user_text(), count_tokens(system, user_text()), diagnostics
