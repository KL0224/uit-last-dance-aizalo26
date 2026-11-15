"""Generate complete, verified Golden Data for B01 and B02 across all 30 businesses."""
import json
import re
from pathlib import Path
from decimal import Decimal
import duckdb

ROOT = Path(__file__).resolve().parents[1]

prep_full = ROOT / 'artifacts/b01_b02_full/preparation_release.json'
prep_data = json.load(prep_full.open())
bundle_map = {r['business_id']: Path(r['warm']['bundle_dir']) for r in prep_data['results']}

INDUSTRIES = {
    'biz_101': 'Bán lẻ / Tạp hóa',
    'biz_102': 'Bán lẻ / Nước giải khát',
    'biz_103': 'Bán lẻ / Nước giải khát',
    'biz_104': 'Tiệm bánh ngọt',
    'biz_105': 'Cà phê',
    'biz_106': 'Cà phê',
    'biz_107': 'Bán lẻ / Tạp hóa',
    'biz_108': 'Bán lẻ / Tạp hóa & Nước giải khát',
    'biz_109': 'Siêu thị mini / Tạp hóa',
    'biz_110': 'Bán buôn / Tạp hóa',
    'biz_111': 'Cà phê & Bánh ngọt',
    'biz_112': 'Cà phê & Bánh ngọt',
    'biz_113': 'Vật liệu xây dựng',
    'biz_114': 'Vật liệu xây dựng',
    'biz_115': 'Vật liệu xây dựng',
    'biz_116': 'Vật liệu xây dựng',
    'biz_117': 'Vật liệu xây dựng',
    'biz_118': 'Vật liệu xây dựng',
    'biz_119': 'Nhà thuốc / Dược phẩm',
    'biz_120': 'Nhà thuốc / Dược phẩm',
    'biz_121': 'Nhà thuốc / Dược phẩm',
    'biz_122': 'Nhà thuốc / Dược phẩm',
    'biz_123': 'Nhà thuốc / Bán lẻ POS',
    'biz_124': 'Nhà thuốc / Dược phẩm',
    'biz_125': 'Quán ăn / Nhà hàng',
    'biz_126': 'Quán ăn / Nhà hàng',
    'biz_127': 'Quán ăn / Nhà hàng',
    'biz_128': 'Quán ăn / Nhà hàng',
    'biz_129': 'Quán ăn / Nhà hàng',
    'biz_130': 'Quán ăn / Nhà hàng',
}

def infer_column_role(col_name, table_grain=''):
    name = col_name.lower()
    if name in ('__dm_row_id', 'stt', 'thu_tu'):
        return 'technical_id'
    # Order ID
    if any(k in name for k in ('ma_hoa_don', 'ma_don_hang', 'ma_bill', 'so_hd', 'ma_chung_tu', 'ma_don', 'so_chung_tu')) and not 'chi_tiet' in name:
        return 'order_id'
    # Customer ID
    if 'so_khach' in name:
        return 'quantity'
    if any(k in name for k in ('ma_khach_hang', 'ma_kh', 'so_kh', 'ma_khach')):
        return 'customer_id'
    if name in ('ben_mua', 'doi_tac', 'khach_hang', 'ten_khach_hang') and not any(k in name for k in ('dia_chi', 'sdt', 'phone', 'mst', 'cccd', 'email')):
        return 'customer_id'
    # Product ID
    if any(k in name for k in ('ma_hang_hoa', 'ma_san_pham', 'ma_hang', 'id_sp', 'sku', 'ma_barcode', 'ma_sp', 'barcode')):
        return 'product_id'
    # Order Date
    if any(k in name for k in ('ngay_dat_hang', 'ngay_ban', 'ngay_giao_dich', 'ngay_tao', 'ngay_thang', 'thoi_gian_tao', 'ngay_don', 'ngay_lap', 'thoi_gian_don')) or name in ('ngay', 'thoi_gian'):
        return 'order_date'
    if any(k in name for k in ('ngay_thu', 'thoi_gian_thu', 'ngay_thanh_toan')):
        return 'payment_date'
    if any(k in name for k in ('ngay_nhap', 'ngay_nhap_kho')):
        return 'order_date'
    # Price & Money
    if any(k in name for k in ('gia_ban', 'don_gia', 'gia_san_pham', 'gia_ban_le', 'gia_don_vi', 'gia_nhap', 'don_gia_nhap', 'gia')):
        return 'unit_price'
    if any(k in name for k in ('gia_von', 'gia_von_hien_tai', 'gia_von_luc_ban')):
        return 'cost_price'
    if any(k in name for k in ('thanh_tien', 't_tien', 'tien_hang', 'tri_gia')) or (name == 'tong_tien' and 'line' in table_grain):
        return 'line_amount'
    if any(k in name for k in ('tong_bill', 'tong_sau_giam_gia', 'can_tra_ncc', 'tong_gia_tri_nhap', 'tong_don', 'phai_thu')) or (name == 'tong_tien' and 'order' in table_grain):
        return 'order_total'
    if any(k in name for k in ('chua_tra', 'con_no', 'da_tra', 'khach_tra', 'con_lai', 'khach_da_tra', 'so_tien_thu', 'tien')):
        return 'debt_amount'
    if any(k in name for k in ('giam_gia', 'chiet_khau')):
        return 'discount'
    # Quantity
    if any(k in name for k in ('so_luong', 'sl', 'sl_quy_doi', 'so_luong_quy_doi', 'quy_ra_dv_le', 'so_luong_le', 'so_luong_san_pham', 'ton_kho', 'ton_cuoi', 'ton_cuoi_ky', 'sl_nhap', 'so_luong_nhap')):
        return 'quantity'
    # Status
    if any(k in name for k in ('trang_thai', 'tinh_trang', 'ket_qua', 'xu_ly', 'status')):
        return 'status'
    # Unit
    if any(k in name for k in ('don_vi_tinh', 'dvt', 'don_vi', 'don_vi_quy_doi', 'don_vi_co_ban')):
        return 'unit'
    # Entity name
    if any(k in name for k in ('ten_hang', 'ten_san_pham', 'ten_hang_hoa', 'ten_mon', 'noi_dung', 'san_pham')):
        return 'entity_name'
    if any(k in name for k in ('nhom_hang', 'phan_loai', 'loai_hang_hoa', 'nhom_hang_hoa', 'nhom_hang_3_cap', 'nhom_khach_hang', 'nhom')):
        return 'category'
    if any(k in name for k in ('ghi_chu', 'mo_ta')):
        return 'notes'
    if any(k in name for k in ('so_lo', 'han_dung', 'han_su_dung', 'ngay_het_han')):
        return 'batch_expiry'
    return 'other'

def infer_table_grain(table_name):
    t = table_name.lower()
    if 'chi_tiet' in t or 'line' in t:
        if 'nhap' in t: return 'goods_receipt_line'
        if 'lo' in t: return 'order_batch_line'
        return 'order_line'
    if 'ban_theo_lo' in t: return 'order_batch_line'
    if any(k in t for k in ('hoa_don', 'don_hang', 'don_nhap', 'phieu_nhap', 'ban_hang', 'so_ban_hang', 'phieu_giao', 'so_chi_tiet_ban_hang')):
        if any(k in t for k in ('nhap', 'phieu_nhap', 'don_nhap')): return 'goods_receipt'
        if 'phieu_giao' in t: return 'delivery_note'
        if any(k in t for k in ('chi_tiet', 'so_ban_hang', 'ban_hang', 'so_chi_tiet')): return 'order_line'
        return 'order'
    if 'thanh_toan' in t or 'phieu_thu' in t or 'so_quy' in t: return 'payment'
    if any(k in t for k in ('san_pham', 'hang_hoa', 'danh_muc')): return 'product'
    if 'khach_hang' in t: return 'customer'
    if 'ton_kho' in t: return 'inventory_snapshot'
    if 'quy_doi' in t: return 'unit_conversion'
    if 'phong_ban' in t: return 'order_service_table'
    if 'lo_hang' in t: return 'product_batch'
    if 'thuoc' in t: return 'medicine_catalog'
    if 'bang_gia' in t or 'lich_su_gia' in t: return 'price_list'
    if 'cong_no' in t or 'so_han_no' in t or 'so_no' in t: return 'debt_record'
    return 'other'

def parse_readme(biz_id):
    p = ROOT / f'data/train/data/{biz_id}/README.md'
    if not p.exists(): return {}, [], None
    text = p.read_text(encoding='utf-8')
    m_date = re.search(r'Dữ liệu có đến hết\s+([0-9]{2}/[0-9]{2}/[0-9]{4})', text)
    cutoff_vn = m_date.group(1) if m_date else None
    cutoff_iso = None
    if cutoff_vn:
        d, m, y = cutoff_vn.split('/')
        cutoff_iso = f'{y}-{m}-{d}'
    lower = text.lower()
        
    units = []
    current_item = None
    for line in text.splitlines():
        line_str = line.strip()
        m1 = re.match(r'^[-\*\s]*([^:]+):\s*1\s+([^\s=]+)\s*=\s*([0-9.,]+)\s+([^\s]+)', line_str)
        if m1:
            item = m1.group(1).strip().strip('*` ')
            from_u = m1.group(2).strip()
            factor = float(m1.group(3).replace(',', '.'))
            to_u = m1.group(4).strip()
            units.append({'item_name': item, 'from_unit': from_u, 'to_unit': to_u, 'factor': factor, 'source': 'README.md'})
        elif line_str.startswith('-') and ':' in line_str and not ('=' in line_str):
            current_item = line_str.split(':', 1)[0].lstrip('-* ').strip('*` ')
        elif current_item and ('=' in line_str):
            m2 = re.search(r'1\s+([^\s=]+)\s*=\s*([0-9.,]+)\s+([^\s]+)', line_str)
            if m2:
                from_u = m2.group(1).strip()
                factor = float(m2.group(2).replace(',', '.'))
                to_u = m2.group(3).strip()
                units.append({'item_name': current_item, 'from_unit': from_u, 'to_unit': to_u, 'factor': factor, 'source': 'README.md'})
                
    rules = {}
    if 'phí phục vụ' in lower:
        rules['service_fee'] = 'Đơn ngồi phòng lạnh có dòng Phí phục vụ (không tính là mặt hàng, không đếm/xếp hạng nhưng cộng vào doanh thu)'
    if 'trả hàng' in lower and ('âm' in lower or 'số lượng âm' in lower):
        rules['return_handling'] = 'negative_quantity_line'
    else:
        rules['return_handling'] = 'exclude_entire_order'
    if 'thuốc kê đơn' in lower:
        rules['prescription'] = 'Thuốc kê đơn = sản phẩm ghi kê đơn trong danh mục thuốc'
    if 'lô' in lower or 'hạn dùng' in lower:
        rules['batch_expiry'] = 'Theo dõi theo lô và hạn sử dụng'
    if any(k in lower for k in ('công nợ', 'còn nợ', 'chưa trả')):
        rules['debt'] = 'Tính theo số chưa trả của tổng đơn; tuổi nợ tính từ ngày đặt'
    return rules, units, cutoff_iso

golden_b01 = {}
golden_b02 = {}
golden_full = {}

for biz_id in sorted(bundle_map.keys()):
    bundle = bundle_map[biz_id]
    db_path = bundle / 'data.duckdb'
    manifest_path = bundle / 'source_manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    
    rules, readme_units, cutoff_iso = parse_readme(biz_id)
    industry = INDUSTRIES[biz_id]
    
    with duckdb.connect(str(db_path), read_only=True) as con:
        # Get tables
        tables_res = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_name != 'calendar'").fetchall()
        table_names = [t[0] for t in tables_res]
        
        tables_dict = {}
        for t in table_names:
            grain = infer_table_grain(t)
            row_count = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            col_info = con.execute(f'PRAGMA table_info("{t}")').fetchall()
            
            columns = {}
            candidate_pks = []
            for cid, name, sql_type, notnull, dflt, pk in col_info:
                if name.startswith('__'): continue
                role = infer_column_role(name, grain)
                columns[name] = {
                    'sql_type': sql_type,
                    'role': role,
                    'nullable': not notnull
                }
                # Check uniqueness for PK
                try:
                    dist, non_null = con.execute(f'SELECT COUNT(DISTINCT "{name}"), COUNT("{name}") FROM "{t}"').fetchone()
                    if dist == row_count and non_null == row_count:
                        candidate_pks.append(name)
                except Exception:
                    pass
            
            # Select most canonical PK
            primary_key = []
            if candidate_pks:
                priority_names = ['ma_hoa_don', 'ma_don_hang', 'ma_bill', 'ma_chung_tu', 'ma_don', 'ma_nhap_hang', 'ma_phieu_nhap', 'ma_khach_hang', 'ma_kh', 'ma_hang_hoa', 'ma_san_pham', 'ma_hang', 'sku', 'id_sp', 'ten_san_pham']
                matched = [p for p in priority_names if p in candidate_pks]
                primary_key = [matched[0]] if matched else [candidate_pks[0]]
            elif grain == 'order_line' and any(k in columns for k in ('ma_hoa_don', 'ma_don_hang', 'ma_don', 'so_hd')):
                ord_col = next(c for c in ('ma_hoa_don', 'ma_don_hang', 'ma_don', 'so_hd') if c in columns)
                line_col = next((c for c in ('stt', 'thu_tu', 'ma_hang', 'ten_hang', 'ten_san_pham') if c in columns), None)
                if line_col:
                    primary_key = [ord_col, line_col]
            
            tables_dict[t] = {
                'grain': grain,
                'row_count': row_count,
                'primary_key': primary_key,
                'columns': columns
            }
            
        # Discover table unit conversions from DB
        all_units = list(readme_units)
        conv_tables = [t for t in table_names if 'quy_doi' in t.lower()]
        for ct in conv_tables:
            cols = list(tables_dict[ct]['columns'].keys())
            if 'ten_san_pham' in cols:
                rows = con.execute(f'SELECT ten_san_pham, don_vi_quy_doi, ti_le_quy_doi, don_vi_co_ban FROM "{ct}"').fetchall()
                for r in rows:
                    all_units.append({
                        'item_name': r[0],
                        'from_unit': r[1],
                        'to_unit': r[3],
                        'factor': float(r[2]),
                        'equation': f'1 {r[1]} = {r[2]} {r[3]}',
                        'source': ct
                    })
            elif 'ma_sp' in cols:
                # biz_124
                rows = con.execute(f'''
                    SELECT h.mon, q.don_vi, q.bang, h.don_vi 
                    FROM "{ct}" q 
                    JOIN ban_hang_hang_hoa_c1fb869d h ON q.ma_sp = h.ma_sp
                ''').fetchall()
                for r in rows:
                    all_units.append({
                        'item_name': r[0],
                        'from_unit': r[1],
                        'to_unit': r[3],
                        'factor': float(r[2]),
                        'equation': f'1 {r[1]} = {r[2]} {r[3]}',
                        'source': ct
                    })
                    
        # Dedup units
        seen_units = set()
        clean_units = []
        for u in all_units:
            key = (u['item_name'].strip().lower(), u['from_unit'].strip().lower(), u['to_unit'].strip().lower())
            if key not in seen_units:
                seen_units.add(key)
                clean_units.append(u)
                
        # Status analysis
        valid_sales_statuses = ['completed', 'delivering', 'Chờ giao', 'Đang giao dịch', 'Đang xử lý']
        cancelled_statuses = ['cancelled', 'hủy', 'huỷ', 'đã hủy', 'đã huỷ']
        returned_statuses = ['returned', 'trả hàng', 'khách trả']
        
        # Discover Joins across tables
        joins = []
        for t1 in table_names:
            cols1 = tables_dict[t1]['columns']
            g1 = tables_dict[t1]['grain']
            for t2 in table_names:
                if t1 == t2: continue
                cols2 = tables_dict[t2]['columns']
                g2 = tables_dict[t2]['grain']
                pk2 = tables_dict[t2]['primary_key']
                
                # 1. Order join: child -> order / invoice
                order_cols1 = [c for c, meta in cols1.items() if meta['role'] == 'order_id']
                order_cols2 = [c for c, meta in cols2.items() if meta['role'] == 'order_id']
                if order_cols1 and order_cols2 and pk2 and pk2[0] in order_cols2 and g2 in ('order', 'invoice') and g1 in ('order_line', 'payment', 'order_service_table'):
                    joins.append({
                        'id': f'{t1}_to_{t2}',
                        'left_table': t1,
                        'left_columns': [order_cols1[0]],
                        'right_table': t2,
                        'right_columns': [pk2[0]],
                        'cardinality': 'one_to_one' if g1 == 'order_service_table' else 'many_to_one',
                        'description': f'Nối dòng đơn/thanh toán ({t1}) về đơn hàng/hóa đơn ({t2}) theo mã đơn'
                    })
                
                # 2. Goods receipt join: receipt_line -> goods_receipt
                rcpt_cols1 = [c for c in cols1 if any(k in c for k in ('ma_nhap_hang', 'ma_phieu_nhap', 'ma_don_nhap'))]
                rcpt_cols2 = [c for c in cols2 if any(k in c for k in ('ma_nhap_hang', 'ma_phieu_nhap', 'ma_don_nhap'))]
                if rcpt_cols1 and rcpt_cols2 and pk2 and pk2[0] in rcpt_cols2 and g2 == 'goods_receipt' and g1 == 'goods_receipt_line':
                    joins.append({
                        'id': f'{t1}_to_{t2}',
                        'left_table': t1,
                        'left_columns': [rcpt_cols1[0]],
                        'right_table': t2,
                        'right_columns': [pk2[0]],
                        'cardinality': 'many_to_one',
                        'description': f'Nối dòng nhập ({t1}) về phiếu nhập ({t2}) theo mã nhập hàng'
                    })

                # 3. Product join: line / inventory -> product
                prod_cols1 = [c for c, meta in cols1.items() if meta['role'] == 'product_id']
                prod_cols2 = [c for c, meta in cols2.items() if meta['role'] == 'product_id']
                if prod_cols1 and prod_cols2 and pk2 and pk2[0] in prod_cols2 and g2 == 'product' and ('line' in g1 or 'inventory' in g1 or 'price' in g1):
                    joins.append({
                        'id': f'{t1}_to_{t2}',
                        'left_table': t1,
                        'left_columns': [prod_cols1[0]],
                        'right_table': t2,
                        'right_columns': [pk2[0]],
                        'cardinality': 'many_to_one',
                        'description': f'Nối dòng hàng/tồn kho ({t1}) về danh mục sản phẩm ({t2}) theo mã hàng'
                    })
                    
                # 4. Customer join: order -> customer
                cust_cols1 = [c for c, meta in cols1.items() if meta['role'] == 'customer_id']
                cust_cols2 = [c for c, meta in cols2.items() if meta['role'] == 'customer_id']
                if cust_cols1 and cust_cols2 and pk2 and pk2[0] in cust_cols2 and g2 == 'customer' and ('order' in g1 or 'invoice' in g1):
                    joins.append({
                        'id': f'{t1}_to_{t2}',
                        'left_table': t1,
                        'left_columns': [cust_cols1[0]],
                        'right_table': t2,
                        'right_columns': [pk2[0]],
                        'cardinality': 'many_to_one',
                        'description': f'Nối đơn hàng ({t1}) về thông tin khách hàng ({t2}) theo mã khách'
                    })

                # 5. Conversion join: order_line -> unit_conversion
                if g2 == 'unit_conversion' and 'ten_san_pham' in cols1 and 'don_vi_tinh' in cols1:
                    joins.append({
                        'id': f'{t1}_to_{t2}',
                        'left_table': t1,
                        'left_columns': ['ten_san_pham', 'don_vi_tinh'],
                        'right_table': t2,
                        'right_columns': ['ten_san_pham', 'don_vi_quy_doi'],
                        'cardinality': 'many_to_one',
                        'description': f'Nối dòng bán ({t1}) sang bảng quy đổi ({t2}) theo tên sản phẩm và đơn vị tính'
                    })
                    
                # 6. Medicine join: medicine_catalog -> product
                if g1 == 'medicine_catalog' and g2 == 'product':
                    common_p = [c for c in prod_cols1 if c in prod_cols2]
                    if common_p:
                        joins.append({
                            'id': f'{t1}_to_{t2}',
                            'left_table': t1,
                            'left_columns': [common_p[0]],
                            'right_table': t2,
                            'right_columns': [common_p[0]],
                            'cardinality': 'one_to_one',
                            'description': f'Nối thông tin thuốc ({t1}) sang danh mục sản phẩm ({t2}) theo mã sản phẩm'
                        })

    # Dedup joins
    dedup_joins = []
    seen_joins = set()
    for j in joins:
        key = (j['left_table'], tuple(j['left_columns']), j['right_table'], tuple(j['right_columns']))
        if key not in seen_joins:
            seen_joins.add(key)
            dedup_joins.append(j)

    # Compile Golden B01
    golden_b01[biz_id] = {
        'business_id': biz_id,
        'industry': industry,
        'source_files': [f['path'] for f in manifest.get('files', []) if f['status'] == 'discovered'],
        'table_count': len(tables_dict),
        'tables': tables_dict,
        'join_relationships': dedup_joins
    }
    
    # Primary sales and purchase table identification
    sales_tables = [t for t, meta in tables_dict.items() if meta['grain'] in ('order', 'order_line') and not any(k in t for k in ('nhap', 'giao'))]
    purchase_tables = [t for t, meta in tables_dict.items() if meta['grain'] in ('goods_receipt', 'goods_receipt_line')]
    
    primary_sales_table = sales_tables[0] if sales_tables else (table_names[0] if table_names else '')
    primary_purchase_table = purchase_tables[0] if purchase_tables else ''

    # Compile Golden B02
    golden_b02[biz_id] = {
        'business_id': biz_id,
        'industry': industry,
        'as_of_date_cutoff': cutoff_iso,
        'unit_conversions': clean_units,
        'status_rules': {
            'valid_revenue_statuses': valid_sales_statuses,
            'cancelled_statuses': cancelled_statuses,
            'returned_statuses': returned_statuses,
            'return_handling': rules.get('return_handling', 'exclude_entire_order')
        },
        'metric_definitions': {
            'revenue': {
                'description': 'Tổng doanh thu thuần từ các đơn đặt trong kỳ (theo ngày đặt hàng), bỏ đơn hủy và đơn trả hàng.',
                'primary_table': primary_sales_table,
                'formula': 'SUM(thanh_tien) hoặc SUM(so_luong * gia_ban)',
                'rulebook_ref': 'Rulebook §1: Doanh thu một đơn là tổng thành tiền các dòng hàng (đã trừ giảm giá dòng), không trừ giảm giá cả đơn, không cộng VAT/phí ship. Đơn đang giao vẫn tính; bỏ cả đơn trả hàng.'
            },
            'purchase_total': {
                'description': 'Tổng tiền các phiếu nhập kho trong kỳ theo ngày phiếu, bỏ phiếu hủy.',
                'primary_table': primary_purchase_table,
                'formula': 'SUM(can_tra_ncc) hoặc SUM(tong_gia_tri_nhap) hoặc SUM(thanh_tien)',
                'rulebook_ref': 'Rulebook §5: Tiền nhập hàng trong kỳ là tổng tiền các phiếu nhập theo ngày phiếu, bỏ phiếu hủy.'
            },
            'gross_profit': {
                'description': 'Lợi nhuận gộp = Doanh thu hợp lệ trừ đi giá vốn của hàng đã bán.',
                'formula': 'DoanhThu - SUM(so_luong * gia_von)',
                'rulebook_ref': 'Rulebook §5: Lãi gộp = doanh thu trừ giá vốn hàng bán (theo giá vốn ghi trên dòng bán).'
            },
            'order_count': {
                'description': 'Số đơn hàng hợp lệ trong kỳ (không hủy, không trả hàng).',
                'primary_table': primary_sales_table,
                'formula': 'COUNT(DISTINCT order_id)',
                'rulebook_ref': 'Rulebook §1: Chỉ tính đơn không hủy, không trả.'
            },
            'quantity_sold': {
                'description': 'Tổng số lượng bán quy đổi về đơn vị cơ bản.',
                'primary_table': primary_sales_table,
                'formula': 'SUM(so_luong_quy_doi)',
                'rulebook_ref': 'Rulebook §3: Xếp hạng bán chạy theo số lượng quy về đơn vị cơ bản.'
            }
        },
        'special_rules': rules
    }
    
    golden_full[biz_id] = {
        'business_id': biz_id,
        'industry': industry,
        'as_of_date_cutoff': cutoff_iso,
        'b01_schema': golden_b01[biz_id],
        'b02_semantics': golden_b02[biz_id]
    }

out_dir = ROOT / 'data/golden'
out_dir.mkdir(parents=True, exist_ok=True)

(out_dir / 'b01_golden.json').write_text(json.dumps(golden_b01, ensure_ascii=False, indent=2))
(out_dir / 'b02_golden.json').write_text(json.dumps(golden_b02, ensure_ascii=False, indent=2))
(out_dir / 'b01_b02_golden_full.json').write_text(json.dumps(golden_full, ensure_ascii=False, indent=2))

print('Complete Golden dataset generated successfully!')
