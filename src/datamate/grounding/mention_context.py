"""Small temporal-policy context; extraction never receives a database plan."""
import json
from .context_index import normalized


def fit_mention_context(index, question, as_of_date, system, count_tokens, budget):
    policies = []
    in_time_section = False
    for line in index.rulebook.splitlines():
        if line.startswith('## '):
            in_time_section = 'thoi gian' in normalized(line)
        if line.strip() and (in_time_section or '**Hôm nay**' in line):
            policies.append(line)
    # README rules can override general calendar semantics, but are evidence only.
    optional = [p['text'] for ident, p in index.policies.items() if ident.startswith('B')
                and any(word in normalized(p['text']) for word in ('thoi gian', 'lich am', 'tet', 'ca sang', 'ca chieu'))]
    evidence = dict(temporal_policies=policies, business_time_notes=optional[:8])

    def user_text():
        return json.dumps(dict(context=evidence, as_of_date=as_of_date, question=question),
                          ensure_ascii=False, separators=(',', ':'))

    initial = count_tokens(system, user_text())
    trimmed = False
    while count_tokens(system, user_text()) > budget:
        if not evidence['business_time_notes']:
            raise ValueError('essential prompt exceeds input budget; temporal policies and question cannot be removed')
        evidence['business_time_notes'].pop()
        trimmed = True
    return evidence, user_text(), count_tokens(system, user_text()), dict(initial_tokens=initial, trimmed=trimmed)
