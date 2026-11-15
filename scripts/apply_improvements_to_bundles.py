"""Apply improved B01 join discovery and B02 semantic unit conversions across all 30 business bundles."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import duckdb

from datamate.context.contracts import BusinessRule, SemanticCatalog
from datamate.context.semantic_extractor import RuleSchemaMatcher
from datamate.context.verified_semantics import verified_merge
from datamate.ingestion.contracts import ColumnMetadata, SchemaCatalog, TableMetadata
from datamate.ingestion.ingestion.profiling import DuckDBProfileProvider
from datamate.ingestion.schema_catalog import SchemaCatalogBuilder

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "artifacts/b01_b02_full/bundles_release"
TARGET_DIR = ROOT / "artifacts/b01_b02_full/improved_bundles"


def main():
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("APPLYING B01 JOIN IMPROVEMENTS & B02 UNIT CONVERSIONS TO ALL 30 BUNDLES")
    print("=" * 80)

    start_time = time.time()
    matcher = RuleSchemaMatcher()

    for biz_dir in sorted(SOURCE_DIR.glob("biz_*")):
        biz_id = biz_dir.name
        subdirs = [p for p in biz_dir.iterdir() if p.is_dir() and (p / "business_context.json").exists()]
        if not subdirs:
            continue
        src_bundle = subdirs[0]
        dst_biz_dir = TARGET_DIR / biz_id
        dst_biz_dir.mkdir(parents=True, exist_ok=True)
        dst_bundle = dst_biz_dir / src_bundle.name
        shutil.copytree(src_bundle, dst_bundle)

        duck_file = dst_bundle / "data.duckdb"
        ctx_file = dst_bundle / "business_context.json"
        ctx = json.loads(ctx_file.read_text())

        # 1. B01 Joins: Ingest tables and run updated _sql_join_candidates
        with duckdb.connect(str(duck_file)) as con:
            tables_raw = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
            table_names = [r[0] for r in tables_raw if r[0] != "calendar" and not r[0].startswith("__")]

            col_role_mapping = {
                (t["name"], c["name"]): c.get("role")
                for t in ctx.get("schema_catalog", {}).get("tables", [])
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

            ctx.setdefault("schema_catalog", {})["join_graph"] = join_graph

            # 2. B02 Unit Conversions:
            rules = tuple(BusinessRule(**r) for r in ctx["rule_catalog"]["rules"])
            base_sem = matcher.extract_semantic_catalog(biz_id, SchemaCatalog(tables=()), rules)
            verified_units = list(base_sem.unit_conversions)

            seen_keys = {
                (u["item_name"].strip().lower(), u["from_unit"].strip().lower(), u["to_unit"].strip().lower())
                for u in verified_units
            }

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

            # Đồng bộ lại DuckDB table unit_conversions
            if verified_units:
                con.execute("CREATE TABLE IF NOT EXISTS main.unit_conversions (item_name VARCHAR, from_unit VARCHAR, to_unit VARCHAR, factor DECIMAL(38,12))")
                con.execute("DELETE FROM main.unit_conversions")
                for u in verified_units:
                    con.execute(
                        "INSERT INTO main.unit_conversions VALUES (?, ?, ?, ?)",
                        [str(u["item_name"]), str(u["from_unit"]), str(u["to_unit"]), float(u["factor"])],
                    )

            ctx.setdefault("semantic_catalog", {})["unit_conversions"] = verified_units
            ctx_file.write_text(json.dumps(ctx, ensure_ascii=False, indent=2) + "\n")

        print(f"[{biz_id}] {len(join_graph)} joins, {len(verified_units)} units")

    total_time = time.time() - start_time
    print(f"\nĐã cập nhật toàn bộ 30 bundles thành công trong {total_time:.2f}s!")


if __name__ == "__main__":
    main()
