"""LLM advice must never edit data or grant semantic JOIN validation."""
import json
from pathlib import Path

import duckdb
import pytest

from datamate.ingestion.ingestion import prepare_business
from datamate.ingestion.schema_advisor import build_request, validate_response, advise, prompt


@pytest.fixture
def prepared(tmp_path):
    biz=tmp_path/'shop';biz.mkdir()
    (biz/'orders.csv').write_text('Store,OrderID,CustomerID\nA,01,C1\nA,02,C2\nB,01,C1\n')
    (biz/'lines.csv').write_text('Store,OrderID,Qty\nA,01,1\nA,02,2\nB,01,3\nA,01,4\n')
    doc=biz/'README.md';doc.write_text('Store and OrderID together join orders to lines.\nOrderID is the order identifier.\n')
    a=prepare_business(biz,tmp_path/'out');ctx=json.loads((a.bundle_dir/'business_context.json').read_text())
    names={t['name'].split('_')[0]:t['name'] for t in ctx['schema_catalog']['tables']}
    request=build_request(a.bundle_dir,[doc],[names['orders'],names['lines']])
    ev={'source_id':request['documents'][0]['source_id'],'line':1,'quote':'Store and OrderID together join orders to lines.'}
    return a.bundle_dir,doc,names,request,ev


def test_composite_sql_check_keeps_uncertain_and_preserves_bundle(prepared):
    bundle,doc,n,req,ev=prepared
    before={p.name:p.read_bytes() for p in bundle.iterdir() if p.is_file()}
    result=validate_response(bundle,req,{'join_candidates':[{'left_table':n['lines'],'right_table':n['orders'],
                'left_columns':['store','order_id'],'right_columns':['store','order_id'],'evidence':ev,'status':'validated'}]})
    edge=result['join_candidates'][0]['edge']
    assert edge['status']=='uncertain' and edge['relationship_evidence'] is None
    assert edge['statistics']['left_coverage']==1
    assert edge['statistics']['observed_cardinality']=='many_to_one'
    assert edge['additional_key_pairs']==(('order_id','order_id'),)
    assert before=={p.name:p.read_bytes() for p in bundle.iterdir() if p.is_file()}


@pytest.mark.parametrize('change',[
    {'left_columns':['missing']}, {'left_columns':['store','store'],'right_columns':['store','order_id']},
    {'left_columns':['store','order_id'],'right_columns':['store']}, {'right_table':'not_real'},
    {'left_columns':['__dm_row_id'],'right_columns':['__dm_row_id']},
])
def test_invalid_join_rejected(prepared,change):
    bundle,doc,n,req,ev=prepared
    raw={'left_table':n['lines'],'right_table':n['orders'],'left_columns':['store'],'right_columns':['store'],'evidence':ev}
    result=validate_response(bundle,req,{'join_candidates':[{**raw,**change}]})
    assert not result['join_candidates'] and result['rejected']


def test_fabricated_quote_or_line_rejected(prepared):
    bundle,doc,n,req,ev=prepared
    result=validate_response(bundle,req,{'column_roles':[{'table':n['orders'],'column':'order_id','role':'order_id',
                   'evidence':{**ev,'line':100}}]})
    assert not result['column_roles'] and result['rejected']


def test_role_conflict_never_becomes_override(prepared):
    bundle,doc,n,req,ev=prepared
    result=validate_response(bundle,req,{'column_roles':[
        {'table':n['orders'],'column':'order_id','role':role,'evidence':ev} for role in ('order_id','customer_id')]})
    assert {p['status'] for p in result['column_roles']}=={'conflicting'}


def test_changed_source_or_request_rejected(prepared):
    bundle,doc,n,req,ev=prepared
    altered=json.loads(json.dumps(req));altered['documents'][0]['lines'][0]['text']='forged source'
    with pytest.raises(ValueError):validate_response(bundle,altered,{})
    doc.write_text('modified source')
    with pytest.raises(ValueError):validate_response(bundle,req,{})


def test_no_raw_rows_in_prompt_and_bad_json_is_reported(prepared):
    bundle,doc,n,req,ev=prepared
    text=prompt(req)
    assert 'C1' not in text and 'C2' not in text
    assert 'profile_rows' not in text and str(doc) not in text
    result=advise(bundle,[doc],lambda *args:'{truncated',req['coverage']['selected_tables'])
    assert result['status']=='llm_failed'


def test_duplicate_reverse_joins_deduplicated(prepared):
    bundle,doc,n,req,ev=prepared
    raw={'left_table':n['lines'],'right_table':n['orders'],'left_columns':['store','order_id'],'right_columns':['store','order_id'],'evidence':ev}
    reverse={**raw,'left_table':raw['right_table'],'right_table':raw['left_table']}
    result=validate_response(bundle,req,{'join_candidates':[raw,reverse]})
    assert len(result['join_candidates'])==1


def test_pending_manifest_bridges_existing_review_workflow(prepared,tmp_path):
    from datamate.ingestion.schema_advisor import export_pending_review
    from datamate.ingestion.ingestion.relationships import ReviewedRelationships
    bundle,doc,n,req,ev=prepared
    advice=validate_response(bundle,req,{'join_candidates':[{'left_table':n['lines'],'right_table':n['orders'],
             'left_columns':['store','order_id'],'right_columns':['store','order_id'],'evidence':ev}]})
    dest=tmp_path/'review/relationships.json'
    result=export_pending_review(bundle,req,advice,dest)
    payload=json.loads(dest.read_text())
    assert result['pending']==1
    assert payload['relationships'][0]['review']['status']=='pending'
    assert payload['relationships'][0]['left']['columns']==['Store','OrderID']
    ReviewedRelationships(dest,'shop')  # Existing strict schema + source hash/quote validator.


def test_scalar_overlap_does_not_hide_many_to_many(prepared):
    bundle,doc,n,req,ev=prepared
    result=validate_response(bundle,req,{'join_candidates':[{'left_table':n['lines'],'right_table':n['orders'],
                   'left_columns':['store'],'right_columns':['store'],'evidence':ev}]})
    edge=result['join_candidates'][0]['edge']
    assert edge['statistics']['observed_cardinality']=='many_to_many'
    assert edge['fanout_warning'] and edge['status']=='uncertain'


def test_pending_roundtrip_never_auto_validates(prepared,tmp_path):
    from datamate.ingestion.schema_advisor import export_pending_review
    bundle,doc,n,req,ev=prepared
    advice=validate_response(bundle,req,{'join_candidates':[{'left_table':n['lines'],'right_table':n['orders'],
             'left_columns':['store','order_id'],'right_columns':['store','order_id'],'evidence':ev}]})
    dest=tmp_path/'pending.json';export_pending_review(bundle,req,advice,dest)
    a=prepare_business(doc.parent,tmp_path/'with_pending',relationships=dest)
    context=json.loads((a.bundle_dir/'business_context.json').read_text())
    composite=[e for e in context['schema_catalog']['join_graph'] if e.get('additional_key_pairs')]
    assert composite and all(e['status']!='validated' for e in composite)


def test_backend_failure_is_explicit(prepared):
    bundle,doc,n,req,ev=prepared
    def fail(*args):raise OSError('backend unavailable')
    assert advise(bundle,[doc],fail,req['coverage']['selected_tables'])['status']=='llm_failed'


def test_export_cannot_overwrite_baseline(prepared):
    from datamate.ingestion.schema_advisor import export_pending_review
    bundle,doc,n,req,ev=prepared
    advice=validate_response(bundle,req,{})
    with pytest.raises(ValueError,match='outside baseline'):
        export_pending_review(bundle,req,advice,bundle/'business_context.json')
