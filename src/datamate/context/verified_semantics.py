"""Evidence checks for optional B02 LLM proposals; never grants join validation."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation
import re
from typing import Any

import sqlglot
from sqlglot import exp

from .contracts import BusinessRule, SemanticCatalog
from datamate.ingestion.contracts import SchemaCatalog


def verified_merge(business_id: str, base: SemanticCatalog, payload: dict[str, Any],
                   schema: SchemaCatalog, rules: tuple[BusinessRule, ...]) -> SemanticCatalog:
    """Only source-backed, structurally valid additions enter executable metadata.

    Source matching proves provenance, not the truth of a metric interpretation:
    metric suggestions remain review-required. Unit equations have an additional
    deterministic arithmetic check. Missing capabilities never become proofs.
    """
    known = {t.name: {c.name for c in t.columns} for t in schema.tables}
    rule_index = {r.rule_id: r for r in rules if r.status != 'invalid'}
    proposals: list[dict[str, Any]] = []
    joins = list(base.suggested_joins)
    units: list[dict[str, Any]] = []

    def evidence(raw):
        ev = raw.get('evidence')
        if not isinstance(ev, dict):
            return None
        rid = ev.get('rule_id')
        rule = rule_index.get(rid) if isinstance(rid, str) else None
        quote = ev.get('quote')
        if rule is None or not isinstance(quote, str) or not quote.strip():
            return None
        if ' '.join(quote.split()) not in ' '.join(rule.text.split()):
            return None
        return {'rule_id': rule.rule_id, 'source': rule.source, 'quote': quote}

    for kind in ('metrics', 'suggested_joins', 'unit_conversions', 'unsupported_capabilities'):
        entries = payload.get(kind, [])
        if not isinstance(entries, list):
            continue
        for value in entries:
            raw = value if isinstance(value, dict) else {'description': str(value)}
            ev = evidence(raw)
            status, reason = 'rejected', 'missing_or_invalid_source_evidence'
            if kind == 'metrics' and ev:
                table = raw.get('preferred_table')
                cols = raw.get('required_columns')
                formula = raw.get('formula_hint')
                valid = table in known and isinstance(cols, list) and bool(cols) and set(cols) <= known[table]
                try:
                    nodes = sqlglot.parse(str(formula), read='duckdb')
                    node = nodes[0] if len(nodes) == 1 else None
                    valid = valid and node is not None and not any(
                        isinstance(n, (exp.Query, exp.DDL, exp.DML, exp.Command, exp.Subquery))
                        for n in node.walk()
                    ) and all(c.name in known[table] and (not c.table or c.table == table)
                              for c in node.find_all(exp.Column))
                    allowed_functions = {'SUM', 'AVG', 'MIN', 'MAX', 'COUNT', 'ABS', 'ROUND', 'COALESCE', 'NULLIF', 'CAST', 'TRY_CAST', 'CASE', 'IF'}
                    valid = valid and all(n.sql_name().upper() in allowed_functions for n in node.find_all(exp.Func))
                except Exception:
                    valid = False
                if valid:
                    status, reason = 'review_required', 'source_and_expression_checked; semantic_binding_requires_review'
                else:
                    reason = 'invalid_columns_or_formula'
            elif kind == 'suggested_joins' and ev:
                lt, rt = raw.get('left_table'), raw.get('right_table')
                if (lt in known and rt in known and raw.get('left_column') in known[lt]
                        and raw.get('right_column') in known[rt]):
                    status, reason = 'candidate', 'requires_existing_B01_relationship_verification'
                    joins.append({**raw, 'status': 'candidate', 'evidence': ev})
                else:
                    reason = 'unknown_join_endpoint'
            elif kind == 'unit_conversions' and ev:
                try:
                    factor = Decimal(str(raw.get('factor')))
                    src, dst = raw.get('from_unit'), raw.get('to_unit')
                    item = raw.get('item_name')
                    if not all(isinstance(x, str) and x.strip() for x in (src, dst, item)):
                        raise ValueError('missing item/unit')
                    # Require the actual equation and product scope in the same cited text.
                    pattern = (r'(?<![\d.,])1\s*' + re.escape(src) + r'\s*=\s*'
                               r'(\d+(?:[.,]\d+)?)\s*' + re.escape(dst) + r'(?!\w)')
                    match = re.search(pattern, ev['quote'], re.IGNORECASE)
                    if (not factor.is_finite() or factor <= 0 or not match
                            or Decimal(match.group(1).replace(',', '.')) != factor
                            or ev['quote'].split(':', 1)[0].strip().lstrip('- ').strip('*` ').casefold() != item.strip().casefold()
                            or max(0, -factor.as_tuple().exponent) > 12
                            or len(str(int(factor))) > 26):
                        raise ValueError('equation or scope mismatch')
                    units.append({**raw, 'factor': str(factor), 'evidence': ev, 'status': 'source_verified'})
                    status, reason = 'source_verified', 'explicit_scoped_equation'
                except (InvalidOperation, ValueError, TypeError):
                    reason = 'invalid_unit_equation_or_scope'
            elif kind == 'unsupported_capabilities' and ev:
                status, reason = 'review_required', 'LLM_absence_claim_is_not_missing_evidence_proof'
            proposals.append({'kind': kind, 'status': status, 'reason': reason, 'proposal': raw, 'evidence': ev})

    # Conflicting equations are all quarantined, never resolved by model confidence.
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for unit in units:
        groups.setdefault(tuple(unit[k].strip().casefold() for k in ('item_name', 'from_unit', 'to_unit')), []).append(unit)
    clean_units = []
    for group in groups.values():
        if len({Decimal(u['factor']) for u in group}) == 1:
            clean_units.append(group[0])
        else:
            for p in proposals:
                if (p['kind'] == 'unit_conversions' and tuple(str(p['proposal'].get(k, '')).strip().casefold()
                        for k in ('item_name', 'from_unit', 'to_unit')) ==
                        tuple(group[0][k].strip().casefold() for k in ('item_name', 'from_unit', 'to_unit'))):
                    p.update(status='rejected', reason='conflicting_unit_equations')
    return replace(base, business_id=business_id, suggested_joins=tuple(joins),
                   unit_conversions=tuple(clean_units), proposals=tuple(proposals))
