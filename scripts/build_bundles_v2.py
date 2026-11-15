"""Rebuild all 30 business bundles with improved B01 schema and B02 semantics."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import duckdb

from datamate.ingestion.ingestion import prepare_business

ROOT = Path(__file__).resolve().parent.parent
TRAIN_DATA = ROOT / "data/train/data"
OUT_DIR = ROOT / "artifacts/b01_b02_full/bundles_v2"


def main():
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    businesses = sorted([p for p in TRAIN_DATA.iterdir() if p.is_dir() and p.name.startswith("biz_")])
    print(f"Bắt đầu chuẩn bị {len(businesses)} doanh nghiệp vào {OUT_DIR}...")

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

        # Bổ sung đơn vị quy đổi từ bảng DB nếu có
        existing_units = list(ctx.get("semantic_catalog", {}).get("unit_conversions", []))
        seen_keys = {
            (u["item_name"].strip().lower(), u["from_unit"].strip().lower(), u["to_unit"].strip().lower())
            for u in existing_units
        }

        with duckdb.connect(str(duck_file)) as con:
            tables = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()]
            conv_tables = [t for t in tables if "quy_doi" in t.lower()]
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
                                existing_units.append({
                                    "item_name": str(r[0]),
                                    "from_unit": str(r[1]),
                                    "factor": str(r[2]),
                                    "to_unit": str(r[3]),
                                    "status": "database_verified",
                                })
                elif "ma_sp" in cols and "don_vi" in cols and "bang" in cols:
                    prod_tables = [t for t in tables if any(k in t for k in ("hang_hoa", "san_pham"))]
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
                                        existing_units.append({
                                            "item_name": str(r[0]),
                                            "from_unit": str(r[1]),
                                            "factor": str(r[2]),
                                            "to_unit": str(r[3]),
                                            "status": "database_verified",
                                        })

            # Đồng bộ lại bảng unit_conversions trong DuckDB
            if existing_units:
                con.execute("CREATE TABLE IF NOT EXISTS main.unit_conversions (item_name VARCHAR, from_unit VARCHAR, to_unit VARCHAR, factor DECIMAL(38,12))")
                con.execute("DELETE FROM main.unit_conversions")
                for u in existing_units:
                    con.execute(
                        "INSERT INTO main.unit_conversions VALUES (?, ?, ?, ?)",
                        [str(u["item_name"]), str(u["from_unit"]), str(u["to_unit"]), float(u["factor"])],
                    )

        ctx.setdefault("semantic_catalog", {})["unit_conversions"] = existing_units
        ctx_file.write_text(json.dumps(ctx, ensure_ascii=False, indent=2) + "\n")

        joins_count = len(ctx.get("schema_catalog", {}).get("join_graph", []))
        units_count = len(existing_units)
        elapsed = time.time() - t0
        print(f"[{idx+1:02d}/30] {biz_id}: {joins_count} joins, {units_count} units ({elapsed:.2f}s)")

    total_elapsed = time.time() - start_time
    print(f"\nHoàn tất chuẩn bị 30 bundles trong {total_elapsed:.2f} giây.")


if __name__ == "__main__":
    main()
