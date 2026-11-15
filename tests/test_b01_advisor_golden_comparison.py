"""Coverage gaps must remain unknown, not become accuracy or LLM gains."""
import json

import duckdb
import pytest

from datamate.ingestion.ingestion import prepare_business
from datamate.ingestion.schema_advisor import build_request
from scripts.compare_b01_advisor_golden import evaluate, run


def test_comparison_preserves_uncovered_golden_as_unknown(tmp_path):
    split = tmp_path / 'train'
    biz = split / 'data' / 'biz_test'
    biz.mkdir(parents=True)
    (biz / 'sales.csv').write_text('Code,Amount\nA,10\nB,20\n')
    doc = biz / 'README.md'
    doc.write_text('Each row is one sale.\n')
    artifact = prepare_business(biz, tmp_path / 'bundles')
    context = json.loads((artifact.bundle_dir / 'business_context.json').read_text())
    table = context['schema_catalog']['tables'][0]['name']
    request = build_request(artifact.bundle_dir, [doc], [table])
    report = tmp_path / 'report.json'
    report.write_text(json.dumps({'results': [{'business_id': 'biz_test', 'warm': artifact.to_dict()}]}))
    (split / 'questions.jsonl').write_text('\n'.join(json.dumps({'id': qid, 'business_id': 'biz_test'}) for qid in ['q1', 'q2']))
    (split / 'answers.jsonl').write_text('\n'.join(json.dumps(a) for a in [
        {'id': 'q1', 'type': 'number', 'answer': 2},
        {'id': 'q2', 'type': 'unanswerable', 'answer': None}]))
    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([{'question_id': 'q1', 'sql': f'SELECT COUNT(*) FROM "{table}"'}]))
    response = tmp_path / 'response.json'
    response.write_text(json.dumps({'request': request, 'response': {}}))
    output = tmp_path / 'comparison.json'
    result = run(report, split, cases, response, output)
    assert result['golden_total'] == 2 and result['evaluated'] == 1 and result['not_evaluated'] == 1
    assert result['baseline_matches'] == result['with_advisor_matches'] == 1
    assert result['changed_results'] == 0 and result['unchanged_bundles'] == 1
    assert result['advisor']['applied'] == 0 and result['advisor']['gpu_calls'] == 0
    unknown = result['questions'][1]
    assert unknown['status'] == 'not_evaluated_no_reviewed_sql' and 'baseline' not in unknown
    with (split / 'answers.jsonl').open('a') as stream:
        stream.write('\n' + json.dumps({'id': 'q1', 'type': 'number', 'answer': 2}))
    with pytest.raises(ValueError, match='duplicated or incomplete'):
        run(report, split, cases, response, output)


def test_sql_precheck_and_null_are_not_success(tmp_path):
    with duckdb.connect(str(tmp_path / 'data.duckdb')) as con:
        con.execute('CREATE TABLE sales (amount INTEGER)')
        con.execute('INSERT INTO sales VALUES (10), (20)')
    expected = {'type': 'number', 'answer': 30}
    case = {'sql': 'SELECT SUM(amount) FROM sales',
            'prechecks': [{'sql': 'SELECT COUNT(*) FROM sales', 'expected': 3}]}
    assert 'precondition failed' in evaluate(tmp_path, case, expected)['error']
    assert not evaluate(tmp_path, {'sql': 'SELECT NULL'}, {'type': 'number', 'answer': 0})['match']
    assert not evaluate(tmp_path, {'sql': 'SELECT * FROM missing'}, expected)['match']
