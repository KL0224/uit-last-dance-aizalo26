"""Tool to compare user's generated B01 and B02 outputs against the Golden Dataset.

Usage:
    .venv/bin/python scripts/compare_with_golden.py --bundle-dir <bundle_or_cache_directory>
    .venv/bin/python scripts/compare_with_golden.py --context-json <path_to_business_context.json>
    .venv/bin/python scripts/compare_with_golden.py --advisor-json <path_to_advisor_advice.json>
    .venv/bin/python scripts/compare_with_golden.py --semantics-json <path_to_modal_b02.json>
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT / 'data/golden/b01_b02_golden_full.json'

def evaluate_b01(actual_schema, golden_b01):
    report = {'tables': {}, 'joins': {}, 'summary': {}}
    
    # Evaluate tables and columns
    actual_tables = {t['name']: t for t in actual_schema.get('tables', [])}
    golden_tables = golden_b01.get('tables', {})
    
    tp_tables = set(actual_tables.keys()) & set(golden_tables.keys())
    precision_tables = len(tp_tables) / len(actual_tables) if actual_tables else 0.0
    recall_tables = len(tp_tables) / len(golden_tables) if golden_tables else 0.0
    
    report['summary']['table_precision'] = round(precision_tables, 4)
    report['summary']['table_recall'] = round(recall_tables, 4)
    
    # Evaluate Joins
    actual_joins = actual_schema.get('join_graph', [])
    golden_joins = golden_b01.get('join_relationships', [])
    
    def norm_join(j):
        lt = j.get('left_table')
        rt = j.get('right_table')
        
        if j.get('left_columns'):
            lc = list(j['left_columns'])
        elif j.get('left_column'):
            lc = [j['left_column']]
            for pair in j.get('additional_key_pairs', []):
                lc.append(pair[0])
        else:
            lc = []
            
        if j.get('right_columns'):
            rc = list(j['right_columns'])
        elif j.get('right_column'):
            rc = [j['right_column']]
            for pair in j.get('additional_key_pairs', []):
                rc.append(pair[1])
        else:
            rc = []

        fwd = (lt, tuple(lc), rt, tuple(rc))
        rev = (rt, tuple(rc), lt, tuple(lc))
        return min(fwd, rev)
        
    actual_join_set = {norm_join(j) for j in actual_joins if norm_join(j)[0] and norm_join(j)[2]}
    golden_join_set = {norm_join(j) for j in golden_joins}
    
    tp_joins = actual_join_set & golden_join_set
    report['summary']['join_precision'] = round(len(tp_joins) / len(actual_join_set), 4) if actual_join_set else 1.0
    report['summary']['join_recall'] = round(len(tp_joins) / len(golden_join_set), 4) if golden_join_set else 1.0
    report['summary']['matched_joins'] = len(tp_joins)
    report['summary']['expected_joins'] = len(golden_join_set)
    report['summary']['actual_joins'] = len(actual_join_set)
    
    return report

def evaluate_b02(actual_context, golden_b02):
    report = {'units': {}, 'status': {}, 'summary': {}}
    
    # Evaluate unit conversions
    actual_units = actual_context.get('semantic_catalog', {}).get('unit_conversions', [])
    if not actual_units and 'unit_conversions' in actual_context:
        actual_units = actual_context['unit_conversions']
        
    def norm_u(u):
        return (str(u.get('item_name')).strip().lower(), str(u.get('from_unit')).strip().lower(),
                str(u.get('to_unit')).strip().lower(), float(u.get('factor', 0)))
                
    act_u_set = {norm_u(u) for u in actual_units}
    gold_u_set = {norm_u(u) for u in golden_b02.get('unit_conversions', [])}
    
    tp_u = act_u_set & gold_u_set
    report['summary']['unit_precision'] = round(len(tp_u) / len(act_u_set), 4) if act_u_set else 1.0
    report['summary']['unit_recall'] = round(len(tp_u) / len(gold_u_set), 4) if gold_u_set else 1.0
    report['summary']['matched_units'] = len(tp_u)
    report['summary']['expected_units'] = len(gold_u_set)
    report['summary']['actual_units'] = len(act_u_set)
    
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-dir', type=Path, help='Path to prepared bundle directory')
    parser.add_argument('--all-bundles', type=Path, help='Path to directory containing all business bundles (e.g. bundles_release)')
    parser.add_argument('--context-json', type=Path, help='Path to business_context.json')
    parser.add_argument('--business-id', help='Business ID to compare against (e.g. biz_128)')
    args = parser.parse_args()
    
    if not GOLDEN_PATH.exists():
        print(f'Error: Golden data not found at {GOLDEN_PATH}. Run scripts/build_golden.py first.')
        return
        
    golden_full = json.loads(GOLDEN_PATH.read_text())
    
    if args.all_bundles:
        print('=' * 80)
        print('FULL EVALUATION ACROSS ALL BUSINESSES AGAINST GOLDEN DATA')
        print('=' * 80)
        total_matched_joins = 0
        total_expected_joins = 0
        total_actual_joins = 0
        total_matched_units = 0
        total_expected_units = 0
        total_actual_units = 0
        
        row_fmt = '{:<10} | {:<10} | {:<10} | {:<15} | {:<15}'
        print(row_fmt.format('Biz ID', 'Tbl Rec', 'Tbl Prec', 'Join Match/Exp', 'Unit Match/Exp'))
        print('-' * 80)
        
        for biz_id in sorted(golden_full.keys()):
            biz_dir = args.all_bundles / biz_id
            if not biz_dir.exists():
                print(f'{biz_id:<10} | NOT FOUND')
                continue
            # find subfolder with hash
            subdirs = [p for p in biz_dir.iterdir() if p.is_dir() and (p / 'business_context.json').exists()]
            if not subdirs:
                if (biz_dir / 'business_context.json').exists():
                    subdirs = [biz_dir]
                else:
                    print(f'{biz_id:<10} | NO CONTEXT JSON')
                    continue
            actual_ctx = json.loads((subdirs[0] / 'business_context.json').read_text())
            gold = golden_full[biz_id]
            b01_res = evaluate_b01(actual_ctx.get('schema_catalog', {}), gold['b01_schema'])
            b02_res = evaluate_b02(actual_ctx, gold['b02_semantics'])
            
            s1 = b01_res['summary']
            s2 = b02_res['summary']
            
            total_matched_joins += s1['matched_joins']
            total_expected_joins += s1['expected_joins']
            total_actual_joins += s1['actual_joins']
            
            total_matched_units += s2['matched_units']
            total_expected_units += s2['expected_units']
            total_actual_units += s2['actual_units']
            
            join_str = f"{s1['matched_joins']}/{s1['expected_joins']} ({s1['join_recall']*100:.1f}%)"
            unit_str = f"{s2['matched_units']}/{s2['expected_units']} ({s2['unit_recall']*100:.1f}%)"
            
            print(row_fmt.format(
                biz_id,
                f"{s1['table_recall']*100:.1f}%",
                f"{s1['table_precision']*100:.1f}%",
                join_str,
                unit_str
            ))
            
        print('-' * 80)
        overall_join_rec = total_matched_joins / total_expected_joins if total_expected_joins else 1.0
        overall_join_prec = total_matched_joins / total_actual_joins if total_actual_joins else 0.0
        overall_unit_rec = total_matched_units / total_expected_units if total_expected_units else 1.0
        overall_unit_prec = total_matched_units / total_actual_units if total_actual_units else 0.0
        
        print(f"OVERALL JOINS: Matched {total_matched_joins}/{total_expected_joins} expected (Recall: {overall_join_rec*100:.2f}%, Precision: {overall_join_prec*100:.2f}%, Total Proposed: {total_actual_joins})")
        print(f"OVERALL UNIT CONVERSIONS: Matched {total_matched_units}/{total_expected_units} expected (Recall: {overall_unit_rec*100:.2f}%, Precision: {overall_unit_prec*100:.2f}%, Total Proposed: {total_actual_units})")
        print('=' * 80)
        return
        
    if args.bundle_dir:
        ctx_file = args.bundle_dir / 'business_context.json'
        if not ctx_file.exists():
            print(f'Error: business_context.json not found in {args.bundle_dir}')
            return
        actual_ctx = json.loads(ctx_file.read_text())
        biz_id = actual_ctx.get('business_id') or args.business_id
    elif args.context_json:
        actual_ctx = json.loads(args.context_json.read_text())
        biz_id = actual_ctx.get('business_id') or args.business_id
    else:
        print('Please supply either --bundle-dir or --context-json')
        return
        
    if not biz_id or biz_id not in golden_full:
        print(f'Error: Unknown business ID: {biz_id}. Available: {list(golden_full.keys())}')
        return
        
    gold = golden_full[biz_id]
    b01_res = evaluate_b01(actual_ctx.get('schema_catalog', {}), gold['b01_schema'])
    b02_res = evaluate_b02(actual_ctx, gold['b02_semantics'])
    
    print('=' * 60)
    print(f'EVALUATION REPORT: {biz_id} against GOLDEN DATA')
    print('=' * 60)
    print('[B01 Schema Evaluation]')
    print(f"  Table Precision : {b01_res['summary']['table_precision'] * 100:.2f}%")
    print(f"  Table Recall    : {b01_res['summary']['table_recall'] * 100:.2f}%")
    print(f"  Join Precision  : {b01_res['summary']['join_precision'] * 100:.2f}%")
    print(f"  Join Recall     : {b01_res['summary']['join_recall'] * 100:.2f}% ({b01_res['summary']['matched_joins']}/{b01_res['summary']['expected_joins']})")
    print('-' * 60)
    print('[B02 Semantics Evaluation]')
    print(f"  Unit Precision  : {b02_res['summary']['unit_precision'] * 100:.2f}%")
    print(f"  Unit Recall     : {b02_res['summary']['unit_recall'] * 100:.2f}% ({b02_res['summary']['matched_units']}/{b02_res['summary']['expected_units']})")
    print('=' * 60)

if __name__ == '__main__':
    main()
