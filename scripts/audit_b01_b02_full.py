"""CPU-only full B01/B02 audit and baseline differences, retaining all failures."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import traceback

import duckdb

if __package__:
    from scripts.audit_prepared_bundles import audit, quote
else:
    from audit_prepared_bundles import audit, quote


def read(path):
    return json.loads(path.read_text())


def numeric_totals(connection, table):
    columns = connection.execute("SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='main' AND table_name=?", [table]).fetchall()
    names = [n for n,t in columns if n != '__dm_row_id' and (t.startswith('DECIMAL') or t in ('BIGINT','INTEGER','DOUBLE','FLOAT'))]
    if not names:
        return {}
    values = connection.execute('SELECT '+','.join('SUM('+quote(n)+')' for n in names)+' FROM '+quote(table)).fetchone()
    return {n:str(v) if v is not None else None for n,v in zip(names,values)}


def run(report_path: Path, baseline_path: Path, output: Path, cases_path: Path, split: Path):
    output.mkdir(parents=True,exist_ok=True)
    benchmark=read(report_path); old=read(baseline_path)
    baseline={r['business_id']:r for r in old['results']}
    findings=[];differences=[];audited=[];files=Counter();issues=Counter(); examples=[];semantic=[];status_issue_tables=[]
    expected_businesses={p.name for p in (split/'data').glob('biz_*') if p.is_dir()}
    reported_businesses={r['business_id'] for r in benchmark['results']}
    if expected_businesses!=reported_businesses:
        findings.append({'category':'business_coverage_mismatch','missing':sorted(expected_businesses-reported_businesses),'unexpected':sorted(reported_businesses-expected_businesses)})
    for record in sorted(benchmark['results'],key=lambda r:r['business_id']):
        biz=record['business_id']
        if 'error' in record.get('cold',{}) or 'error' in record.get('warm',{}):
            findings.append({'business_id':biz,'category':'preparation_failed','detail':record});continue
        folder=Path(record['warm']['bundle_dir'])
        manifest=read(folder/'source_manifest.json');ctx=read(folder/'business_context.json')
        normalization=read(folder/'normalization_report.json')
        known={t['name']:{c['name'] for c in t['columns']} for t in ctx['schema_catalog']['tables']}
        rule_states=Counter(r['status'] for r in ctx['rule_catalog']['rules'])
        metrics=ctx.get('semantic_catalog',{}).get('metrics',[])
        for metric in metrics:
            table=metric.get('preferred_table')
            missing=set(metric.get('required_columns',[]))-known.get(table,set())
            if table not in known or missing:
                findings.append({'business_id':biz,'category':'semantic_invalid_binding','metric_id':metric['metric_id'],'table':table,'missing_columns':sorted(missing)})
        semantic.append({'business_id':biz,'rule_status':dict(rule_states),'metric_count':len(metrics),
                         'validated_join_count':sum(e['status']=='validated' for e in ctx['schema_catalog']['join_graph'])})
        one=output/'checks'/(biz+'.json');one.parent.mkdir(parents=True,exist_ok=True)
        one.write_text(json.dumps({**benchmark,'results':[record]}))
        try:
            result=audit(one)
            audited.extend(result['results'])
            issues.update(result['issue_counts']);files.update(result['data_files'])
        except Exception as exc:
            findings.append({'business_id':biz,'category':'integrity_audit_failed','error':str(exc),'traceback':traceback.format_exc()})
        for filename,expected in manifest.get('artifact_hashes',{}).items():
            if hashlib.sha256((folder/filename).read_bytes()).hexdigest()!=expected:
                findings.append({'business_id':biz,'category':'artifact_hash_mismatch','file':filename})
        for rel,expected in manifest['inputs']['sources'].items():
            if hashlib.sha256((split/'data'/biz/rel).read_bytes()).hexdigest()!=expected:
                findings.append({'business_id':biz,'category':'source_hash_mismatch','file':rel})
        old_folder=Path(baseline[biz]['warm']['bundle_dir'])
        old_ctx=read(old_folder/'business_context.json')
        old_tables={t['name']:t for t in old_ctx['schema_catalog']['tables']}
        with duckdb.connect(str(folder/'data.duckdb'),read_only=True) as new_db, duckdb.connect(str(old_folder/'data.duckdb'),read_only=True) as old_db:
            new_db.execute("SET memory_limit='512MB'");old_db.execute("SET memory_limit='512MB'")
            for table in ctx['schema_catalog']['tables']:
                name=table['name'];prev=old_tables.get(name)
                if not prev:
                    differences.append({'business_id':biz,'table':name,'category':'added_table','row_count':table['row_count']});continue
                entry={'business_id':biz,'table':name}
                if prev['row_count']!=table['row_count']:
                    entry['rows']={'before':prev['row_count'],'after':table['row_count']}
                previous={c['name']:c['data_type'] for c in prev['columns']};current={c['name']:c['data_type'] for c in table['columns']}
                if previous!=current:entry['types']={'before':previous,'after':current}
                before=numeric_totals(old_db,name);after=numeric_totals(new_db,name)
                totals={c:{'before':before.get(c),'after':after.get(c)} for c in before.keys()|after.keys() if before.get(c)!=after.get(c)}
                if totals:entry['numeric_totals']=totals
                if len(entry)>2:differences.append(entry)
            names={t['name'] for t in ctx['schema_catalog']['tables']}
            for name in old_tables.keys()-names:
                differences.append({'business_id':biz,'table':name,'category':'removed_table'})
            status_issue_tables.extend({'business_id':biz,'table':t,'column':col,'count':n} for t,col,n in new_db.execute(
                "SELECT m.normalized_table,q.column_name,COUNT(*) FROM meta.quality_issues q JOIN meta.source_mapping m USING(source_id) WHERE q.code='unmapped_status' GROUP BY 1,2").fetchall())
            examples.extend({'business_id':biz,'source_id':s,'row':r,'column':c,'code':code,'rule':rule} for s,r,c,code,rule in new_db.execute(
                "SELECT source_id, source_row, column_name, code, rule FROM meta.quality_issues ORDER BY code,source_id,source_row LIMIT 20").fetchall())
        print(biz,'audited/diffed',flush=True)
    questions={q['id']:q for q in map(json.loads,(split/'questions.jsonl').read_text().splitlines())}
    golden={q['id']:q for q in map(json.loads,(split/'answers.jsonl').read_text().splitlines())}
    bundles={r['business_id']:Path(r['warm']['bundle_dir']) for r in benchmark['results'] if 'warm' in r and 'error' not in r['warm']}
    checks=[]
    from decimal import Decimal
    for case in read(cases_path):
        q=questions[case['question_id']];biz=q['business_id']
        check={'question_id':q['id'],'business_id':biz,'question':q['question'],'sql':case['sql'],'category':case.get('category','unspecified'),'rationale':case['rationale'],'expected':golden[q['id']]}
        try:
            with duckdb.connect(str(bundles[biz]/'data.duckdb'),read_only=True) as con:
                prechecks=[{**pre,'actual':con.execute(pre['sql']).fetchone()[0]} for pre in case.get('prechecks',[])]
                check['prechecks']=prechecks
                if any(p['actual']!=p['expected'] for p in prechecks):
                    raise ValueError('reviewed SQL precondition failed; investigate join identity')
                rows=con.execute(case['sql']).fetchall()
            value=rows[0][0] if len(rows)==1 and len(rows[0])==1 else rows
            check.update(actual=str(value),match=golden[q['id']]['type'] in ('number','percent') and value is not None and Decimal(str(value))==Decimal(str(golden[q['id']]['answer'])))
        except Exception as exc:check.update(match=False,error=str(exc))
        checks.append(check)
    result={'scope':'B01/B02 CPU only; no inference pipeline, no GPU, no PA','business_count':len(benchmark['results']),
            'integrity_passed':len(audited),'findings':findings,'data_files':dict(files),'issues':dict(issues),
            'source_unchanged':benchmark.get('source_unchanged'),'baseline_report':str(baseline_path),
            'differences':differences,'semantic':semantic,'status_issue_tables':status_issue_tables,'issue_examples':examples,'businesses':audited,'golden_checks':checks,
            'golden_evaluated':len(checks),'golden_matched':sum(c['match'] for c in checks)}
    (output/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k in ('business_count','integrity_passed','data_files','golden_evaluated','golden_matched','source_unchanged')},ensure_ascii=False))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--cases',type=Path,required=True)
    p.add_argument('--split',type=Path,default=Path('data/train'))
    a=p.parse_args();result=run(a.report,a.baseline,a.output,a.cases,a.split)
    if result['findings'] or not result['source_unchanged'] or result['golden_matched']!=result['golden_evaluated']:
        raise SystemExit(1)
