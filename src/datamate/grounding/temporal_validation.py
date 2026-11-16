"""Cross-check declared temporal intent against materialized, scoped windows.

This validates representation completeness, not natural-language understanding.
No question regexes, guessed dates or model repair calls are used.
"""
from collections import defaultdict


def check_temporal_completeness(proposal, constraints, unresolved):
    problems = []
    affects = [m.id for m in proposal.measures]
    def issue(code, message, refs=affects):
        problems.append(dict(code=code, raw_text=message, affects=list(refs)))

    intent = proposal.temporal_intent
    if intent == 'unknown':
        issue('TEMPORAL_INTENT_UNRESOLVED', 'Whether this request needs one period or a comparison has not been established.')
    if intent == 'none' and proposal.time:
        issue('TEMPORAL_INTENT_CONFLICT', 'Time constraints contradict temporal_intent=none.')
    if intent in ('single_period', 'compare_periods') and not constraints:
        issue('MISSING_TEMPORAL_WINDOW', 'No usable window was materialized for the declared temporal intent.')
    if intent == 'single_period' and any(c.get('label') == 'comparison' for c in constraints):
        issue('TEMPORAL_INTENT_CONFLICT', 'Comparison windows contradict single_period intent.')

    # A comparison between different measures can legitimately share one period.
    if intent == 'compare_measures':
        measures = {m.id: m for m in proposal.measures}
        comparisons = [m for m in measures.values() if m.operator in ('percent_change', 'subtract', 'divide')]
        valid = any(len(m.operands) == 2 and len(set(m.operands)) == 2 and
                    all(ref in measures for ref in m.operands) for m in comparisons)
        if not valid:
            issue('MISSING_COMPARISON_OPERANDS', 'Measure comparison needs two distinct, bound measure operands.')

    needs_pair = intent == 'compare_periods' or (
        proposal.operation in ('percent_change', 'comparison') and intent != 'compare_measures')
    needs_pair = needs_pair or any(t.comparison is not None for t in proposal.time)
    if needs_pair:
        groups = defaultdict(list)
        for c in constraints:
            groups[(c['column'], c['date_role'], tuple(sorted(c['applies_to'])))].append(c)
        if not groups:
            issue('MISSING_COMPARISON_WINDOW', 'Period comparison requires primary and comparison windows in the same scope.')
        linked = set()
        # Explicit operands may intentionally have different time/source scopes.
        for m in proposal.measures:
            if m.operator not in ('percent_change', 'subtract', 'divide') or len(m.operands) != 2:
                continue
            a, b = m.operands
            primary = [c for c in constraints if c.get('label') == 'primary' and a in c['applies_to']]
            comparison = [c for c in constraints if c.get('label') == 'comparison' and b in c['applies_to']]
            if primary and comparison:
                linked.update(c['id'] for c in primary + comparison)
        for (column, date_role, scope), windows in groups.items():
            primary = [c for c in windows if c.get('label') == 'primary']
            comparison = [c for c in windows if c.get('label') == 'comparison']
            # Unrelated dates on another source/measure cannot satisfy this pair.
            if (not primary or not comparison) and not all(c['id'] in linked for c in windows):
                issue('MISSING_COMPARISON_WINDOW', f'Unpaired period on {column} ({date_role}); both primary and comparison are required.', scope)
    temporal_errors = [p for p in unresolved + problems if any(term in p['code'] for term in ('TEMPORAL', 'COMPARISON', 'PERIOD_EXTENT'))]
    status = 'incomplete' if temporal_errors else 'complete'
    return dict(completeness_status=status, intent=intent, constraints=constraints), problems
