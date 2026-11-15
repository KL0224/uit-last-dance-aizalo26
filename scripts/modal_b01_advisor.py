"""Optional 3B schema-advisor pilot; no B02, no 9B, no full pipeline."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import modal
image=(modal.Image.debian_slim(python_version='3.12')
       .pip_install_from_requirements(str(ROOT/'requirements-lock.txt'))
       .add_local_dir(str(ROOT/'src'),'/workspace/src'))
volume=modal.Volume.from_name('datamate-b0-volume',create_if_missing=False)

app=modal.App('datamate-b01-advisor',image=image)

@app.function(cpu=0.125,memory=256,timeout=60,volumes={'/vol':volume},retries=0)
def model_identity():
    path=Path('/vol/models/Qwen--Qwen2.5-3B-Instruct')
    if not (path/'config.json').is_file():raise ValueError('3B cache missing; no GPU')
    metadata=path/'.cache/huggingface/download'
    return {'model':'Qwen/Qwen2.5-3B-Instruct','config_hash':hashlib.sha256((path/'config.json').read_bytes()).hexdigest(),
            'revision':{p.name:p.read_text().splitlines()[:2] for p in metadata.glob('*.metadata')},
            'weights':{p.name:[p.stat().st_size,p.stat().st_mtime_ns] for p in path.glob('*.safetensors')}}

@app.function(gpu='A100',cpu=2,memory=16384,timeout=900,max_containers=1,
              scaledown_window=2,volumes={'/vol':volume},retries=0)
def extract(request):
    sys.path.insert(0,'/workspace/src')
    from datamate.ingestion.schema_advisor import SYSTEM_PROMPT, ROLES, prompt
    from vllm import LLM, SamplingParams
    from vllm.sampling_params import StructuredOutputsParams
    started=time.time()
    path=Path('/vol/models/Qwen--Qwen2.5-3B-Instruct')
    if not (path/'config.json').is_file():raise RuntimeError('3B cache missing')
    model=LLM(model=str(path),max_model_len=8192,dtype='bfloat16',gpu_memory_utilization=0.65,
              max_num_seqs=1,generation_config='vllm')
    source_ids=[d['source_id'] for d in request['documents']]
    source_lines=[line for d in request['documents'] for line in d['lines']]
    table_names=[t['name'] for t in request['tables']]
    column_names=sorted({c['name'] for t in request['tables'] for c in t['columns']})
    ev={'type':'object','properties':{'source_id':{'type':'string','enum':source_ids},'line':{'type':'integer','enum':sorted({l['line'] for l in source_lines})},'quote':{'type':'string','enum':list(dict.fromkeys(l['text'] for l in source_lines))}},'required':['source_id','line','quote'],'additionalProperties':False}
    role={'type':'object','properties':{'table':{'type':'string','enum':table_names},'column':{'type':'string','enum':column_names},'role':{'type':'string','enum':list(ROLES)},'evidence':ev},'required':['table','column','role','evidence'],'additionalProperties':False}
    join={'type':'object','properties':{'left_table':{'type':'string','enum':table_names},'right_table':{'type':'string','enum':table_names},'left_columns':{'type':'array','items':{'type':'string','enum':column_names},'minItems':1,'maxItems':4},'right_columns':{'type':'array','items':{'type':'string','enum':column_names},'minItems':1,'maxItems':4},'evidence':ev},'required':['left_table','right_table','left_columns','right_columns','evidence'],'additionalProperties':False}
    schema={'type':'object','properties':{'column_roles':{'type':'array','items':role,'maxItems':4},'join_candidates':{'type':'array','items':join,'maxItems':2}},'required':['column_roles','join_candidates'],'additionalProperties':False}
    messages=[{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':prompt(request)}]
    tokens=model.get_tokenizer().apply_chat_template(messages,tokenize=True,add_generation_prompt=True)
    if len(tokens)+2048>8192:raise ValueError('input exceeds token budget; no truncation')
    result=model.chat(messages,SamplingParams(max_tokens=2048,temperature=0,seed=42,
                structured_outputs=StructuredOutputsParams(json=schema)),use_tqdm=False)[0]
    completion=result.outputs[0]
    if completion.finish_reason=='length':raise ValueError('LLM output truncated; no partial advice accepted')
    return {'response':json.loads(completion.text),'raw_text':completion.text,'elapsed_seconds':time.time()-started,
            'prompt_tokens':len(result.prompt_token_ids or []),'completion_tokens':len(completion.token_ids),
            'modal_call_id':modal.current_function_call_id()}

@app.local_entrypoint()
def main(request: str,output: str):
    from scripts.modal_b02_semantics import reserve_budget
    profile=subprocess.check_output([sys.executable,'-m','modal','profile','current'],text=True).strip()
    if profile!='geminiveo4ai57':raise ValueError('unexpected Modal profile; no GPU dispatched')
    req=json.loads(Path(request).read_text());dest=Path(output);dest.parent.mkdir(parents=True,exist_ok=True)
    identity=model_identity.remote()  # CPU only
    manifest={'task':'B01 schema advice only','git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'request_hash':hashlib.sha256(Path(request).read_bytes()).hexdigest(),'model_identity':identity,
              'runner_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'requirements_hash':hashlib.sha256((ROOT/'requirements-lock.txt').read_bytes()).hexdigest(),
              'code_hash':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src/datamate').rglob('*.py'))}}
    cache_key=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    cache=ROOT/'artifacts/b01_b02/semantic_cache'/('b01-'+cache_key+'.json')
    if cache.is_file():dest.write_text(cache.read_text());print('B01 advice cache hit; no GPU');return
    reserved=reserve_budget(ROOT/'artifacts/b01_b02/cost_ledger.jsonl',{'reserved_usd':1.0,'started_at':time.time(),**manifest})
    # Local paths are excluded from the prompt by schema_advisor.prompt().
    response=extract.remote(req)
    payload=json.dumps({'request':req,'manifest':manifest,**response},ensure_ascii=False,indent=2)+'\n'
    dest.write_text(payload);cache.parent.mkdir(parents=True,exist_ok=True);cache.write_text(payload)
    print(f'B01-only result: {dest}; cumulative reservation ${reserved:.2f}/15')
