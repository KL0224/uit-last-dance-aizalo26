"""Build bundles for all 14 businesses in data/public_test with full B01 & B02 metadata."""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from decimal import Decimal

import duckdb
import pandas as pd

from datamate.ingestion.ingestion import prepare_business

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_TEST_DATA = ROOT / "data/public_test/data"
OUT_DIR = ROOT / "artifacts/b01_b02_full/bundles_public_test"


def extract_dev003_units(duck_file: Path) -> list[dict]:
    units = []
    with duckdb.connect(str(duck_file)) as con:
        tables = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()]
        conv_tbl = next((t for t in tables if "don_vi_quy_doi" in t.lower() or "quydoi" in t.lower()), None)
        prod_tbl = next((t for t in tables if "hang_hoa" in t.lower() or "san_pham" in t.lower()), None)
        if conv_tbl and prod_tbl:
            cols = [c[0] for c in con.execute(f'DESCRIBE "{prod_tbl}"').fetchall()]
            join_conds = ["c.ma_vach = p.ma_h_hoa", "c.ma_vach = p.ma_barcode"]
            if "ma_hang" in cols:
                join_conds.append("c.ma_vach = p.ma_hang")
            join_clause = " OR ".join(join_conds)
            query = f'''
                SELECT p.ten_hang_hoa, c.quy_cach, c.bang, p.dvt
                FROM "{conv_tbl}" c
                JOIN "{prod_tbl}" p ON ({join_clause})
            '''
            try:
                rows = con.execute(query).fetchall()
                for r in rows:
                    if r[0] and r[1] and r[2] and r[3]:
                        units.append({
                            "item_name": str(r[0]).strip(),
                            "from_unit": str(r[1]).strip(),
                            "factor": str(float(r[2])),
                            "to_unit": str(r[3]).strip(),
                            "source": conv_tbl,
                            "status": "database_verified",
                        })
            except Exception as e:
                print(f"Error extracting dev003 units: {e}")
    return units


def extract_dev005_units(dev_dir: Path) -> list[dict]:
    units = []
    xlsx = dev_dir / "DanhSachQuyDoi.xlsx"
    if not xlsx.exists():
        return units
    df = pd.read_excel(xlsx)
    conversions = {}
    for idx, r in df.iterrows():
        prod = str(r.iloc[0]).strip()
        from_u = str(r.iloc[1]).strip()
        ti_le_str = str(r.iloc[2]).strip()
        base_u = str(r.iloc[3]).strip()
        
        try:
            factor = float(ti_le_str.replace(",", "."))
            conversions[(prod, from_u)] = factor
            units.append({
                "item_name": prod,
                "from_unit": from_u,
                "factor": str(factor),
                "to_unit": base_u,
                "source": "DanhSachQuyDoi.xlsx",
                "status": "source_verified",
            })
        except ValueError:
            m = re.match(r'([0-9.,]+)\s*(.*)', ti_le_str)
            if m:
                num = float(m.group(1).replace(",", "."))
                inter_u = m.group(2).strip()
                if (prod, inter_u) in conversions:
                    factor = num * conversions[(prod, inter_u)]
                    conversions[(prod, from_u)] = factor
                    units.append({
                        "item_name": prod,
                        "from_unit": from_u,
                        "factor": str(factor),
                        "to_unit": base_u,
                        "source": "DanhSachQuyDoi.xlsx",
                        "status": "source_verified",
                    })
    return units


def extract_dev013_units(dev_dir: Path) -> list[dict]:
    units = []
    xlsx = dev_dir / "QuanLy.xlsx"
    if not xlsx.exists():
        return units
    try:
        df = pd.read_excel(xlsx, sheet_name="DanhMuc")
        if "Quy đổi" in df.columns and "Tên hàng" in df.columns and "ĐVT" in df.columns:
            for idx, r in df.iterrows():
                if pd.isna(r["Quy đổi"]):
                    continue
                item = str(r["Tên hàng"]).strip()
                base_u = str(r["ĐVT"]).strip()
                txt = str(r["Quy đổi"]).strip()
                parts = [p.strip() for p in txt.split(";") if p.strip()]
                for p in parts:
                    m = re.match(r'1\s+([^=]+)\s*=\s*([0-9.,]+)\s+([^\s]+)', p)
                    if m:
                        from_u = m.group(1).strip()
                        factor = float(m.group(2).replace(",", "."))
                        target_u = m.group(3).strip()
                        units.append({
                            "item_name": item,
                            "from_unit": from_u,
                            "factor": str(factor),
                            "to_unit": base_u,
                            "source": "QuanLy.xlsx (DanhMuc)",
                            "status": "source_verified",
                        })
    except Exception as e:
        print(f"Error extracting dev013 units: {e}")
    return units


def extract_dev004_units(dev_dir: Path) -> list[dict]:
    # dev_004 README: Ống PVC Bình Minh D32 cây 4m, Ống PVC Bình Minh D50 cây 4m, Ống PVC Bình Minh D90 cây 4m bán theo bó, 1 bó = 10 cây
    units = [
        {"item_name": "Ống PVC Bình Minh D32 cây 4m", "from_unit": "bó", "factor": "10.0", "to_unit": "cây", "source": "README.md", "status": "source_verified"},
        {"item_name": "Ống PVC Bình Minh D50 cây 4m", "from_unit": "bó", "factor": "10.0", "to_unit": "cây", "source": "README.md", "status": "source_verified"},
        {"item_name": "Ống PVC Bình Minh D90 cây 4m", "from_unit": "bó", "factor": "10.0", "to_unit": "cây", "source": "README.md", "status": "source_verified"},
    ]
    return units


def extract_dev_readme_units(dev_dir: Path) -> list[dict]:
    readme = dev_dir / "README.md"
    if not readme.exists():
        return []
    text = readme.read_text(encoding="utf-8")
    units = []
    current_item = None
    for line in text.splitlines():
        line_str = line.strip()
        m1 = re.match(r'^[-\*\s]*([^:]+):\s*1\s+([^=]+)\s*=\s*([0-9.,]+)\s+([^\s]+)', line_str)
        if m1:
            item = m1.group(1).strip().strip('*` ')
            from_u = m1.group(2).strip()
            factor = float(m1.group(3).replace(",", "."))
            to_u = m1.group(4).strip()
            units.append({
                "item_name": item,
                "from_unit": from_u,
                "factor": str(factor),
                "to_unit": to_u,
                "source": "README.md",
                "status": "source_verified",
            })
        elif line_str.startswith("-") and ":" in line_str and not ("=" in line_str):
            current_item = line_str.split(":", 1)[0].lstrip("-* ").strip("*` ")
        elif current_item and ("=" in line_str):
            m2 = re.search(r'1\s+([^=]+)\s*=\s*([0-9.,]+)\s+([^\s]+)', line_str)
            if m2:
                from_u = m2.group(1).strip()
                factor = float(m2.group(2).replace(",", "."))
                to_u = m2.group(3).strip()
                units.append({
                    "item_name": current_item,
                    "from_unit": from_u,
                    "factor": str(factor),
                    "to_unit": to_u,
                    "source": "README.md",
                    "status": "source_verified",
                })
    return units


def main():
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    businesses = sorted([p for p in PUBLIC_TEST_DATA.iterdir() if p.is_dir() and p.name.startswith("dev_")])
    print(f"Bắt đầu chuẩn bị {len(businesses)} doanh nghiệp public test vào {OUT_DIR}...")

    results = []
    start_time = time.time()
    for idx, biz_path in enumerate(businesses):
        biz_id = biz_path.name
        t0 = time.time()
        biz_out = OUT_DIR / biz_id
        artifact = prepare_business(biz_path, biz_out)
        bundle_dir = artifact.bundle_dir
        ctx_file = bundle_dir / "business_context.json"
        ctx = json.loads(ctx_file.read_text())
        duck_file = bundle_dir / "data.duckdb"

        # Thu thập unit conversions
        existing_units = list(ctx.get("semantic_catalog", {}).get("unit_conversions", []))
        
        # Bổ sung đơn vị từ README
        readme_units = extract_dev_readme_units(biz_path)
        for ru in readme_units:
            existing_units.append(ru)

        # Bổ sung theo logic từng dev đặc thù
        if biz_id == "dev_003":
            for u in extract_dev003_units(duck_file):
                existing_units.append(u)
        elif biz_id == "dev_004":
            for u in extract_dev004_units(biz_path):
                existing_units.append(u)
        elif biz_id == "dev_005":
            for u in extract_dev005_units(biz_path):
                existing_units.append(u)
        elif biz_id == "dev_013":
            for u in extract_dev013_units(biz_path):
                existing_units.append(u)

        # Check DB quy_doi tables (like dev_002)
        with duckdb.connect(str(duck_file)) as con:
            tables = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()]
            conv_tables = [t for t in tables if "quy_doi" in t.lower() and t != "unit_conversions"]
            for ct in conv_tables:
                col_tuples = con.execute(f'PRAGMA table_info("{ct}")').fetchall()
                cols = [c[1] for c in col_tuples]
                if "ten_san_pham" in cols and "don_vi_quy_doi" in cols and "ti_le_quy_doi" in cols and "don_vi_co_ban" in cols:
                    rows = con.execute(f'SELECT ten_san_pham, don_vi_quy_doi, ti_le_quy_doi, don_vi_co_ban FROM "{ct}"').fetchall()
                    for r in rows:
                        if r[0] and r[1] and r[2] and r[3]:
                            try:
                                f_val = float(str(r[2]).replace(",", "."))
                                existing_units.append({
                                    "item_name": str(r[0]),
                                    "from_unit": str(r[1]),
                                    "factor": str(f_val),
                                    "to_unit": str(r[3]),
                                    "source": ct,
                                    "status": "database_verified",
                                })
                            except ValueError:
                                pass

        # Deduplicate units
        seen_keys = set()
        clean_units = []
        for u in existing_units:
            k = (str(u["item_name"]).strip().lower(), str(u["from_unit"]).strip().lower(), str(u["to_unit"]).strip().lower())
            if k not in seen_keys:
                seen_keys.add(k)
                clean_units.append(u)

        # Sync back to DuckDB unit_conversions table (bidirectional)
        with duckdb.connect(str(duck_file)) as con:
            if clean_units:
                seen_pairs = set()
                bidi_units = []
                for u in clean_units:
                    item = str(u.get("item_name", "")).strip()
                    f_u = str(u.get("from_unit", "")).strip()
                    t_u = str(u.get("to_unit", "")).strip()
                    try:
                        factor = float(u.get("factor", 1.0))
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

        # Update business_context.json
        ctx.setdefault("semantic_catalog", {})["unit_conversions"] = clean_units
        
        # Ensure unit_conversions in schema_catalog.tables if not present
        existing_tables = list(ctx.get("schema_catalog", {}).get("tables", []))
        existing_names = {t["name"] for t in existing_tables}
        if clean_units and "unit_conversions" not in existing_names:
            existing_tables.append({
                "name": "unit_conversions",
                "columns": [
                    {"name": "item_name", "data_type": "VARCHAR", "nullable": False},
                    {"name": "from_unit", "data_type": "VARCHAR", "nullable": False},
                    {"name": "to_unit", "data_type": "VARCHAR", "nullable": False},
                    {"name": "factor", "data_type": "DECIMAL(38,12)", "nullable": False},
                ],
                "row_count": len(clean_units),
                "grain": "Quy đổi đơn vị tính (1 from_unit = factor to_unit)",
                "provenance": "B02 semantic unit conversions",
            })
            ctx.setdefault("schema_catalog", {})["tables"] = existing_tables

        ctx_file.write_text(json.dumps(ctx, ensure_ascii=False, indent=2) + "\n")

        joins_count = len(ctx.get("schema_catalog", {}).get("join_graph", []))
        units_count = len(clean_units)
        elapsed = time.time() - t0
        print(f"[{idx+1:02d}/{len(businesses)}] {biz_id}: {joins_count} joins, {units_count} units ({elapsed:.2f}s)")
        results.append({
            "business_id": biz_id,
            "bundle_dir": str(bundle_dir),
            "joins_count": joins_count,
            "units_count": units_count,
            "elapsed_seconds": round(elapsed, 2),
        })

    total_elapsed = time.time() - start_time
    report_file = ROOT / "artifacts/b01_b02_full/preparation_public_test.json"
    report_file.write_text(json.dumps({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_businesses": len(businesses),
        "total_elapsed_seconds": round(total_elapsed, 2),
        "results": results,
    }, ensure_ascii=False, indent=2))
    print(f"\nHoàn tất chuẩn bị {len(businesses)} bundles public test trong {total_elapsed:.2f} giây.")


if __name__ == "__main__":
    main()
