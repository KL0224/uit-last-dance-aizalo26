"""CPU-only preparation, reviewed SQL/golden checks and optional B02 enrichment.

No LLM-generated SQL, no Grounding, no Text-to-SQL planner, no submission.
"""
from __future__ import annotations
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time

import duckdb
from datamate.ingestion.ingestion import prepare_business
from datamate.context.semantic_experiment import semantic_packets, publish_enrichment, digest


def run(split: Path, output: Path, businesses: list[str], cases: Path | None = None):
    output.mkdir(parents=True, exist_ok=True)
    bundles, baseline = {}, {}
    start = time.perf_counter()
    for biz in businesses:
        print(f'Preparing B01/B02: {biz}', flush=True)
        artifact = prepare_business(split/'data'/biz, output/'bundles', rulebook=split/'rulebook.md', calendar=split/'calendar.csv')
        bundles[biz] = artifact.to_dict()
        baseline[biz] = json.loads((artifact.bundle_dir/'business_context.json').read_text())
    results = []
    if cases:
        questions = {x['id']:x for x in map(json.loads,(split/'questions.jsonl').read_text().splitlines())}
        # Golden answers are only loaded here, never into extraction requests.
        golden = {x['id']:x for x in map(json.loads,(split/'answers.jsonl').read_text().splitlines())}
        for case in json.loads(cases.read_text()):
            q = questions[case['question_id']]
            biz = q['business_id']
            if biz not in bundles: continue
            with duckdb.connect(bundles[biz]['database'], read_only=True) as con:
                rows = con.execute(case['sql']).fetchall()
            expected = golden[q['id']]
            value = rows[0][0] if len(rows)==1 and len(rows[0])==1 else rows
            matched = (expected['type']=='number' and value is not None and
                       Decimal(str(value))==Decimal(str(expected['answer'])))
            results.append({'question_id': q['id'], 'business_id': biz, 'question': q['question'],
                'sql': case['sql'], 'rationale': case['rationale'], 'expected': expected,
                'actual': str(value) if isinstance(value,Decimal) else value, 'match': matched})
    report = {'scope':'B01/B02 only; reviewed SQL, not system PA', 'bundles':bundles,
              'elapsed_seconds':time.perf_counter()-start, 'golden_cases':results,
              'evaluation_inputs': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in ([cases,split/'questions.jsonl',split/'answers.jsonl'] if cases else [])},
              'matched':sum(x['match'] for x in results), 'evaluated':len(results)}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    return baseline, report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--split-dir',type=Path,default=Path('data/train'))
    p.add_argument('--output-dir',type=Path,default=Path('artifacts/b01_b02'))
    p.add_argument('--businesses',default='biz_123,biz_128,biz_105')
    p.add_argument('--cases',type=Path)
    p.add_argument('--modal-result',type=Path)
    args=p.parse_args()
    contexts, report=run(args.split_dir,args.output_dir,args.businesses.split(','),args.cases)
    if args.modal_result:
        result=json.loads(args.modal_result.read_text())
        for biz,ctx in contexts.items():
            catalogs=[c for c in result['catalogs'] if c['business_id']==biz]
            if catalogs:
                dest=publish_enrichment(Path(report['bundles'][biz]['bundle_dir']),args.output_dir/'enriched',catalogs,{**result['manifest'], 'model_revision':result.get('model_revision'), 'modal_call_id':result.get('modal_call_id')})
                print('Enriched:',dest)
    packets=[packet for ctx in contexts.values() for packet in semantic_packets(ctx)]
    manifest={'scope':'B02 only', 'sources':{b:d['cache_key'] for b,d in report['bundles'].items()},
              'context_hashes':{b:digest(c) for b,c in contexts.items()}, 'golden_in_prompt':False}
    (args.output_dir/'requests_all.json').write_text(json.dumps({'manifest':manifest,'packets':packets},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'evaluated':report['evaluated'],'matched':report['matched'],'semantic_packets':len(packets)}))

if __name__=='__main__':main()
