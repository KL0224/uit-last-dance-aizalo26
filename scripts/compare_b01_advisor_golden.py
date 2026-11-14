"""Compare baseline and review-only B01 advice against reviewed SQL and full gold inventory.

No model calls, generated SQL, preparation, downstream pipeline or auto approval.
Unknown/uncovered answers are never scored as correct or incorrect.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import duckdb

from datamate.ingestion.schema_advisor import validate_response


def read(path):
    return json.loads(path.read_text())


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def evaluate(bundle, case, expected):
    try:
        with duckdb.connect(str(bundle / 'data.duckdb'), read_only=True) as con:
            con.execute("SET memory_limit='512MB'")
            con.execute('SET threads=2')
            for pre in case.get('prechecks', []):
                if con.execute(pre['sql']).fetchone()[0] != pre['expected']:
                    raise ValueError('reviewed SQL precondition failed')
            rows = con.execute(case['sql']).fetchall()
        if len(rows) != 1 or len(rows[0]) != 1:
            raise ValueError('this reviewed evaluator supports scalar numeric results only')
        value = rows[0][0]
        if expected['type'] not in ('number', 'percent'):
            raise ValueError('unsupported golden type for reviewed numeric SQL')
        return {'actual': str(value), 'match': value is not None and
                Decimal(str(value)) == Decimal(str(expected['answer']))}
    except Exception as exc:
        return {'match': False, 'error': str(exc)}


def run(report, split, cases_path, response_path, output):
    questions = [json.loads(line) for line in (split / 'questions.jsonl').read_text().splitlines()]
    answers = [json.loads(line) for line in (split / 'answers.jsonl').read_text().splitlines()]
    qmap = {q['id']: q for q in questions}
    amap = {a['id']: a for a in answers}
    if len(qmap) != len(questions) or len(amap) != len(answers) or qmap.keys() != amap.keys():
        raise ValueError('question/answer identities are duplicated or incomplete')
    bundles = {r['business_id']: Path(r['warm']['bundle_dir']) for r in read(report)['results']}
    if {q['business_id'] for q in questions} - bundles.keys():
        raise ValueError('missing business bundles')
    cases = read(cases_path)
    cids = {c['question_id'] for c in cases}
    if len(cids) != len(cases) or cids - qmap.keys():
        raise ValueError('reviewed SQL identities duplicated or missing in golden')
    before = {}
    source_hashes = {}
    for biz, bundle in bundles.items():
        manifest = read(bundle / 'source_manifest.json')
        dependencies = {str((split / 'data' / biz / name).resolve()): value
                        for name, value in manifest['inputs']['sources'].items()}
        dependencies.update(manifest['inputs']['documents'])
        for path, expected in dependencies.items():
            if digest(Path(path)) != expected:
                raise ValueError(f'source dependency hash mismatch: {path}')
            source_hashes[path] = expected
        for name, expected in manifest['artifact_hashes'].items():
            path = bundle / name
            actual = digest(path)
            if actual != expected:
                raise ValueError(f'baseline artifact hash mismatch: {path}')
            before[str(path)] = actual
    baseline = {c['question_id']: evaluate(bundles[qmap[c['question_id']]['business_id']], c,
                                          amap[c['question_id']]) for c in cases}
    saved = read(response_path)
    biz = saved['request']['business_id']
    advice = validate_response(bundles[biz], saved['request'], saved['response'])
    # Advisor never applies proposals. The second arm deliberately uses the same
    # published bundle, measuring preservation rather than hypothetical accuracy.
    upgraded = {c['question_id']: evaluate(bundles[qmap[c['question_id']]['business_id']], c,
                                          amap[c['question_id']]) for c in cases}
    results = [{'question_id': q['id'], 'business_id': q['business_id'], 'type': amap[q['id']]['type'],
                'status': 'evaluated_reviewed_sql' if q['id'] in cids else 'not_evaluated_no_reviewed_sql',
                **({'baseline': baseline[q['id']], 'with_advisor': upgraded[q['id']]} if q['id'] in cids else {})}
               for q in questions]
    unchanged = all(digest(Path(path)) == old for path, old in before.items())
    sources_unchanged = all(digest(Path(path)) == old for path, old in source_hashes.items())
    rows = []
    for business_id in sorted(bundles):
        group = [r for r in results if r['business_id'] == business_id]
        evaluated = [r for r in group if 'baseline' in r]
        rows.append({'business_id': business_id, 'golden_total': len(group), 'evaluated': len(evaluated),
                     'baseline_matches': sum(r['baseline']['match'] for r in evaluated),
                     'with_advisor_matches': sum(r['with_advisor']['match'] for r in evaluated),
                     'not_evaluated': len(group) - len(evaluated)})
    result = {'scope': 'B01/B02; reviewed SQL comparison and full golden inventory, not end-to-end PA',
              'inputs': {str(p): digest(p) for p in (report, cases_path, response_path,
                         split / 'questions.jsonl', split / 'answers.jsonl')},
              'golden_total': len(questions), 'golden_types': dict(Counter(a['type'] for a in answers)),
              'evaluated': len(cases), 'not_evaluated': len(questions) - len(cases),
              'baseline_matches': sum(r['match'] for r in baseline.values()),
              'with_advisor_matches': sum(r['match'] for r in upgraded.values()),
              'changed_results': sum(baseline[qid] != upgraded[qid] for qid in cids),
              'unchanged_bundles': len(bundles) if unchanged else None,
              'source_dependencies_checked': len(source_hashes), 'sources_unchanged': sources_unchanged,
              'artifact_hashes_before': before,
              'advisor': {'business_id': biz, 'column_roles': len(advice['column_roles']),
                          'joins': len(advice['join_candidates']), 'rejected': len(advice['rejected']),
                          'new_joins': sum(not j['already_in_catalog'] for j in advice['join_candidates']),
                          'applied': 0, 'gpu_calls': 0},
              'businesses': rows, 'questions': results}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('golden_total', 'evaluated', 'not_evaluated',
          'baseline_matches', 'with_advisor_matches', 'changed_results', 'unchanged_bundles', 'advisor')}, ensure_ascii=False))
    if not unchanged or not sources_unchanged or result['changed_results'] or result['baseline_matches'] != len(cases):
        raise SystemExit('verification failed; inspect report')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--split', type=Path, default=Path('data/train'))
    parser.add_argument('--cases', type=Path, default=Path('examples/b01_b02/expanded_golden_checks.json'))
    parser.add_argument('--response', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.report, args.split, args.cases, args.response, args.output)
