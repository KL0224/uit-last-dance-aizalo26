"""Read-only prebuilt bundle index and bounded evidence retrieval."""
from __future__ import annotations
import hashlib
import json
import unicodedata
from pathlib import Path
from .calendar_resolver import CalendarResolver


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if unicodedata.category(c) != 'Mn').replace('đ', 'd')

class GroundingContextIndex:
    def __init__(self, bundle: str | Path, *, rulebook: str | Path, calendar: str | Path):
        self.bundle = Path(bundle).resolve()
        raw = (self.bundle / 'business_context.json').read_bytes()
        self.payload = json.loads(raw)
        self.business_id = self.payload['business_id']
        self.calendar = CalendarResolver(calendar)
        self.rulebook = Path(rulebook).read_text(encoding='utf-8')
        self.rulebook_hash = hashlib.sha256(self.rulebook.encode()).hexdigest()
        self.fingerprint = hashlib.sha256(raw + self.rulebook_hash.encode() + self.calendar.fingerprint.encode()).hexdigest()
        self.tables = {t['name']: t for t in self.payload['schema_catalog']['tables']}
        self.columns = {f"{t['name']}.{c['name']}": c for t in self.tables.values() for c in t['columns']}
        self.policies = {}
        self.core_policy_ids = set()
        core_section = True
        for line, text in enumerate(self.rulebook.splitlines(), 1):
            if text.startswith('## '):
                heading = normalized(text)
                core_section = any(term in heading for term in ('thoi gian', 'doanh thu', 'don hang'))
            if text.strip():
                ident = f'P{line}'
                self.policies[ident] = dict(id=ident, text=text, source=dict(path=str(rulebook), line=line, sha256=self.rulebook_hash), applies_to=[])
                if core_section and not text.startswith(('#', '|---', '| Luật', '| Cách nói')):
                    self.core_policy_ids.add(ident)
        for i, rule in enumerate(self.payload.get('rule_catalog', {}).get('rules', [])):
            ident = f'B{i}'
            self.policies[ident] = dict(id=ident, text=rule.get('text', ''), source=rule, applies_to=[])
        self.conversions = {f'U{i}': value for i,value in enumerate(self.payload.get('semantic_catalog', {}).get('unit_conversions', []))}
        self.database = self.bundle / 'data.duckdb'
        if not self.database.is_file():
            raise FileNotFoundError(self.database)
        manifest = self.bundle / 'source_manifest.json'
        identity = str(self.database.stat().st_size) + ':' + str(self.database.stat().st_mtime_ns)
        self.fingerprint = hashlib.sha256(self.fingerprint.encode() + identity.encode() + (manifest.read_bytes() if manifest.exists() else b'')).hexdigest()
        self._verify_schema()

    def _verify_schema(self):
        import duckdb
        with duckdb.connect(str(self.database), read_only=True) as conn:
            actual = {}
            for table, column in conn.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='main'").fetchall():
                actual.setdefault(table, set()).add(column)
            for name, table in self.tables.items():
                if not {c['name'] for c in table['columns']} <= actual.get(name, set()):
                    raise ValueError(f'physical schema mismatch: {name}')

    def prompt_context(self, question):
        words = set(normalized(question).split())
        def score(item):
            return sum(w in normalized(json.dumps(item, ensure_ascii=False)) for w in words if len(w) > 1)
        tables = sorted(self.tables.values(), key=score, reverse=True)
        global_policies = [p for k,p in self.policies.items() if k.startswith('P')]
        core = [p for p in global_policies if p['id'] in self.core_policy_ids]
        optional = sorted((p for p in global_policies if p not in core), key=score, reverse=True)[:8]
        return dict(
            directory=list(self.tables),
            tables=[dict(name=t['name'], grain=t.get('grain'), columns=[dict(name=c['name'], type=c.get('data_type', c.get('dtype', c.get('sql_type'))), original=c.get('provenance')) for c in t['columns']]) for t in tables],
            policies=[dict(id=p['id'], text=p['text']) for p in core],
            extra_policies=[dict(id=p['id'], text=p['text']) for p in optional],
            business_policies=[dict(id=p['id'], text=p['text']) for p in sorted((p for k,p in self.policies.items() if k.startswith('B')), key=score, reverse=True)[:12]],
            metric_candidates=[dict(metric_id=m.get('metric_id'), preferred_table=m.get('preferred_table'), required_columns=m.get('required_columns', []), formula_hint=m.get('formula_hint'), trust='candidate_not_semantically_verified', warning='Missing formula/date_role; choose binding from source policies, not registry preference' if not m.get('formula_hint') or not m.get('date_role') else 'Validate against policies') for m in self.payload.get('semantic_catalog', {}).get('metrics', [])],
            unit_candidates=[dict(id=k, **v) for k,v in sorted(self.conversions.items(), key=lambda pair: score(pair[1]), reverse=True)[:12]],
            candidate_joins=self.payload['schema_catalog'].get('join_graph', []),
        )

    def planner_context(self):
        # Runtime view only: never mutate the producer bundle.
        payload = json.loads(json.dumps(self.payload))
        payload.setdefault('rule_catalog', {}).setdefault('rules', []).extend(dict(rule_id=p['id'], text=p['text'], source=str(p['source']), scope='global', status='descriptive', precedence=0) for k,p in self.policies.items() if k.startswith('P'))
        payload['grounding_global_policies'] = self.rulebook
        months = {}
        for d, key in self.calendar.rows:
            months.setdefault((key[0], key[1], key[3]), []).append((d, key[2]))
        payload['grounding_calendar'] = dict(sha256=self.calendar.fingerprint,
            coverage=[self.calendar.rows[0][0].isoformat(), self.calendar.rows[-1][0].isoformat()],
            months=[dict(lunar_year=y, lunar_month=m, leap=leap, first_observed_date=rows[0][0].isoformat(),
                         first_observed_day=rows[0][1], last_observed_day=rows[-1][1])
                    for (y,m,leap),rows in months.items()])
        return payload
