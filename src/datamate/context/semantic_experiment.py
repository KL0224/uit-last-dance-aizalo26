"""Isolated B01/B02 experiments: no grounding, planner generation or answer pipeline."""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import uuid

import duckdb

from datamate.ingestion.contracts import SchemaCatalog, TableMetadata, ColumnMetadata
from .contracts import BusinessRule
from .semantic_extractor import LLMSemanticExtractor

EXPERIMENT_VERSION = 'b01-b02-evidence-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def semantic_packets(context: dict, max_chars: int = 6000) -> list[dict]:
    """Whole-record chunks, with no mid-column or mid-rule slicing.

    Cross products retain every table/rule association; duplicates are later
    checked by evidence and unit key. Oversized records fail explicitly.
    """
    tables = context['schema_catalog']['tables']
    rules = context['rule_catalog']['rules']
    def chunks(records, budget):
        result, group, size = [], [], 0
        for record in records:
            n = len(json.dumps(record, ensure_ascii=False))
            if n > budget:
                raise ValueError('record exceeds semantic context budget; split source explicitly')
            if group and size + n > budget:
                result.append(group); group, size = [], 0
            group.append(record); size += n
        if group: result.append(group)
        return result or [[]]
    compact = [{'name': t['name'], 'columns': [{'name': c['name'], 'data_type': c['data_type']}
                for c in t['columns'] if not c['name'].startswith('__dm_')]} for t in tables]
    relevant = sorted((r for r in rules if r.get('status') != 'invalid'),
                      key=lambda r: (r.get('scope') != 'business', r['rule_id']))
    compact_rules = [{k: r[k] for k in ('rule_id', 'text', 'source', 'scope', 'precedence')} for r in relevant]
    return [{'business_id': context['business_id'], 'tables': ts, 'rules': rs}
            for ts in chunks(compact, max_chars // 2)
            for rs in chunks(compact_rules, max_chars // 2)]


def extract_packet(packet, chat_fn):
    schema = SchemaCatalog(tables=tuple(TableMetadata(name=t['name'], columns=tuple(
        ColumnMetadata(**c) for c in t['columns'])) for t in packet['tables']))
    rules = tuple(BusinessRule(**r) for r in packet['rules'])
    return LLMSemanticExtractor(chat_fn=chat_fn).extract_semantic_catalog(
        packet['business_id'], schema, rules).to_dict()


def publish_enrichment(bundle: Path, output: Path, catalogs: list[dict], manifest: dict) -> Path:
    """Clone immutable baseline, update DB/catalog together, then atomic publish."""
    source_manifest = json.loads((bundle / 'source_manifest.json').read_text())
    if source_manifest.get('status') != 'ready':
        raise ValueError('baseline bundle is not ready')
    for name, expected_hash in source_manifest['artifact_hashes'].items():
        if hashlib.sha256((bundle/name).read_bytes()).hexdigest() != expected_hash:
            raise ValueError(f'baseline artifact hash mismatch: {name}')
    baseline = json.loads((bundle / 'business_context.json').read_text())
    from .verified_semantics import verified_merge
    from .contracts import SemanticCatalog
    source_rules = tuple(BusinessRule(**r) for r in baseline['rule_catalog']['rules'])
    checked_catalogs = []
    for catalog in catalogs:
        if catalog.get('business_id') != baseline['business_id']:
            raise ValueError('semantic catalog belongs to another business')
        checked = verified_merge(baseline['business_id'], SemanticCatalog(business_id=baseline['business_id']),
                    {'unit_conversions': list(catalog.get('unit_conversions', []))}, SchemaCatalog(tables=()), source_rules)
        checked_catalogs.append({**catalog, 'unit_conversions': checked.to_dict()['unit_conversions']})
    catalogs = checked_catalogs
    key = digest({'version': EXPERIMENT_VERSION, 'baseline': baseline,
                  'catalogs': catalogs, 'manifest': manifest})
    target = output / baseline['business_id'] / key
    if target.exists():
        return target
    work = target.with_name('.' + key + '-' + uuid.uuid4().hex)
    work.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(bundle, work)
    try:
        units, proposals, suggestions = {}, [], []
        for c in catalogs:
            proposals.extend(c.get('proposals', []))
            suggestions.extend(c.get('suggested_joins', []))
            for u in c.get('unit_conversions', []):
                k = tuple(u[x].casefold().strip() for x in ('item_name', 'from_unit', 'to_unit'))
                units.setdefault(k, []).append(u)
        verified = [v[0] for v in units.values() if len({Decimal(x['factor']) for x in v}) == 1]
        conflicts = [list(k) for k,v in units.items() if len({Decimal(x['factor']) for x in v}) > 1]
        sem = baseline.setdefault('semantic_catalog', {})
        sem.update(proposals=proposals, unit_conversions=verified)
        # Do not promote suggested joins into B01's graph or capability proofs.
        sem['suggested_joins'] = list({digest(j): j for j in suggestions if j.get('status') == 'candidate'}.values())
        with duckdb.connect(str(work / 'data.duckdb')) as con:
            if con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='main' AND table_name='unit_conversions'").fetchone()[0]:
                raise ValueError('unit_conversions collides with source table; baseline unchanged')
            if verified:
                bidirectional_units = []
                seen_pairs = set()
                for u in verified:
                    item = str(u.get("item_name", "")).strip()
                    f_u = str(u.get("from_unit", "")).strip()
                    t_u = str(u.get("to_unit", "")).strip()
                    factor = Decimal(str(u.get("factor", 1.0)))
                    if not (item and f_u and t_u and factor > 0):
                        continue
                    pair_fwd = (item.casefold(), f_u.casefold(), t_u.casefold())
                    if pair_fwd not in seen_pairs:
                        seen_pairs.add(pair_fwd)
                        bidirectional_units.append([item, f_u, t_u, factor])
                    pair_rev = (item.casefold(), t_u.casefold(), f_u.casefold())
                    if pair_rev not in seen_pairs:
                        seen_pairs.add(pair_rev)
                        bidirectional_units.append([item, t_u, f_u, Decimal(round(1.0 / float(factor), 12))])

                con.execute('CREATE TABLE main.unit_conversions (item_name VARCHAR, from_unit VARCHAR, to_unit VARCHAR, factor DECIMAL(38,12))')
                con.executemany('INSERT INTO main.unit_conversions VALUES (?,?,?,?)', bidirectional_units)
                baseline['schema_catalog']['tables'].append({
                    'name': 'unit_conversions', 'columns': [
                        {'name': n, 'data_type': t, 'nullable': False} for n,t in
                        [('item_name','VARCHAR'),('from_unit','VARCHAR'),('to_unit','VARCHAR'),('factor','DECIMAL(38,12)')]],
                    'row_count': len(bidirectional_units), 'provenance': 'B02 verified document equations (bidirectional)'})
                baseline.setdefault('data_profiling', {})['unit_conversions'] = {
                    'row_count': len(bidirectional_units), 'sample_rows': [{k:u[k] for k in ('item_name','from_unit','to_unit','factor')} for u in verified[:5]], 'origin': 'B02 evidence-checked enrichment'}
            if verified:
                con.execute('CREATE TABLE IF NOT EXISTS meta.semantic_evidence (item_name VARCHAR, evidence_json VARCHAR)')
                con.executemany('INSERT INTO meta.semantic_evidence VALUES (?,?)',
                                [[u['item_name'], json.dumps(u['evidence'], ensure_ascii=False)] for u in verified])
        foundation_path = work / 'foundation_metadata.json'
        foundation = json.loads(foundation_path.read_text())
        if verified:
            foundation['tables'].append(baseline['schema_catalog']['tables'][-1])
            foundation.setdefault('data_profiling', {})['unit_conversions'] = baseline['data_profiling']['unit_conversions']
        for name, data in [('foundation_metadata.json', foundation), ('business_context.json', baseline),
                           ('semantic_experiment.json', {**manifest, 'version': EXPERIMENT_VERSION,
                             'baseline_bundle': str(bundle.resolve()), 'unit_conflicts': conflicts,
                             'verified_units': len(verified), 'proposals': len(proposals)})]:
            (work / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str)+'\n')
        normalization_path = work / 'normalization_report.json'
        normalization = json.loads(normalization_path.read_text())
        normalization['semantic_enrichment_rows'] = len(verified)
        if verified:
            normalization['table_count'] += 1
        normalization_path.write_text(json.dumps(normalization, ensure_ascii=False, indent=2)+'\n')
        source_path = work / 'source_manifest.json'
        source_manifest = json.loads(source_path.read_text())
        source_manifest['cache_key'] = key
        source_manifest['inputs']['semantic_enrichment'] = {'version': EXPERIMENT_VERSION, 'catalog_hash': digest(catalogs), 'manifest': manifest}
        source_manifest['artifact_hashes'] = {name: hashlib.sha256((work/name).read_bytes()).hexdigest()
            for name in ('data.duckdb','foundation_metadata.json','business_context.json','normalization_report.json','semantic_experiment.json')}
        source_path.write_text(json.dumps(source_manifest, ensure_ascii=False, indent=2)+'\n')
        work.rename(target)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return target


def compare_unit_expectations(catalogs: list[dict], expected: dict) -> dict:
    """Offline semantic evaluation only; expectations must never enter LLM input."""
    def key(u):
        return tuple(str(u[k]).strip().casefold() for k in ('item_name', 'from_unit', 'to_unit')) + (str(Decimal(str(u['factor'])).normalize()),)
    want = {key(u) for u in expected['units']}
    got = {key(u) for c in catalogs if c['business_id'] == expected['business_id'] for u in c.get('unit_conversions', [])}
    return {'business_id':expected['business_id'],'expected':len(want),'accepted':len(got),
            'correct':len(want & got),'missing':sorted(want-got),'unexpected':sorted(got-want),
            'precision':len(want & got)/len(got) if got else None,
            'recall':len(want & got)/len(want) if want else None}
