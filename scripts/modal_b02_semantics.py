"""Isolated, bounded Qwen 3B B02 experiment. Never loads 9B or runs questions.

modal run scripts/modal_b02_semantics.py --request artifacts/b01_b02/request.json --output artifacts/b01_b02/modal.json
"""
from __future__ import annotations
import json
from pathlib import Path
import time
import modal

ROOT = Path(__file__).resolve().parents[1]
image = (modal.Image.debian_slim(python_version='3.12')
         .pip_install_from_requirements(str(ROOT / 'requirements-lock.txt'))
         .add_local_dir(str(ROOT / 'src'), '/workspace/src'))
app = modal.App('datamate-b02-semantics', image=image)
volume = modal.Volume.from_name('datamate-b0-volume', create_if_missing=False)

def reserve_budget(ledger: Path, manifest: dict, limit: float = 15.0) -> float:
    """One project-wide, locked reservation ledger; failed dispatches count too."""
    import fcntl
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        total = sum(json.loads(line)['reserved_usd'] for line in stream if line.strip())
        if total + manifest['reserved_usd'] > limit:
            raise RuntimeError('15 USD reservation limit reached; no GPU launched')
        stream.write(json.dumps(manifest)+'\n'); stream.flush()
        return total + manifest['reserved_usd']


@app.function(cpu=0.125, memory=256, timeout=60, volumes={'/vol':volume}, retries=0)
def model_identity() -> dict:
    """CPU-only identity check, before allowing a semantic-result cache hit."""
    import hashlib
    root = Path('/vol/models/Qwen--Qwen2.5-3B-Instruct')
    config = root/'config.json'
    if not config.is_file():
        raise RuntimeError('cached 3B model missing; no GPU launched')
    files = {p.name:{'size':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns}
             for p in root.iterdir() if p.is_file() and p.suffix in ('.json','.safetensors')}
    metadata = root/'.cache/huggingface/download'
    revisions = {p.name:p.read_text().splitlines()[:2] for p in metadata.glob('*.metadata')}
    return {'model_id':'Qwen/Qwen2.5-3B-Instruct','config_sha256':hashlib.sha256(config.read_bytes()).hexdigest(),
            'files':files,'download_revisions':revisions}


@app.function(gpu='A100', cpu=2, memory=16384, timeout=900, max_containers=1,
              scaledown_window=2, volumes={'/vol': volume}, retries=0)
def extract(packets: list[dict]) -> dict:
    import sys
    sys.path.insert(0, '/workspace/src')
    from datamate.context.semantic_experiment import extract_packet
    from vllm import LLM, SamplingParams
    from vllm.sampling_params import StructuredOutputsParams
    start = time.time()
    weights = Path('/vol/models/Qwen--Qwen2.5-3B-Instruct')
    if not (weights / 'config.json').is_file():
        raise RuntimeError('3B weights missing; CPU download required before GPU experiment')
    print('B02 ONLY: Qwen2.5-3B unit extraction with JSON schema; no 9B', flush=True)
    model = LLM(model=str(weights), tokenizer=str(weights), dtype='bfloat16', max_model_len=8192,
                gpu_memory_utilization=0.65, max_num_seqs=8, generation_config='vllm')
    evidence = {'type':'object','properties':{'rule_id':{'type':'string'},'quote':{'type':'string'}},
                'required':['rule_id','quote'],'additionalProperties':False}
    fields = {k:{'type':'string'} for k in ('item_name','from_unit','to_unit')}
    fields.update(factor={'type':'number'}, evidence=evidence)
    schema = {'type':'object','properties':{'unit_conversions':{'type':'array','items':{
        'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}}},
        'required':['unit_conversions'],'additionalProperties':False}
    sampling = SamplingParams(max_tokens=2048, temperature=0, seed=42,
                             structured_outputs=StructuredOutputsParams(json=schema))
    calls = []
    def chat(system, user):
        instruction = ('Chỉ trích xuất quy đổi đơn vị từ các dòng nguồn. Trả JSON unit_conversions. '
                       'Giữ NGUYÊN đầy đủ tên mặt hàng trước dấu hai chấm, kể cả lon/chai. '
                       'Mỗi mục có item_name, from_unit, to_unit, factor, evidence {rule_id, quote}. '
                       'Quote nguyên văn dòng có tên hàng và phương trình; rule_id đúng [ID] input. '
                       'Không xuất metrics hoặc JOIN. Không có phương trình thì trả mảng rỗng.')
        response = model.chat([{'role':'system','content':instruction},{'role':'user','content':user}],sampling,use_tqdm=False)[0]
        completion = response.outputs[0]
        calls.append({'raw_text':completion.text,'finish_reason':completion.finish_reason,
                      'prompt_tokens':len(response.prompt_token_ids or []),'completion_tokens':len(completion.token_ids)})
        if completion.finish_reason == 'length':
            raise ValueError('B02 output truncated; no partial metadata accepted')
        return completion.text
    results = [extract_packet(packet, chat) for packet in packets]
    revision_file = weights / '.cache/huggingface/download/config.json.metadata'
    revision = revision_file.read_text().splitlines()[0] if revision_file.is_file() else 'unknown_cached_revision'
    configs = {p.name: p.read_text() for p in weights.glob('*.json') if p.name in ('config.json', '.model-download.json')}
    return {'catalogs': results, 'calls': calls, 'elapsed_seconds': time.time()-start,
            'model': 'Qwen/Qwen2.5-3B-Instruct', 'model_revision': revision, 'model_metadata': configs,
            'modal_call_id': modal.current_function_call_id()}

def run_local(request: str, output: str):
    import subprocess
    import sys
    from hashlib import sha256
    profile = subprocess.check_output([sys.executable, '-m', 'modal', 'profile', 'current'], text=True).strip()
    if profile != 'geminiveo4ai57':
        raise RuntimeError('expected Modal profile geminiveo4ai57; no GPU launched')
    req = json.loads(Path(request).read_text())
    packets = req['packets']
    if not packets or len(packets) > 8:
        raise ValueError('pilot accepts 1..8 packets; prepare smaller batches')
    dest = Path(output); dest.parent.mkdir(parents=True, exist_ok=True)
    ledger = ROOT / 'artifacts/b01_b02/cost_ledger.jsonl'
    # Conservative reservation includes full 900s timeout, startup and CPU/RAM.
    reservation = 1.0
    manifest = {**req.get('manifest', {}), 'git_commit': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
                'request_sha256': sha256(Path(request).read_bytes()).hexdigest(),
                'source_sha256': {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src/datamate').rglob('*.py'))},
                'workspace': 'geminiveo4ai57', 'reserved_usd': reservation, 'started_at': time.time()}
    manifest['runner_sha256'] = sha256(Path(__file__).read_bytes()).hexdigest()
    manifest['lock_sha256'] = sha256((ROOT/'requirements-lock.txt').read_bytes()).hexdigest()
    manifest['generation'] = {'max_model_len':8192,'max_new_tokens':2048,'temperature':0,'seed':42,'structured_outputs':'unit_conversions'}
    manifest['model_identity'] = model_identity.remote()
    cache_key = sha256(json.dumps({k:v for k,v in manifest.items() if k not in ('started_at','reserved_usd')},sort_keys=True).encode()).hexdigest()
    cache_file = dest.parent / 'semantic_cache' / (cache_key + '.json')
    if cache_file.exists():
        dest.write_text(cache_file.read_text())
        print(f'B02 cache hit: {dest}; no GPU function dispatched')
        return
    # Reserve before dispatch; failed calls consume reservation too.
    reserved = reserve_budget(ledger, manifest)
    result = extract.remote(packets)
    result_json = json.dumps({'manifest': manifest, **result}, ensure_ascii=False, indent=2)+'\n'
    dest.write_text(result_json)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(result_json)
    print(f'B02-only artifacts: {dest}; reserved ${reserved:.2f}/$15')


@app.local_entrypoint()
def main(request: str, output: str):
    run_local(request, output)
