"""Evidence and isolated preparation regression; no model/GPU needed."""
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

import duckdb
import pytest

from datamate.context.contracts import BusinessRule, MetricDefinition, SemanticCatalog
from datamate.context.verified_semantics import verified_merge
from datamate.context.semantic_experiment import publish_enrichment, semantic_packets
from datamate.ingestion.contracts import SchemaCatalog, TableMetadata, ColumnMetadata
from datamate.ingestion.ingestion import prepare_business
from datamate.ingestion.ingestion.normalization import is_order_key

SCHEMA = SchemaCatalog(tables=(TableMetadata(name='sales',columns=(ColumnMetadata(name='amount',data_type='DECIMAL(38,2)'),)),))
RULE = BusinessRule(rule_id='r1',text='Ống PVC: 1 bó = 10 cây. Doanh thu tính trên amount.',source='README.md:8',scope='business',precedence=10)
EV = {'rule_id':'r1','quote':RULE.text}
UNIT = {'item_name':'Ống PVC','from_unit':'bó','to_unit':'cây','factor':'10','evidence':EV}
BASE = SemanticCatalog(business_id='shop', metrics=(MetricDefinition(metric_id='revenue',preferred_table='sales',formula_hint='SUM(amount)'),))

def merge(payload,rules=(RULE,)):
    return verified_merge('shop',BASE,payload,SCHEMA,rules)

@pytest.mark.parametrize('factor',['0','-1','NaN','Infinity','100','0.0000000000001'])
def test_invalid_unit_never_published(factor):
    c=merge({'unit_conversions':[{**UNIT,'factor':factor}]})
    assert not c.unit_conversions
    assert c.proposals[0]['status']=='rejected'


def test_evidence_scoped_decimal_conversion():
    c=merge({'unit_conversions':[UNIT]})
    assert c.unit_conversions[0]['factor']=='10'
    assert c.unit_conversions[0]['evidence']['source']=='README.md:8'
    assert not merge({'unit_conversions':[{**UNIT,'item_name':'Other product'}]}).unit_conversions
    assert not merge({'unit_conversions':[{**UNIT,'evidence':{'rule_id':'r1','quote':'invented'}}]}).unit_conversions


def test_conflicting_units_quarantined():
    r2=replace(RULE,rule_id='r2',text='Ống PVC: 1 bó = 12 cây.')
    c=merge({'unit_conversions':[UNIT,{**UNIT,'factor':12,'evidence':{'rule_id':'r2','quote':r2.text}}]},(RULE,r2))
    assert not c.unit_conversions
    assert all(p['status']=='rejected' for p in c.proposals)


@pytest.mark.parametrize('formula',['SUM(missing)','SUM(amount); DROP TABLE sales','(SELECT SUM(amount) FROM sales)','read_csv(\'/etc/passwd\')'])
def test_invalid_formula_rejected(formula):
    c=merge({'metrics':[{'metric_id':'revenue','preferred_table':'sales','required_columns':['amount'],'formula_hint':formula,'evidence':EV}]})
    assert c.metrics==BASE.metrics
    assert c.proposals[0]['status']=='rejected'


def test_metric_cannot_override_baseline_and_absence_is_not_proof():
    c=merge({'metrics':[{'metric_id':'revenue','preferred_table':'sales','required_columns':['amount'],'formula_hint':'SUM(amount)','evidence':EV}],
             'unsupported_capabilities':[{'description':'no category','evidence':EV}]})
    assert c.metrics==BASE.metrics
    assert not c.unsupported_capabilities
    assert all(p['status']=='review_required' for p in c.proposals)


def test_join_remains_candidate():
    c=merge({'suggested_joins':[{'left_table':'sales','left_column':'amount','right_table':'sales','right_column':'amount','evidence':EV}]})
    assert c.suggested_joins[0]['status']=='candidate'
    assert SCHEMA.join_graph==()


def test_stt_is_not_order_identity():
    assert not is_order_key('STT','số thứ tự dòng trong đơn')
    assert is_order_key('STT','mã đơn hàng')
    assert is_order_key('HD')
    assert not is_order_key('ghi_chu','khách STT thường xuyên')


def test_ambiguous_numeric_row_retained_and_cache_hit(tmp_path):
    biz=tmp_path/'shop';biz.mkdir()
    (biz/'sales.csv').write_text('Mã đơn,Tên hàng,Thành tiền\nA,Ống,10\n,,20\nTổng cộng,,30\n',encoding='utf-8')
    a=prepare_business(biz,tmp_path/'out')
    with duckdb.connect(str(a.bundle_dir/'data.duckdb'),read_only=True) as con:
        tbl=con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchone()[0]
        assert con.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]==2
        assert con.execute("SELECT COUNT(*) FROM meta.quality_issues WHERE code='ambiguous_subtotal'").fetchone()[0]==1
    assert prepare_business(biz,tmp_path/'out').cache_hit


def test_enrichment_atomic_catalog_and_source_unchanged(tmp_path):
    biz=tmp_path/'shop';biz.mkdir();(biz/'sales.csv').write_text('Mã đơn,Thành tiền\nA,10\n')
    a=prepare_business(biz,tmp_path/'base')
    original=(a.bundle_dir/'data.duckdb').read_bytes()
    ctx_path=a.bundle_dir/'business_context.json'
    ctx=json.loads(ctx_path.read_text());ctx['rule_catalog']['rules'].append(__import__('dataclasses').asdict(RULE))
    ctx_path.write_text(json.dumps(ctx))
    manifest_path=a.bundle_dir/'source_manifest.json'
    mf=json.loads(manifest_path.read_text());mf['artifact_hashes']['business_context.json']=__import__('hashlib').sha256(ctx_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(mf))
    dest=publish_enrichment(a.bundle_dir,tmp_path/'enriched',[merge({'unit_conversions':[UNIT]}).to_dict()],{'model':'fake'})
    assert (a.bundle_dir/'data.duckdb').read_bytes()==original
    ctx=json.loads((dest/'business_context.json').read_text())
    assert 'unit_conversions' in {t['name'] for t in ctx['schema_catalog']['tables']}
    with duckdb.connect(str(dest/'data.duckdb'),read_only=True) as con:
        assert con.execute('SELECT factor FROM unit_conversions').fetchone()[0]==Decimal('10')
    mf=json.loads((dest/'source_manifest.json').read_text())
    assert mf['cache_key']==dest.name
    for filename,expected in mf['artifact_hashes'].items():
        assert __import__('hashlib').sha256((dest/filename).read_bytes()).hexdigest()==expected
    assert publish_enrichment(a.bundle_dir,tmp_path/'enriched',[merge({'unit_conversions':[UNIT]}).to_dict()],{'model':'fake'})==dest


def test_packets_include_every_rule_without_cutting():
    ctx={'business_id':'x','schema_catalog':{'tables':[{'name':'sales','columns':[{'name':'amount','data_type':'BIGINT'}]}]},
         'rule_catalog':{'rules':[{'rule_id':str(i),'text':'word '*60,'source':'README','scope':'business','precedence':1} for i in range(25)]}}
    packets=semantic_packets(ctx,max_chars=2000)
    assert {r['rule_id'] for p in packets for r in p['rules']}=={str(i) for i in range(25)}


def test_prompt_has_no_business_example_to_copy():
    from datamate.context.semantic_extractor import SEMANTIC_DISCOVERY_SYSTEM_PROMPT
    assert 'Ống PVC' not in SEMANTIC_DISCOVERY_SYSTEM_PROMPT
    assert 'rule_id' in SEMANTIC_DISCOVERY_SYSTEM_PROMPT
    assert 'quote' in SEMANTIC_DISCOVERY_SYSTEM_PROMPT


def test_malformed_evidence_does_not_bypass_checks():
    assert not merge({'unit_conversions':[{**UNIT,'evidence':{'rule_id':[],'quote':RULE.text}}]}).unit_conversions


def test_enrichment_rejects_other_business(tmp_path):
    biz=tmp_path/'shop';biz.mkdir();(biz/'s.csv').write_text('id,value\n1,2\n')
    a=prepare_business(biz,tmp_path/'base')
    with pytest.raises(ValueError,match='another business'):
        publish_enrichment(a.bundle_dir,tmp_path/'enriched',[{'business_id':'foreign'}],{})


def test_rulebook_change_invalidates_preparation(tmp_path):
    biz=tmp_path/'shop';biz.mkdir();(biz/'s.csv').write_text('id,value\n1,2\n')
    rb=tmp_path/'rules.md';rb.write_text('Rule one.')
    first=prepare_business(biz,tmp_path/'out',rulebook=rb)
    assert prepare_business(biz,tmp_path/'out',rulebook=rb).cache_hit
    rb.write_text('Rule two.')
    second=prepare_business(biz,tmp_path/'out',rulebook=rb)
    assert not second.cache_hit and first.cache_key!=second.cache_key


def test_semantic_expectations_are_offline_only():
    from datamate.context.semantic_experiment import compare_unit_expectations
    expected={'business_id':'shop','units':[UNIT]}
    good=compare_unit_expectations([merge({'unit_conversions':[UNIT]}).to_dict()],expected)
    assert good['correct']==1 and good['precision']==1 and good['recall']==1
    assert compare_unit_expectations([BASE.to_dict()],expected)['missing']


def test_shortened_product_scope_is_rejected():
    assert not merge({'unit_conversions':[{**UNIT,'item_name':'Ống'}]}).unit_conversions


def test_budget_reservation_counts_failed_attempts_and_stops(tmp_path):
    from scripts.modal_b02_semantics import reserve_budget
    ledger=tmp_path/'costs.jsonl'
    assert reserve_budget(ledger,{'reserved_usd':1},limit=2)==1
    # An unsuccessful dispatch is intentionally never refunded automatically.
    assert reserve_budget(ledger,{'reserved_usd':1},limit=2)==2
    with pytest.raises(RuntimeError,match='no GPU launched'):
        reserve_budget(ledger,{'reserved_usd':1},limit=2)
    assert len(ledger.read_text().splitlines())==2


def test_semantic_cache_skips_gpu_and_model_change_invalidates(tmp_path,monkeypatch):
    import scripts.modal_b02_semantics as runner
    import subprocess
    monkeypatch.setattr(runner,'ROOT',tmp_path)
    (tmp_path/'requirements-lock.txt').write_text('locked')
    (tmp_path/'src/datamate').mkdir(parents=True)
    (tmp_path/'src/datamate/a.py').write_text('version=1')
    monkeypatch.setattr(subprocess,'check_output',lambda args,**kw: 'geminiveo4ai57\n' if 'profile' in args else 'commit\n')
    identity={'revision':'one'};calls=[]
    monkeypatch.setattr(runner.model_identity,'remote',lambda:dict(identity))
    def gpu(packets):
        calls.append(packets)
        return {'catalogs':[],'model_revision':identity['revision']}
    monkeypatch.setattr(runner.extract,'remote',gpu)
    request=tmp_path/'request.json';request.write_text(json.dumps({'packets':[{}]}))
    output=tmp_path/'output/result.json'
    runner.run_local(str(request),str(output));runner.run_local(str(request),str(output))
    assert len(calls)==1
    identity['revision']='two'
    runner.run_local(str(request),str(output))
    assert len(calls)==2
    ledger=tmp_path/'artifacts/b01_b02/cost_ledger.jsonl'
    assert len(ledger.read_text().splitlines())==2
