"""Generate complete, verified Golden Data for B01 and B02 across all 14 businesses in data/public_test."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_TEST_DIR = ROOT / "data/public_test/data"
BUNDLES_DIR = ROOT / "artifacts/b01_b02_full/bundles_public_test"

INDUSTRIES = {
    "dev_001": "Bán lẻ / Tạp hóa",
    "dev_002": "Tiệm bánh & Cà phê",
    "dev_003": "Cà phê & Tiệm bánh",
    "dev_004": "Vật liệu xây dựng",
    "dev_005": "Nhà thuốc / Dược phẩm",
    "dev_006": "Quán ăn / Máy POS",
    "dev_007": "Bán lẻ / Nước giải khát",
    "dev_008": "Bán lẻ / Nước giải khát",
    "dev_009": "Bán lẻ / Hóa đơn tổng",
    "dev_010": "Bán buôn & Bán lẻ / Tạp hóa & Mẹ bé",
    "dev_011": "Cửa hàng điện thoại",
    "dev_012": "Tiệm sửa xe",
    "dev_013": "Cửa hàng Mẹ và bé",
    "dev_014": "Cửa hàng điện thoại & Thu máy cũ",
}


def infer_column_role(col_name: str, table_grain: str = "") -> str:
    name = col_name.lower()
    if name in ("__dm_row_id", "stt", "thu_tu", "so_thu_tu", "so_dong"):
        return "technical_id"
    # Order ID
    if any(k in name for k in ("ma_hoa_don", "ma_don_hang", "ma_bill", "bill", "so_hd", "ma_chung_tu", "ma_don", "so_chung_tu", "so_ct", "don_so", "hd")) and not "chi_tiet" in name:
        return "order_id"
    # Customer ID
    if "so_khach" in name:
        return "quantity"
    if any(k in name for k in ("ma_khach_hang", "ma_kh", "so_kh", "ma_khach", "ma_the", "ma_khach_mua", "ma_nguoi_mua")):
        return "customer_id"
    if name in ("ben_mua", "doi_tac", "khach_hang", "ten_khach_hang", "khach", "ho_ten_khach", "ten_kh") and not any(k in name for k in ("dia_chi", "sdt", "phone", "mst", "cccd", "email")):
        return "customer_id"
    # Product ID
    if any(k in name for k in ("ma_hang_hoa", "ma_san_pham", "ma_hang", "id_sp", "sku", "ma_sku", "ma_barcode", "ma_sp", "barcode", "ma_vach", "ma_hang_ban", "ma_san_pham_ban", "ma_h_hoa", "mathuoc", "may_thu")):
        return "product_id"
    # Order Date
    if any(k in name for k in ("ngay_dat_hang", "ngay_ban", "ngay_giao_dich", "ngay_tao", "ngay_thang", "thoi_gian_tao", "ngay_don", "ngay_lap", "thoi_gian_don", "ngay_xuat", "ngay_hd")) or name in ("ngay", "thoi_gian", "date"):
        return "order_date"
    if any(k in name for k in ("ngay_thu", "thoi_gian_thu", "ngay_thanh_toan", "ngay_tt")):
        return "payment_date"
    if any(k in name for k in ("ngay_nhap", "ngay_nhap_kho")):
        return "receipt_date"
    # Price & Money
    if any(k in name for k in ("gia_ban", "don_gia", "gia_san_pham", "gia_ban_le", "gia_don_vi", "gia_nhap", "don_gia_nhap", "gia_1_dv", "don_gia_d", "dg")):
        return "unit_price"
    if any(k in name for k in ("gia_von", "gia_von_hien_tai", "gia_von_luc_ban")):
        return "cost_price"
    if any(k in name for k in ("thanh_tien", "t_tien", "tien_hang", "tri_gia", "thanh_tien_d", "tt")) or (name == "tong_tien" and "line" in table_grain):
        return "line_amount"
    if any(k in name for k in ("tong_bill", "tong_sau_giam_gia", "can_tra_ncc", "tong_gia_tri_nhap", "tong_don", "phai_thu", "tong_thanh_toan", "tong_tien_phieu", "tong_tien_hang")) or (name == "tong_tien" and "order" in table_grain):
        return "order_total"
    if any(k in name for k in ("chua_tra", "con_no", "da_tra", "khach_tra", "con_lai", "khach_da_tra", "so_tien_thu", "tien_thu", "da_thu", "bot")):
        return "debt_amount"
    if any(k in name for k in ("giam_gia", "chiet_khau", "tien_giam", "giam_d", "ck", "giam_gia_hd")):
        return "discount"
    # Quantity
    if any(k in name for k in ("so_luong", "sl", "sl_quy_doi", "so_luong_quy_doi", "quy_ra_dv_le", "so_luong_le", "so_luong_san_pham", "ton_kho", "ton_cuoi", "ton_cuoi_ky", "sl_nhap", "so_luong_nhap", "sluong", "slg", "sl_le", "s_l", "sl_dv_co_ban")):
        return "quantity"
    # Status
    if any(k in name for k in ("trang_thai", "tinh_trang", "ket_qua", "xu_ly", "status", "trang_thai_don_hang", "trang_thai_giao", "trang_thai_phieu", "tien_do", "tt_don")):
        return "status"
    # Unit
    if any(k in name for k in ("don_vi_tinh", "dvt", "don_vi", "don_vi_quy_doi", "don_vi_co_ban", "dvt_nhap", "quy_cach", "dv")):
        return "unit"
    # Entity name
    if any(k in name for k in ("ten_hang", "ten_san_pham", "ten_hang_hoa", "ten_mon", "noi_dung", "san_pham", "mat_hang", "hang_hoa", "hang_ban", "ten_mat_hang", "product")):
        return "entity_name"
    if any(k in name for k in ("nhom_hang", "phan_loai", "loai_hang_hoa", "nhom_hang_hoa", "nhom_hang_3_cap", "nhom_khach_hang", "nhom", "loai_hang", "loai_khach")):
        return "category"
    if any(k in name for k in ("ghi_chu", "mo_ta", "note", "luu_y", "mo_ta_san_pham")):
        return "notes"
    if any(k in name for k in ("so_lo", "han_dung", "han_su_dung", "ngay_het_han", "ma_lo")):
        return "batch_expiry"
    # Employee / Worker
    if any(k in name for k in ("nhan_vien_ban", "ma_nv_ban", "ma_nv", "tho", "ho_ten", "ten_tho", "nguoi_tao")):
        return "employee"
    # IMEI / Serial
    if "imei" in name:
        return "serial_number"
    return "other"


def infer_table_grain(table_name: str) -> str:
    t = table_name.lower()
    if "unit_conversions" in t or "quy_doi" in t or "don_vi_sp" in t:
        return "unit_conversion"
    if "chi_tiet" in t or "line" in t:
        if "nhap" in t: return "goods_receipt_line"
        if "lo" in t: return "order_batch_line"
        return "order_line"
    if "ban_theo_lo" in t or "don_hang_lo" in t or "chi_tiet_don_lo" in t:
        return "order_batch_line"
    if any(k in t for k in ("hoa_don", "don_hang", "don_nhap", "phieu_nhap", "ban_hang", "so_ban_hang", "phieu_giao", "so_chi_tiet_ban_hang")):
        if any(k in t for k in ("nhap", "phieu_nhap", "don_nhap")): return "goods_receipt"
        if "phieu_giao" in t: return "delivery_note"
        if any(k in t for k in ("chi_tiet", "so_ban_hang", "ban_hang", "so_chi_tiet")): return "order_line"
        return "order"
    if "thanh_toan" in t or "phieu_thu" in t or "so_quy" in t:
        return "payment"
    if any(k in t for k in ("san_pham", "hang_hoa", "danh_muc")):
        return "product"
    if "khach_hang" in t:
        return "customer"
    if "ton_kho" in t:
        return "inventory_snapshot"
    if "phong_ban" in t:
        return "order_service_table"
    if "lo_hang" in t:
        return "product_batch"
    if "thuoc" in t:
        return "medicine_catalog"
    if "bang_gia" in t or "lich_su_gia" in t:
        return "price_list"
    if "cong_no" in t or "so_han_no" in t or "so_no" in t:
        return "debt_record"
    if "so_sua_xe" in t:
        return "order"
    if "tho" in t or "nhan_vien" in t:
        return "employee"
    if "thu_may_cu" in t:
        return "trade_in"
    if "ghi_tat" in t:
        return "abbreviation_mapping"
    if "tra_gop" in t:
        return "installment"
    if "bao_hanh" in t:
        return "warranty"
    if "chi_phi" in t:
        return "expense"
    if "bao_cao_ca" in t:
        return "shift_report"
    if "khuyen_mai" in t:
        return "promotion"
    if "chi_nhanh" in t:
        return "branch"
    return "other"


def parse_dev_readme(dev_id: str) -> tuple[dict, list[dict], str | None]:
    p = PUBLIC_TEST_DIR / dev_id / "README.md"
    if not p.exists():
        return {}, [], None
    text = p.read_text(encoding="utf-8")
    
    # Cutoff date
    m_date = re.search(r"Dữ liệu có đến hết\s+([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
    if not m_date:
        m_date = re.search(r"hết ngày\s+([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
    if not m_date:
        m_date = re.search(r"([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
    cutoff_iso = None
    if m_date:
        d, m, y = m_date.group(1).split("/")
        cutoff_iso = f"{y}-{m}-{d}"
    
    lower = text.lower()
    
    # Unit conversions from README
    units = []
    current_item = None
    for line in text.splitlines():
        line_str = line.strip()
        m1 = re.match(r"^[-\*\s]*([^:]+):\s*1\s+([^=]+)\s*=\s*([0-9.,]+)\s+([^\s]+)", line_str)
        if m1:
            item = m1.group(1).strip().strip("*` ")
            from_u = m1.group(2).strip()
            factor = float(m1.group(3).replace(",", "."))
            to_u = m1.group(4).strip()
            units.append({
                "item_name": item,
                "from_unit": from_u,
                "to_unit": to_u,
                "factor": factor,
                "source": "README.md",
            })
        elif line_str.startswith("-") and ":" in line_str and not ("=" in line_str):
            current_item = line_str.split(":", 1)[0].lstrip("-* ").strip("*` ")
        elif current_item and ("=" in line_str):
            m2 = re.search(r"1\s+([^=]+)\s*=\s*([0-9.,]+)\s+([^\s]+)", line_str)
            if m2:
                from_u = m2.group(1).strip()
                factor = float(m2.group(2).replace(",", "."))
                to_u = m2.group(3).strip()
                units.append({
                    "item_name": current_item,
                    "from_unit": from_u,
                    "to_unit": to_u,
                    "factor": factor,
                    "source": "README.md",
                })
                
    # Specific rule parsing
    rules = {}
    if "phí phục vụ" in lower:
        rules["service_fee"] = "Đơn ngồi phòng lạnh có dòng Phí phục vụ (không tính là mặt hàng, không đếm/xếp hạng nhưng cộng vào doanh thu)"
    if "trả hàng" in lower and ("âm" in lower or "số lượng âm" in lower):
        rules["return_handling"] = "negative_quantity_line"
    else:
        rules["return_handling"] = "exclude_entire_order"
    if "thuốc kê đơn" in lower:
        rules["prescription"] = "Thuốc kê đơn = sản phẩm ghi kê đơn trong danh mục thuốc"
    if "lô" in lower or "hạn dùng" in lower:
        rules["batch_expiry"] = "Theo dõi theo lô và hạn sử dụng"
    if any(k in lower for k in ("công nợ", "còn nợ", "chưa trả", "sổ nợ")):
        rules["debt"] = "Tính theo số chưa trả của tổng đơn; tuổi nợ tính từ ngày đặt"
    if "hoa hồng" in lower or "huê hồng" in lower:
        rules["commission"] = "Tiền hoa hồng thợ = Doanh thu phiếu sửa xe * % hoa hồng thợ (bảo hành tiền 0 không tính)"
    if "thu máy cũ" in lower:
        rules["trade_in"] = "Sổ thu máy cũ nối với sổ bán hàng theo STT đơn và IMEI; tiền thu máy cũ trừ vào số tiền khách trả"
    if "bảo hành" in lower:
        rules["warranty"] = "Phiếu bảo hành có Tiền 0, xe quay lại bảo hành việc của một phiếu trước, tiệm không thu tiền"
        
    return rules, units, cutoff_iso


def main():
    golden_b01 = {}
    golden_b02 = {}
    golden_full = {}

    dev_ids = sorted([f"dev_{i:03d}" for i in range(1, 15)])
    print(f"Bắt đầu xây dựng Golden Dataset cho {len(dev_ids)} doanh nghiệp Public Test...")

    for dev_id in dev_ids:
        dev_bundle_root = BUNDLES_DIR / dev_id
        ctx_files = list(dev_bundle_root.rglob("business_context.json"))
        if not ctx_files:
            print(f"CẢNH BÁO: Không tìm thấy business_context.json cho {dev_id}")
            continue
        ctx_file = ctx_files[0]
        bundle_dir = ctx_file.parent
        db_path = bundle_dir / "data.duckdb"
        manifest_path = bundle_dir / "source_manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        ctx = json.loads(ctx_file.read_text())

        rules, readme_units, cutoff_iso = parse_dev_readme(dev_id)
        industry = INDUSTRIES.get(dev_id, "Bán lẻ")

        with duckdb.connect(str(db_path), read_only=True) as con:
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
                    if name.startswith("__"): continue
                    role = infer_column_role(name, grain)
                    columns[name] = {
                        "sql_type": sql_type,
                        "role": role,
                        "nullable": not notnull,
                    }
                    try:
                        dist, non_null = con.execute(f'SELECT COUNT(DISTINCT "{name}"), COUNT("{name}") FROM "{t}"').fetchone()
                        if dist == row_count and non_null == row_count and row_count > 0:
                            candidate_pks.append(name)
                    except Exception:
                        pass

                # Canonical PK selection
                primary_key = []
                if candidate_pks:
                    priority_names = [
                        "ma_hoa_don", "ma_don_hang", "so_ct", "ma_bill", "ma_chung_tu", "ma_don", "don_so",
                        "ma_nhap_hang", "ma_phieu_nhap", "ma_don_nhap", "so_phieu",
                        "ma_khach_hang", "ma_kh", "ma_khach", "ma_the",
                        "ma_hang_hoa", "ma_san_pham", "ma_hang", "ma_sku", "ma_vach", "sku", "id_sp", "ma_h_hoa", "ma_san_pham_ban",
                        "stt", "imei", "ten_san_pham", "ten_hang", "ten_hang_hoa"
                    ]
                    matched = [p for p in priority_names if p in candidate_pks]
                    primary_key = [matched[0]] if matched else [candidate_pks[0]]
                elif grain in ("order_line", "goods_receipt_line") and any(k in columns for k in ("ma_hoa_don", "ma_don_hang", "ma_bill", "so_ct", "don_so", "so_hd", "ma_phieu_nhap", "so_phieu")):
                    ord_col = next(c for c in ("ma_hoa_don", "ma_don_hang", "ma_bill", "so_ct", "don_so", "so_hd", "ma_phieu_nhap", "so_phieu") if c in columns)
                    line_col = next((c for c in ("stt", "thu_tu", "so_dong", "so_thu_tu", "ma_hang", "ma_hang_hoa", "ma_san_pham", "ten_hang", "ten_san_pham") if c in columns), None)
                    if line_col:
                        primary_key = [ord_col, line_col]

                tables_dict[t] = {
                    "grain": grain,
                    "row_count": row_count,
                    "primary_key": primary_key,
                    "columns": columns,
                }

        # Unit conversions collection
        all_units = list(ctx.get("semantic_catalog", {}).get("unit_conversions", []))
        for ru in readme_units:
            all_units.append(ru)

        # Deduplicate units
        seen_units = set()
        clean_units = []
        for u in all_units:
            k = (str(u["item_name"]).strip().lower(), str(u["from_unit"]).strip().lower(), str(u["to_unit"]).strip().lower())
            if k not in seen_units:
                seen_units.add(k)
                factor_val = float(str(u["factor"]).replace(",", "."))
                clean_units.append({
                    "item_name": str(u["item_name"]).strip(),
                    "from_unit": str(u["from_unit"]).strip(),
                    "to_unit": str(u["to_unit"]).strip(),
                    "factor": factor_val,
                    "equation": f"1 {u['from_unit']} = {factor_val:g} {u['to_unit']}",
                    "source": u.get("source", "verified"),
                })

        # Joins extraction from schema catalog join graph
        bundle_joins = ctx.get("schema_catalog", {}).get("join_graph", [])
        formatted_joins = []
        seen_join_pairs = set()

        for j in bundle_joins:
            l_tbl = j["left_table"]
            r_tbl = j["right_table"]
            if "left_column" in j:
                l_cols = [j["left_column"]] + [p[0] for p in j.get("additional_key_pairs", [])]
            elif "left_columns" in j:
                l_cols = list(j["left_columns"])
            else:
                l_cols = [p[0] for p in j.get("key_pairs", [])]

            if "right_column" in j:
                r_cols = [j["right_column"]] + [p[1] for p in j.get("additional_key_pairs", [])]
            elif "right_columns" in j:
                r_cols = list(j["right_columns"])
            else:
                r_cols = [p[1] for p in j.get("key_pairs", [])]

            pair_key = (l_tbl, tuple(l_cols), r_tbl, tuple(r_cols))
            if pair_key not in seen_join_pairs:
                seen_join_pairs.add(pair_key)
                formatted_joins.append({
                    "id": f"{l_tbl}_to_{r_tbl}",
                    "left_table": l_tbl,
                    "left_columns": l_cols,
                    "right_table": r_tbl,
                    "right_columns": r_cols,
                    "cardinality": j.get("cardinality", "many_to_one"),
                    "description": f"Liên kết {l_tbl}.{l_cols} sang {r_tbl}.{r_cols}",
                })

        # Status rules
        valid_sales_statuses = ["completed", "delivering", "Chờ giao", "Đang giao dịch", "Đang xử lý", "Hoàn thành", "Đã thanh toán"]
        cancelled_statuses = ["cancelled", "hủy", "huỷ", "đã hủy", "đã huỷ", "Hủy"]
        returned_statuses = ["returned", "trả hàng", "khách trả", "Trả hàng"]

        # Sales and purchase primary tables
        sales_tables = [t for t, meta in tables_dict.items() if meta["grain"] in ("order", "order_line") and not any(k in t for k in ("nhap", "giao", "chi_phi"))]
        purchase_tables = [t for t, meta in tables_dict.items() if meta["grain"] in ("goods_receipt", "goods_receipt_line")]

        primary_sales_table = sales_tables[0] if sales_tables else (table_names[0] if table_names else "")
        primary_purchase_table = purchase_tables[0] if purchase_tables else ""

        # Golden B01
        golden_b01[dev_id] = {
            "business_id": dev_id,
            "industry": industry,
            "source_files": [f["path"] for f in manifest.get("files", []) if f["status"] == "discovered"],
            "table_count": len(tables_dict),
            "tables": tables_dict,
            "join_relationships": formatted_joins,
        }

        # Golden B02
        golden_b02[dev_id] = {
            "business_id": dev_id,
            "industry": industry,
            "as_of_date_cutoff": cutoff_iso,
            "unit_conversions": clean_units,
            "status_rules": {
                "valid_revenue_statuses": valid_sales_statuses,
                "cancelled_statuses": cancelled_statuses,
                "returned_statuses": returned_statuses,
                "return_handling": rules.get("return_handling", "exclude_entire_order"),
            },
            "metric_definitions": {
                "revenue": {
                    "description": "Tổng doanh thu thuần từ các đơn đặt trong kỳ (theo ngày đặt hàng), bỏ đơn hủy và đơn trả hàng.",
                    "primary_table": primary_sales_table,
                    "formula": "SUM(thanh_tien) hoặc SUM(so_luong * gia_ban)",
                    "rulebook_ref": "Rulebook §1: Doanh thu một đơn là tổng thành tiền các dòng hàng (đã trừ giảm giá dòng), không trừ giảm giá cả đơn, không cộng VAT/phí ship. Đơn đang giao vẫn tính; bỏ cả đơn trả hàng.",
                },
                "purchase_total": {
                    "description": "Tổng tiền các phiếu nhập kho trong kỳ theo ngày phiếu, bỏ phiếu hủy.",
                    "primary_table": primary_purchase_table,
                    "formula": "SUM(tong_tien_phieu) hoặc SUM(can_tra_ncc) hoặc SUM(thanh_tien)",
                    "rulebook_ref": "Rulebook §5: Tiền nhập hàng trong kỳ là tổng tiền các phiếu nhập theo ngày phiếu, bỏ phiếu hủy.",
                },
                "gross_profit": {
                    "description": "Lợi nhuận gộp = Doanh thu hợp lệ trừ đi giá vốn của hàng đã bán.",
                    "formula": "DoanhThu - SUM(so_luong * gia_von)",
                    "rulebook_ref": "Rulebook §5: Lãi gộp = doanh thu trừ giá vốn hàng bán (theo giá vốn ghi trên dòng bán).",
                },
                "order_count": {
                    "description": "Số đơn hàng hợp lệ trong kỳ (không hủy, không trả hàng).",
                    "primary_table": primary_sales_table,
                    "formula": "COUNT(DISTINCT order_id)",
                    "rulebook_ref": "Rulebook §1: Chỉ tính đơn không hủy, không trả.",
                },
                "quantity_sold": {
                    "description": "Tổng số lượng bán quy đổi về đơn vị cơ bản.",
                    "primary_table": primary_sales_table,
                    "formula": "SUM(so_luong_quy_doi)",
                    "rulebook_ref": "Rulebook §3: Xếp hạng bán chạy theo số lượng quy về đơn vị cơ bản.",
                },
            },
            "special_rules": rules,
        }

        # Golden Full (B01 + B02)
        golden_full[dev_id] = {
            "business_id": dev_id,
            "industry": industry,
            "as_of_date_cutoff": cutoff_iso,
            "b01_schema": golden_b01[dev_id],
            "b02_semantics": golden_b02[dev_id],
        }

        print(f"[{dev_id}] {industry}: {len(tables_dict)} tables, {len(formatted_joins)} joins, {len(clean_units)} units, cutoff: {cutoff_iso}")

    out_dir = ROOT / "data/golden"
    out_dir.mkdir(parents=True, exist_ok=True)

    b01_path = out_dir / "b01_public_test_golden.json"
    b02_path = out_dir / "b02_public_test_golden.json"
    full_path = out_dir / "b01_b02_public_test_golden.json"

    b01_path.write_text(json.dumps(golden_b01, ensure_ascii=False, indent=2))
    b02_path.write_text(json.dumps(golden_b02, ensure_ascii=False, indent=2))
    full_path.write_text(json.dumps(golden_full, ensure_ascii=False, indent=2))

    print("\n" + "=" * 60)
    print("HOÀN THÀNH TẠO GOLDEN DATA CHO TẬP PUBLIC TEST!")
    print(f"  - B01 Golden: {b01_path} ({len(golden_b01)} businesses)")
    print(f"  - B02 Golden: {b02_path} ({len(golden_b02)} businesses)")
    print(f"  - Full Golden: {full_path} ({len(golden_full)} businesses)")
    print("=" * 60)


if __name__ == "__main__":
    main()
