"""Full B01 and B02 Evaluation Runner using Qwen2.5-3B-Instruct hosted on Modal.

Runs across all 30 businesses in a single GPU container session on Modal:
- B02: Extracts unit conversions from business rules and documents with structured JSON.
- B01: Evaluates column roles and equi-join candidates with schema advisor.
- Validates all proposals against DuckDB ground truth.
- Enriches bundles and compares against Golden Data (data/golden/b01_b02_golden_full.json).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import modal

image = (modal.Image.debian_slim(python_version='3.12')
         .pip_install_from_requirements(str(ROOT / 'requirements-lock.txt'))
         .add_local_dir(str(ROOT / 'src'), '/workspace/src'))
volume = modal.Volume.from_name('datamate-b0-volume', create_if_missing=False)

app = modal.App('datamate-full-b01-b02', image=image)


@app.function(gpu='A100', cpu=2, memory=16384, timeout=1800, max_containers=1,
              scaledown_window=2, volumes={'/vol': volume}, retries=0)
def batch_run_modal(b02_packets: list[dict], b01_requests: list[dict]) -> dict:
    sys.path.insert(0, '/workspace/src')
    from vllm import LLM, SamplingParams
    from vllm.sampling_params import StructuredOutputsParams
    from datamate.ingestion.schema_advisor import SYSTEM_PROMPT as B01_SYSTEM_PROMPT, ROLES, prompt as b01_prompt

    start_time = time.time()
    weights_path = Path('/vol/models/Qwen--Qwen2.5-3B-Instruct')
    if not (weights_path / 'config.json').is_file():
        raise RuntimeError('3B cached weights missing on Modal volume')

    print(f'[Modal GPU] Khởi tạo mô hình Qwen2.5-3B-Instruct từ {weights_path}...', flush=True)
    model = LLM(
        model=str(weights_path),
        tokenizer=str(weights_path),
        dtype='bfloat16',
        max_model_len=8192,
        gpu_memory_utilization=0.65,
        max_num_seqs=8,
        generation_config='vllm',
    )
    print(f'[Modal GPU] Khởi tạo vLLM thành công sau {time.time() - start_time:.2f}s.', flush=True)

    # 1. B02 Unit Extraction Schema
    b02_instruction = (
        'Chỉ trích xuất quy đổi đơn vị từ các dòng nguồn. Trả JSON unit_conversions. '
        'Giữ NGUYÊN đầy đủ tên mặt hàng trước dấu hai chấm, kể cả lon/chai. '
        'Mỗi mục có item_name, from_unit, to_unit, factor, evidence {rule_id, quote}. '
        'item_name PHẢI là tên sản phẩm sạch (ví dụ: "Bánh croissant", "Pepsi 330ml"), KHÔNG chứa dấu hai chấm hay quy cách như ": 1 hộp". '
        'Quote nguyên văn dòng có tên hàng và phương trình; rule_id đúng [ID] input. '
        'Không xuất metrics hoặc JOIN. Không có phương trình thì trả mảng rỗng.'
    )
    b02_evidence = {
        'type': 'object',
        'properties': {'rule_id': {'type': 'string'}, 'quote': {'type': 'string'}},
        'required': ['rule_id', 'quote'],
        'additionalProperties': False,
    }
    b02_fields = {k: {'type': 'string'} for k in ('item_name', 'from_unit', 'to_unit')}
    b02_fields.update(factor={'type': 'number'}, evidence=b02_evidence)
    b02_schema = {
        'type': 'object',
        'properties': {
            'unit_conversions': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': b02_fields,
                    'required': list(b02_fields),
                    'additionalProperties': False,
                },
            }
        },
        'required': ['unit_conversions'],
        'additionalProperties': False,
    }
    b02_sampling = SamplingParams(
        max_tokens=4096,
        temperature=0,
        seed=42,
        structured_outputs=StructuredOutputsParams(json=b02_schema),
    )

    b02_results = []
    print(f'[Modal GPU] Bắt đầu xử lý {len(b02_packets)} B02 semantic packets...', flush=True)
    for idx, packet in enumerate(b02_packets):
        biz_id = packet['business_id']
        rules_text = '\n'.join(
            f"- [{r['rule_id']}] source={r.get('source', '')}: {r['text']}"
            for r in packet['rules']
        )
        user_prompt = f"DOANH NGHIỆP: {biz_id}\n\n### CÁC QUY TẮC NGHIỆP VỤ & TÀI LIỆU:\n{rules_text}"
        messages = [
            {'role': 'system', 'content': b02_instruction},
            {'role': 'user', 'content': user_prompt},
        ]
        res = model.chat(messages, b02_sampling, use_tqdm=False)[0]
        comp = res.outputs[0]
        try:
            parsed = json.loads(comp.text)
            for u in parsed.get('unit_conversions', []):
                if 'item_name' in u:
                    u['item_name'] = str(u['item_name']).split(':')[0].strip().strip('*-` ')
        except Exception as e:
            parsed = {'unit_conversions': [], 'error': str(e)}
        b02_results.append({
            'business_id': biz_id,
            'packet_id': packet.get('chunk_index', idx),
            'unit_conversions': parsed.get('unit_conversions', []),
            'tokens': len(comp.token_ids),
        })
        if (idx + 1) % 5 == 0 or idx == len(b02_packets) - 1:
            print(f'  -> B02 hoàn thành {idx + 1}/{len(b02_packets)} packets', flush=True)

    # 2. B01 Schema Advisor
    b01_results = []
    print(f'[Modal GPU] Bắt đầu xử lý {len(b01_requests)} B01 schema requests...', flush=True)
    for idx, req in enumerate(b01_requests):
        biz_id = req['business_id']
        source_ids = [d['source_id'] for d in req['documents']]
        source_lines = [line for d in req['documents'] for line in d['lines']]
        table_names = [t['name'] for t in req['tables']]
        column_names = sorted({c['name'] for t in req['tables'] for c in t['columns']})

        ev = {
            'type': 'object',
            'properties': {
                'source_id': {'type': 'string', 'enum': source_ids},
                'line': {'type': 'integer', 'enum': sorted({l['line'] for l in source_lines})},
                'quote': {'type': 'string', 'enum': list(dict.fromkeys(l['text'] for l in source_lines))},
            },
            'required': ['source_id', 'line', 'quote'],
            'additionalProperties': False,
        }
        role = {
            'type': 'object',
            'properties': {
                'table': {'type': 'string', 'enum': table_names},
                'column': {'type': 'string', 'enum': column_names},
                'role': {'type': 'string', 'enum': list(ROLES)},
                'evidence': ev,
            },
            'required': ['table', 'column', 'role', 'evidence'],
            'additionalProperties': False,
        }
        join = {
            'type': 'object',
            'properties': {
                'left_table': {'type': 'string', 'enum': table_names},
                'right_table': {'type': 'string', 'enum': table_names},
                'left_columns': {'type': 'array', 'items': {'type': 'string', 'enum': column_names}, 'minItems': 1, 'maxItems': 4},
                'right_columns': {'type': 'array', 'items': {'type': 'string', 'enum': column_names}, 'minItems': 1, 'maxItems': 4},
                'evidence': ev,
            },
            'required': ['left_table', 'right_table', 'left_columns', 'right_columns', 'evidence'],
            'additionalProperties': False,
        }
        b01_schema = {
            'type': 'object',
            'properties': {
                'column_roles': {'type': 'array', 'items': role, 'maxItems': 8},
                'join_candidates': {'type': 'array', 'items': join, 'maxItems': 4},
            },
            'required': ['column_roles', 'join_candidates'],
            'additionalProperties': False,
        }

        messages = [{'role': 'system', 'content': B01_SYSTEM_PROMPT}, {'role': 'user', 'content': b01_prompt(req)}]
        b01_sampling = SamplingParams(
            max_tokens=2048,
            temperature=0,
            seed=42,
            structured_outputs=StructuredOutputsParams(json=b01_schema),
        )
        res = model.chat(messages, b01_sampling, use_tqdm=False)[0]
        comp = res.outputs[0]
        try:
            parsed = json.loads(comp.text)
        except Exception as e:
            parsed = {'column_roles': [], 'join_candidates': [], 'error': str(e)}
        b01_results.append({
            'business_id': biz_id,
            'request_index': idx,
            'response': parsed,
            'tokens': len(comp.token_ids),
        })
        if (idx + 1) % 5 == 0 or idx == len(b01_requests) - 1:
            print(f'  -> B01 hoàn thành {idx + 1}/{len(b01_requests)} requests', flush=True)

    total_elapsed = time.time() - start_time
    print(f'[Modal GPU] Toàn bộ tác vụ hoàn tất trong {total_elapsed:.2f} giây.', flush=True)
    return {
        'elapsed_seconds': total_elapsed,
        'b02_results': b02_results,
        'b01_results': b01_results,
        'modal_call_id': modal.current_function_call_id(),
    }


@app.local_entrypoint()
def main():
    profile = subprocess.check_output([sys.executable, '-m', 'modal', 'profile', 'current'], text=True).strip()
    if profile != 'geminiveo4ai57':
        raise ValueError(f"Expected Modal profile geminiveo4ai57, got: {profile}")

    release_dir = ROOT / 'artifacts/b01_b02_full/bundles_release'
    train_data = ROOT / 'data/train/data'
    from datamate.ingestion.schema_advisor import build_request

    print("=" * 70)
    print("CHUẨN BỊ TOÀN BỘ DỮ LIỆU INPUT CHO B01 VÀ B02 TRÊN 30 DOANH NGHIỆP")
    print("=" * 70)

    b02_packets = []
    b01_requests = []
    biz_bundles = {}

    for biz_dir in sorted(release_dir.glob('biz_*')):
        biz_id = biz_dir.name
        subdirs = [p for p in biz_dir.iterdir() if p.is_dir() and (p / 'business_context.json').exists()]
        if not subdirs:
            continue
        bundle = subdirs[0]
        biz_bundles[biz_id] = bundle
        ctx = json.loads((bundle / 'business_context.json').read_text())
        readme = train_data / biz_id / 'README.md'

        # 1. B02 Packets (chunk 10 rules để tránh vượt trần tokens)
        unit_rules = [
            r for r in ctx['rule_catalog']['rules']
            if '=' in r['text'] and any(u in r['text'] for u in ('thùng', 'lon', 'chai', 'hộp', 'vỉ', 'két', 'lốc', 'gói', 'cây', 'bịch', 'viên', 'ly', 'tô', 'dĩa', 'bao', 'tấn', 'kg'))
        ]
        if unit_rules:
            CHUNK_SIZE = 10
            for i in range(0, len(unit_rules), CHUNK_SIZE):
                b02_packets.append({
                    'business_id': biz_id,
                    'chunk_index': i // CHUNK_SIZE,
                    'rules': unit_rules[i:i + CHUNK_SIZE],
                })

        # 2. B01 Requests
        non_cal_tables = [t['name'] for t in ctx['schema_catalog']['tables'] if t['name'] != 'calendar']
        if len(non_cal_tables) >= 2 and readme.exists():
            # Choose top relevant tables (fact + dimension) up to 4
            tables_to_advise = non_cal_tables[:4]
            try:
                req = build_request(bundle, [readme], tables_to_advise)
                b01_requests.append(req)
            except Exception:
                # Fallback to top 2 tables if 4 exceeds budget
                try:
                    req = build_request(bundle, [readme], non_cal_tables[:2])
                    b01_requests.append(req)
                except Exception as e:
                    print(f"Bỏ qua B01 advisor cho {biz_id}: {e}")

    print(f"Tổng số B02 packets: {len(b02_packets)}")
    print(f"Tổng số B01 requests: {len(b01_requests)}")
    print("=" * 70)

    # Budget reservation
    ledger = ROOT / 'artifacts/b01_b02/cost_ledger.jsonl'
    from scripts.modal_b02_semantics import reserve_budget
    manifest = {
        'scope': 'Full B01 and B02 Evaluation Run on Modal GPU',
        'reserved_usd': 1.0,
        'started_at': time.time(),
        'b02_packets_count': len(b02_packets),
        'b01_requests_count': len(b01_requests),
    }
    reserved = reserve_budget(ledger, manifest, limit=15.0)
    print(f"Đã đặt chỗ kinh phí ${reserved:.2f} / $15.00 limit.")

    print(f"\n[Modal Launch] Đang điều phối chạy batch trên Modal GPU (A100)...")
    result = batch_run_modal.remote(b02_packets, b01_requests)

    out_file = ROOT / 'artifacts/b01_b02_full/modal_full_results.json'
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f"Đã lưu kết quả thô từ Modal tại: {out_file}")

    # Áp dụng các kết quả B01 và B02 vào các bundles làm giàu (enriched)
    print("\n" + "=" * 70)
    print("ÁP DỤNG KẾT QUẢ TỪ MODAL VÀO CÁC BUNDLE & ĐỐI CHIẾU VỚI GOLDEN DATA")
    print("=" * 70)
    
    enriched_root = ROOT / 'artifacts/b01_b02_full/enriched_bundles'
    enriched_root.mkdir(parents=True, exist_ok=True)

    import duckdb
    import shutil
    from datamate.context.contracts import BusinessRule, SemanticCatalog
    from datamate.context.semantic_extractor import RuleSchemaMatcher
    from datamate.context.verified_semantics import verified_merge
    from datamate.ingestion.contracts import ColumnMetadata, SchemaCatalog, TableMetadata
    from datamate.ingestion.ingestion.profiling import DuckDBProfileProvider
    from datamate.ingestion.schema_advisor import validate_response
    from datamate.ingestion.schema_catalog import SchemaCatalogBuilder

    matcher = RuleSchemaMatcher()

    # Group B02 results by business_id
    b02_by_biz: dict[str, list[dict]] = {}
    for res in result['b02_results']:
        b02_by_biz.setdefault(res['business_id'], []).extend(res.get('unit_conversions', []))

    # Map B01 results by request_index
    b01_by_index: dict[int, dict] = {res['request_index']: res['response'] for res in result['b01_results']}

    for biz_id, bundle_dir in sorted(biz_bundles.items()):
        ctx_path = bundle_dir / 'business_context.json'
        ctx_data = json.loads(ctx_path.read_text())
        
        # Clone bundle to enriched directory
        target_dir = enriched_root / biz_id
        target_dir.mkdir(parents=True, exist_ok=True)
        sub_target = target_dir / bundle_dir.name
        if not sub_target.exists():
            shutil.copytree(bundle_dir, sub_target)

        duck_file = sub_target / 'data.duckdb'
        new_ctx_path = sub_target / 'business_context.json'

        with duckdb.connect(str(duck_file)) as con:
            tables_raw = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
            table_names = [r[0] for r in tables_raw if r[0] != "calendar" and not r[0].startswith("__")]

            # 1. B01 Joins: Ingest tables and run updated _sql_join_candidates from core engine
            col_role_mapping = {
                (t["name"], c["name"]): c.get("role")
                for t in ctx_data.get("schema_catalog", {}).get("tables", [])
                for c in t.get("columns", [])
                if c.get("role")
            }

            provider = DuckDBProfileProvider(con, biz_id, column_roles=col_role_mapping)
            builder = SchemaCatalogBuilder(provider)

            tables = []
            for tn in table_names:
                cols = [ColumnMetadata(c[1], c[2]) for c in con.execute(f'PRAGMA table_info("{tn}")').fetchall() if not c[1].startswith("__")]
                cnt = con.execute(f'SELECT COUNT(*) FROM "{tn}"').fetchone()[0]
                tables.append(TableMetadata(tn, tuple(cols), row_count=cnt))

            inferred_catalog = builder._sql_join_candidates(tables, [], [], [])
            
            # Format inferred join edges for context json
            join_graph = []
            for edge in inferred_catalog.join_graph:
                join_dict = {
                    "left_table": edge.left_table,
                    "left_column": edge.left_column,
                    "right_table": edge.right_table,
                    "right_column": edge.right_column,
                    "cardinality": edge.cardinality,
                    "status": edge.status,
                    "confidence": edge.confidence,
                    "evidence": list(edge.evidence),
                    "fanout_warning": edge.fanout_warning,
                }
                if edge.additional_key_pairs:
                    join_dict["additional_key_pairs"] = [list(p) for p in edge.additional_key_pairs]
                join_graph.append(join_dict)

            # Merge any advisor join candidates from Modal
            for req_idx, req in enumerate(b01_requests):
                if req['business_id'] == biz_id and req_idx in b01_by_index:
                    try:
                        advice = validate_response(bundle_dir, req, b01_by_index[req_idx])
                        for j in advice.get('join_candidates', []):
                            edge = j.get('edge')
                            if edge and edge.get('status') in ('candidate', 'uncertain', 'validated'):
                                join_graph.append(edge)
                    except Exception as e:
                        print(f"Lỗi validate B01 cho {biz_id} req #{req_idx}: {e}")

            ctx_data.setdefault("schema_catalog", {})["join_graph"] = join_graph

            # 2. B02 Unit Conversions:
            rules = tuple(BusinessRule(**r) for r in ctx_data['rule_catalog']['rules'])
            base_sem = matcher.extract_semantic_catalog(biz_id, SchemaCatalog(tables=()), rules)
            verified_units = list(base_sem.unit_conversions)
            seen_keys = {
                (str(u["item_name"]).strip().lower(), str(u["from_unit"]).strip().lower(), str(u["to_unit"]).strip().lower())
                for u in verified_units
            }

            # Merge LLM extractions from Modal if any
            llm_units = b02_by_biz.get(biz_id, [])
            if llm_units:
                try:
                    merged = verified_merge(biz_id, base_sem, {'unit_conversions': llm_units}, SchemaCatalog(tables=()), rules)
                    for u in merged.to_dict().get('unit_conversions', []):
                        k = (str(u["item_name"]).strip().lower(), str(u["from_unit"]).strip().lower(), str(u["to_unit"]).strip().lower())
                        if k not in seen_keys:
                            seen_keys.add(k)
                            verified_units.append(u)
                except Exception as e:
                    print(f"Lỗi verified_merge cho {biz_id}: {e}")

            # Bổ sung đơn vị quy đổi từ bảng DB
            conv_tables = [t for t in table_names if "quy_doi" in t.lower()]
            for ct in conv_tables:
                col_tuples = con.execute(f'PRAGMA table_info("{ct}")').fetchall()
                cols = [c[1] for c in col_tuples]
                if "ten_san_pham" in cols and "don_vi_quy_doi" in cols and "ti_le_quy_doi" in cols and "don_vi_co_ban" in cols:
                    rows = con.execute(f'SELECT ten_san_pham, don_vi_quy_doi, ti_le_quy_doi, don_vi_co_ban FROM "{ct}"').fetchall()
                    for r in rows:
                        if r[0] and r[1] and r[2] and r[3]:
                            k = (str(r[0]).strip().lower(), str(r[1]).strip().lower(), str(r[3]).strip().lower())
                            if k not in seen_keys:
                                seen_keys.add(k)
                                verified_units.append({
                                    "item_name": str(r[0]),
                                    "from_unit": str(r[1]),
                                    "factor": str(r[2]),
                                    "to_unit": str(r[3]),
                                    "status": "database_verified",
                                })
                elif "ma_sp" in cols and "don_vi" in cols and "bang" in cols:
                    prod_tables = [t for t in table_names if any(k in t for k in ("hang_hoa", "san_pham"))]
                    if prod_tables:
                        pt = prod_tables[0]
                        p_cols = [c[1] for c in con.execute(f'PRAGMA table_info("{pt}")').fetchall()]
                        name_col = next((c for c in ("mon", "ten_sp", "ten_san_pham", "ten_hang") if c in p_cols), None)
                        base_unit_col = next((c for c in ("don_vi", "don_vi_tinh", "don_vi_co_ban") if c in p_cols), None)
                        if name_col and base_unit_col:
                            rows = con.execute(f'SELECT p.{name_col}, q.don_vi, q.bang, p.{base_unit_col} FROM "{ct}" q JOIN "{pt}" p ON q.ma_sp = p.ma_sp').fetchall()
                            for r in rows:
                                if r[0] and r[1] and r[2] and r[3]:
                                    k = (str(r[0]).strip().lower(), str(r[1]).strip().lower(), str(r[3]).strip().lower())
                                    if k not in seen_keys:
                                        seen_keys.add(k)
                                        verified_units.append({
                                            "item_name": str(r[0]),
                                            "from_unit": str(r[1]),
                                            "factor": str(r[2]),
                                            "to_unit": str(r[3]),
                                            "status": "database_verified",
                                        })

            # Ghi nhận unit_conversions vào DuckDB
            if verified_units:
                seen_pairs = set()
                bidi_units = []
                for u in verified_units:
                    item = str(u.get('item_name', '')).strip()
                    f_u = str(u.get('from_unit', '')).strip()
                    t_u = str(u.get('to_unit', '')).strip()
                    try:
                        factor = float(u.get('factor', 1.0))
                    except (ValueError, TypeError):
                        factor = 1.0
                    if not (item and f_u and t_u and factor > 0):
                        continue
                    pair_fwd = (item.casefold(), f_u.casefold(), t_u.casefold())
                    if pair_fwd not in seen_pairs:
                        seen_pairs.add(pair_fwd)
                        bidi_units.append([item, f_u, t_u, factor])
                    pair_rev = (item.casefold(), t_u.casefold(), f_u.casefold())
                    if pair_rev not in seen_pairs:
                        seen_pairs.add(pair_rev)
                        bidi_units.append([item, t_u, f_u, round(1.0 / factor, 12)])

                con.execute("CREATE TABLE IF NOT EXISTS main.unit_conversions (item_name VARCHAR, from_unit VARCHAR, to_unit VARCHAR, factor DECIMAL(38,12))")
                con.execute("DELETE FROM main.unit_conversions")
                for r in bidi_units:
                    con.execute("INSERT INTO main.unit_conversions VALUES (?, ?, ?, ?)", r)

            # Cập nhật semantic_catalog
            ctx_data.setdefault('semantic_catalog', {})['unit_conversions'] = verified_units

        new_ctx_path.write_text(json.dumps(ctx_data, ensure_ascii=False, indent=2))

    print("\n" + "=" * 70)
    print("CHẠY ĐỐI CHIẾU BẰNG compare_with_golden.py TRÊN TOÀN BỘ ENRICHED BUNDLES")
    print("=" * 70)
    
    cmd = [sys.executable, str(ROOT / 'scripts/compare_with_golden.py'), '--all-bundles', str(enriched_root)]
    subprocess.run(cmd, check=True)


if __name__ == '__main__':
    main()
