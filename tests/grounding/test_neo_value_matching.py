"""Tests for deterministic DB value matching inside NeoGroundingEngine v3."""

from __future__ import annotations

import json
from pathlib import Path

from datamate.grounding import (
    GroundingContextIndex,
    GroundingToPlannerAdapter,
    NeoGroundingEngine,
    QuestionRequest,
)
from datamate.ingestion.ingestion import prepare_business
from datamate.pipeline import DataMatePipeline


def _setup_menu_bundle(tmp_path: Path):
    biz_dir = tmp_path / "biz"
    biz_dir.mkdir()
    # >25 products so categorical_samples skips full enumeration (reproducing high-cardinality column)
    rows = ["sku,san_pham,nhom_hang"]
    for i in range(1, 26):
        rows.append(f"SP{i:03d},Món số {i},Khác")
    rows.append("SP026,Cà phê sữa (L),cà phê")
    rows.append("SP027,Rau cần xào tỏi,món xào")
    (biz_dir / "san_pham.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    cal = tmp_path / "calendar.csv"
    cal.write_text("date,weekday,lunar_day,lunar_month,lunar_year,lunar_leap,holiday\n2026-01-10,6,22,11,2025,false,\n", encoding="utf-8")
    rb = tmp_path / "rulebook.md"
    rb.write_text("## Thời gian\n- Tháng M/Y cả tháng.\n", encoding="utf-8")
    art = prepare_business(biz_dir, tmp_path / "bundle", calendar=cal, rulebook=rb)
    idx = GroundingContextIndex(art.bundle_dir, rulebook=rb, calendar=cal)
    rt = DataMatePipeline.load_runtime_context(art.bundle_dir, expected_business_id="biz")
    return idx, rt


def test_neo_grounding_links_exact_product_and_appears_in_hint(tmp_path: Path) -> None:
    idx, rt = _setup_menu_bundle(tmp_path)
    proposal = json.dumps(
        {
            "metric_mentions": [{"id": "m1", "text": "bán đc mấy ly"}],
            "entity_mentions": [{"id": "e1", "text": "Cà phê sữa (L)"}],
            "condition_mentions": [],
            "temporal_intent": "single_period",
            "time": [
                {
                    "id": "t1",
                    "raw_expression": "tháng 1 năm 2026",
                    "calendar": "gregorian",
                    "kind": "month",
                    "year": 2026,
                    "month": 1,
                    "period_extent": "full_period",
                    "comparison": "none",
                    "role": "primary",
                    "applies_to": ["m1"],
                }
            ],
            "unresolved": [],
        },
        ensure_ascii=False,
    )
    engine = NeoGroundingEngine(
        lambda _s, _u: proposal,
        {"biz": idx},
        token_count_fn=lambda s, u: len((s + u).split()),
    )
    grounded = engine.ground(
        QuestionRequest(
            question_id="q_05ed1cf68188",
            business_id="biz",
            question="Trong tháng 1 năm 2026 cửa hàng bán đc mấy ly Cà phê sữa (L)?",
            as_of_date="2026-08-19",
        ),
        rt.grounding_context,
    )
    assert any(
        mv.matched_db_value == "Cà phê sữa (L)" and mv.column_name == "san_pham"
        for mv in grounded.matched_values
    )
    hint = json.loads(GroundingToPlannerAdapter.format_grounded_hint_for_v1_2(grounded) or "{}")
    assert any(m["value"] == "Cà phê sữa (L)" for m in hint.get("matched_values", []))


def test_neo_grounding_scans_unaccented_question_against_high_cardinality_db(tmp_path: Path) -> None:
    idx, rt = _setup_menu_bundle(tmp_path)
    # Even if 3B puts the whole dish into metric or misses entity_mentions completely:
    proposal = json.dumps(
        {
            "metric_mentions": [{"id": "m1", "text": "ban duoc may dia"}],
            "entity_mentions": [],
            "condition_mentions": [],
            "temporal_intent": "single_period",
            "time": [
                {
                    "id": "t1",
                    "raw_expression": "thang 4 nam 2025",
                    "calendar": "gregorian",
                    "kind": "month",
                    "year": 2025,
                    "month": 4,
                    "period_extent": "full_period",
                    "comparison": "none",
                    "role": "primary",
                    "applies_to": ["m1"],
                }
            ],
            "unresolved": [],
        },
        ensure_ascii=False,
    )
    engine = NeoGroundingEngine(
        lambda _s, _u: proposal,
        {"biz": idx},
        token_count_fn=lambda s, u: len((s + u).split()),
    )
    grounded = engine.ground(
        QuestionRequest(
            question_id="q_060cee917ee1",
            business_id="biz",
            question="trong thang 4 nam 2025 cua hang ban duoc may dia rau can xao toi",
            as_of_date="2026-08-29",
        ),
        rt.grounding_context,
    )
    assert any(
        mv.matched_db_value == "Rau cần xào tỏi" and mv.column_name == "san_pham"
        for mv in grounded.matched_values
    )
