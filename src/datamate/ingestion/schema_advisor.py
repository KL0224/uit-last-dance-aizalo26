"""Optional LLM schema advice, checked against immutable sources and full SQL profiles.

Advice is a sidecar for review. It never mutates prepared tables, parser roles,
existing join edges or relationship attestations.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import duckdb

from .contracts import JoinEdge
from .ingestion.profiling import DuckDBProfileProvider

VERSION = '1.0.0'
ROLES = ('order_id', 'customer_id', 'product_id', 'order_date', 'payment_date',
         'unit_price', 'line_amount', 'order_total', 'quantity', 'status', 'entity_name', 'unknown')
SYSTEM_PROMPT = '''Bạn hỗ trợ B01 đọc schema và tài liệu nguồn. Chỉ đề xuất vai trò cột và equi-JOIN có bằng chứng.
Không viết SQL. Không sửa dữ liệu. Không tự suy doanh thu, đơn vị quy đổi hoặc xác nhận JOIN.
Tên bảng/cột phải khớp schema, kể cả tên SQL đã chuẩn hóa. Dùng tên gốc/provenance để đối chiếu tài liệu.
Mỗi đề xuất có evidence {source_id, line, quote}: ID nguồn, số dòng và trích nguyên văn chính xác từ dòng đó.
Chỉ trích dòng thực sự giải thích cột hoặc quan hệ. Không coi tên giống nhau hoặc giá trị trùng là chứng cứ ngữ nghĩa.
JOIN nhiều cột: left_columns và right_columns cùng độ dài, thứ tự tương ứng; không bỏ thành phần khóa.
Nếu không có đủ bằng chứng thì trả mảng rỗng. Vai trò chỉ là gợi ý cần review, không là override parser.
Output JSON {column_roles: [{table,column,role,evidence}],join_candidates: [{left_table,right_table,left_columns,right_columns,evidence}]}.
'''


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def _bundle(bundle: Path):
    manifest = json.loads((bundle/'source_manifest.json').read_text())
    if manifest.get('status') != 'ready':
        raise ValueError('B01 advice requires a ready bundle')
    for name in ('data.duckdb', 'business_context.json'):
        if _hash(bundle/name) != manifest['artifact_hashes'][name]:
            raise ValueError(f'baseline artifact changed: {name}')
    return manifest, json.loads((bundle/'business_context.json').read_text())


def build_request(bundle: Path, documents: list[Path], tables: list[str] | None = None) -> dict:
    """Build bounded metadata-only input; no rows, questions or answers are sent."""
    manifest, context = _bundle(bundle)
    available = {t['name']: t for t in context['schema_catalog']['tables'] if t['name'] != 'calendar'}
    chosen = list(available) if tables is None else tables
    if not chosen or len(chosen) > 4 or len(set(chosen)) != len(chosen) or set(chosen)-available.keys():
        raise ValueError('select 1..4 distinct existing business tables per advisory request')
    sources = []
    dependencies = manifest['inputs']['documents']
    for path in documents:
        path = path.resolve(strict=True)
        if str(path) not in dependencies or _hash(path) != dependencies[str(path)]:
            raise ValueError('advisory document must match a hashed bundle input')
        lines = [{'line': i, 'text': text} for i,text in enumerate(path.read_text(encoding='utf-8').splitlines(),1) if text.strip()]
        sid = hashlib.sha256((str(path)+dependencies[str(path)]).encode()).hexdigest()[:20]
        sources.append({'source_id':sid,'name':path.name,'path':str(path),'sha256':dependencies[str(path)],'lines':lines})
    if not sources or len({s['source_id'] for s in sources}) != len(sources):
        raise ValueError('unique source documents required')
    compact = [{'name':n,'grain':available[n].get('grain'),'row_count':available[n]['row_count'],
                'columns':[{k:c.get(k) for k in ('name','data_type','provenance')} for c in available[n]['columns'] if not c['name'].startswith('__dm_')]} for n in chosen]
    request = {'version':VERSION,'business_id':context['business_id'],
               'binding':{n:manifest['artifact_hashes'][n] for n in ('data.duckdb','business_context.json')},
               'coverage':{'selected_tables':chosen,'available_tables':len(available)},
               'tables':compact,'documents':sources,'prompt_sha256':hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()}
    if len(prompt(request)) > 14000:
        raise ValueError('advisory input too large; select fewer tables/documents (no silent truncation)')
    return request


def prompt(request: dict) -> str:
    """Only metadata and numbered source text enter the LLM prompt."""
    return json.dumps({'business_id':request['business_id'],'tables':request['tables'],
                       'sources':[{k:v for k,v in d.items() if k in ('source_id','name','lines')} for d in request['documents']]},ensure_ascii=False)


def validate_response(bundle: Path, request: dict, response: dict) -> dict:
    manifest, context = _bundle(bundle)
    if context['business_id'] != request['business_id'] or any(manifest['artifact_hashes'][n] != v for n,v in request['binding'].items()):
        raise ValueError('stale advice request or business mismatch')
    # Rebuild the full request from actual sources, rather than trusting supplied lines/schema.
    fresh = build_request(bundle,[Path(d['path']) for d in request['documents']],request['coverage']['selected_tables'])
    if fresh != request:
        raise ValueError('request does not match current metadata, documents or advisor version')
    known = {t['name']:{c['name'] for c in t['columns']} for t in request['tables']}
    source = {d['source_id']:d for d in request['documents']}
    out = {'version':VERSION,'business_id':request['business_id'],'binding':request['binding'],
           'coverage':request['coverage'],'column_roles':[],'join_candidates':[],'rejected':[],
           'policy':'review_only; no data/role overrides or validated JOIN promotion'}
    if not isinstance(response,dict):
        raise ValueError('LLM response must be a JSON object')
    if any(not isinstance(response.get(k,[]),list) or len(response.get(k,[]))>12 for k in ('column_roles','join_candidates')):
        raise ValueError('at most 12 proposals per category')

    def evidence(raw):
        ev=raw.get('evidence')
        if not isinstance(ev,dict) or not isinstance(ev.get('source_id'),str) or type(ev.get('line')) is not int:
            raise ValueError('missing source evidence')
        doc=source.get(ev['source_id'])
        line=next((l['text'] for l in doc['lines'] if l['line']==ev['line']),None) if doc else None
        quote=ev.get('quote')
        if not isinstance(quote,str) or not quote.strip() or line is None or quote not in line:
            raise ValueError('quote/line does not match source')
        return {**ev,'source_sha256':doc['sha256'],'source':doc['name']}

    seen=set()
    with duckdb.connect(str(bundle/'data.duckdb'),read_only=True) as connection:
        connection.execute("SET memory_limit='512MB'");connection.execute('SET threads=2')
        provider=DuckDBProfileProvider(connection,context['business_id'])
        existing=context['schema_catalog']['join_graph']
        for category in ('column_roles','join_candidates'):
            for raw in response.get(category,[]):
                try:
                    if not isinstance(raw,dict):raise ValueError('proposal must be an object')
                    ev=evidence(raw)
                    if category=='column_roles':
                        t,c,role=raw.get('table'),raw.get('column'),raw.get('role')
                        if t not in known or c not in known[t] or role not in ROLES:raise ValueError('unknown column or role')
                        identity=(category,t,c,role)
                        if identity in seen:continue
                        seen.add(identity)
                        out[category].append({**raw,'evidence':ev,'status':'review_required'})
                    else:
                        lt,rt=raw.get('left_table'),raw.get('right_table')
                        left,right=raw.get('left_columns'),raw.get('right_columns')
                        if lt==rt or lt not in known or rt not in known:raise ValueError('unknown or self JOIN endpoint')
                        if (not isinstance(left,list) or not isinstance(right,list) or not 1<=len(left)==len(right)<=4
                            or not all(isinstance(c,str) for c in left+right)
                            or len(set(left))!=len(left) or len(set(right))!=len(right)
                            or set(left)-known[lt] or set(right)-known[rt]):raise ValueError('invalid composite key columns')
                        pairs=tuple(zip(left,right))
                        forward=(lt,rt,tuple(sorted(pairs)));reverse=(rt,lt,tuple(sorted((r,l) for l,r in pairs)))
                        identity=(category,min(forward,reverse))
                        if identity in seen:continue
                        seen.add(identity)
                        edge=JoinEdge(lt,left[0],rt,right[0],'unknown','uncertain',0.0,
                                      ('LLM proposal; cited text requires semantic review',),additional_key_pairs=pairs[1:])
                        checked=provider.check_join(edge)
                        prior=any((e['left_table'],e['right_table'],tuple(sorted([(e['left_column'],e['right_column']),*map(tuple,e.get('additional_key_pairs',[]))]))) in (forward,reverse) for e in existing)
                        out[category].append({'edge':asdict(checked),'evidence':ev,'already_in_catalog':prior,'review_status':'pending'})
                except (ValueError,TypeError,duckdb.Error) as exc:
                    out['rejected'].append({'category':category,'proposal':raw,'reason':str(exc)})
    # Conflicting roles are retained as conflicting proposals, never applied.
    for item in out['column_roles']:
        roles={x['role'] for x in out['column_roles'] if (x['table'],x['column'])==(item['table'],item['column'])}
        if len(roles)>1:item['status']='conflicting'
    return out


def advise(bundle: Path, documents: list[Path], chat_fn: Callable[[str,str],str], tables: list[str] | None = None) -> dict:
    request=build_request(bundle,documents,tables)
    try:
        response=json.loads(chat_fn(SYSTEM_PROMPT,prompt(request)))
    except Exception as exc:
        return {'business_id':request['business_id'],'status':'llm_failed','error':str(exc),'binding':request['binding']}
    return validate_response(bundle,request,response)


def export_pending_review(bundle: Path, request: dict, advice: dict, destination: Path) -> dict:
    """Bridge SQL names to the existing reviewed-relationships input, pending only.

    Ambiguous physical mappings and many-to-many shapes need manual modeling;
    these are listed as blocked, rather than choosing a source or inventing grain.
    """
    import os
    manifest, context = _bundle(bundle)
    if advice.get('binding') != request['binding'] or context['business_id'] != advice['business_id']:
        raise ValueError('advice scope/binding mismatch')
    if destination.resolve().is_relative_to(bundle.resolve()) or any(destination.resolve()==Path(d['path']).resolve() for d in request['documents']):
        raise ValueError('review artifact must be outside baseline bundle and source documents')
    documents = {d['source_id']: d for d in request['documents']}
    relationships, blocked = [], []
    with duckdb.connect(str(bundle/'data.duckdb'),read_only=True) as con:
        def endpoint(table, columns):
            sources=con.execute('SELECT path,sheet FROM meta.source_mapping WHERE normalized_table=?',[table]).fetchall()
            if len(sources)!=1:raise ValueError('physical source mapping is ambiguous; manual review required')
            originals=[]
            for column in columns:
                rows=con.execute('SELECT original_name FROM meta.column_mapping WHERE table_name=? AND column_name=?',[table,column]).fetchall()
                if len(rows)!=1:raise ValueError('original column mapping is ambiguous')
                originals.append(rows[0][0])
            return {'file':sources[0][0],'table':sources[0][1],'columns':originals}
        for candidate in advice['join_candidates']:
            edge=candidate['edge']
            try:
                if edge['cardinality'] not in ('one_to_one','many_to_one','one_to_many'):
                    raise ValueError('many-to-many/unknown grain requires manual modeling')
                pairs=[(edge['left_column'],edge['right_column']),*edge['additional_key_pairs']]
                ev=candidate['evidence'];doc=documents[ev['source_id']]
                if _hash(Path(doc['path']))!=doc['sha256']:raise ValueError('source document changed')
                relationships.append({'id':'llm_'+hashlib.sha256(json.dumps([edge['left_table'],edge['right_table'],pairs]).encode()).hexdigest()[:16],
                    'left':endpoint(edge['left_table'],[p[0] for p in pairs]),
                    'right':endpoint(edge['right_table'],[p[1] for p in pairs]),'cardinality':edge['cardinality'],
                    'review':{'status':'pending','reviewed_by':'unreviewed',
                              'evidence':{'path':os.path.relpath(doc['path'],destination.resolve().parent),
                                          'sha256':doc['sha256'],'quote':ev['quote']}}})
            except ValueError as exc:
                blocked.append({'edge':edge,'reason':str(exc)})
    payload={'version':'1.0','business_id':advice['business_id'],'relationships':relationships}
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    return {'manifest':str(destination),'pending':len(relationships),'blocked':blocked}
