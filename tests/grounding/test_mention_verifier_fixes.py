"""Regression tests reproducing real Modal 3B Neo Grounding mention/time verification failures."""

from __future__ import annotations

import json
from pathlib import Path

from datamate.grounding import GroundingContextIndex, NeoGroundingEngine, QuestionRequest
from datamate.grounding.mention_contracts import MentionProposal
from datamate.grounding.mention_verifier import parse_mentions, verify_mentions
from datamate.grounding.neo_prompt import SYSTEM
from datamate.ingestion.ingestion import prepare_business
from datamate.pipeline import DataMatePipeline


def _setup_index(tmp_path: Path):
    biz_dir = tmp_path / "biz"
    biz_dir.mkdir()
    (biz_dir / "orders.csv").write_text(
        "order_id,ngay,amount\n1,2025-04-01,100\n2,2025-07-10,200\n",
        encoding="utf-8",
    )
    cal = tmp_path / "calendar.csv"
    # Continuous dates covering 2025-03-20 .. 2025-08-10
    from datetime import date, timedelta

    lines = ["date,weekday,lunar_day,lunar_month,lunar_year,lunar_leap,holiday"]
    cur = date(2025, 3, 20)
    end = date(2025, 8, 10)
    idx_day = 0
    while cur <= end:
        l_year = 2025 + (idx_day // 360)
        l_month = ((idx_day // 30) % 12) + 1
        l_day = (idx_day % 30) + 1
        lines.append(f"{cur.isoformat()},{cur.weekday() + 1},{l_day},{l_month},{l_year},false,")
        cur += timedelta(days=1)
        idx_day += 1
    cal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rb = tmp_path / "rulebook.md"
    rb.write_text("## Thời gian\n- Tuần bắt đầu thứ Hai.\n", encoding="utf-8")
    art = prepare_business(biz_dir, tmp_path / "bundle", calendar=cal, rulebook=rb)
    idx = GroundingContextIndex(art.bundle_dir, rulebook=rb, calendar=cal)
    rt = DataMatePipeline.load_runtime_context(art.bundle_dir, expected_business_id="biz")
    return idx, rt


def test_accent_insensitive_span_and_no_cascade_time_rejection(tmp_path: Path) -> None:
    idx, _ = _setup_index(tmp_path)
    raw = json.dumps(
        {
            "metric_mentions": [{"id": "m1", "text": "doanh thu"}],  # question has shorthand "dthu"
            "entity_mentions": [],
            "condition_mentions": [],
            "temporal_intent": "single_period",
            "time": [
                {
                    "id": "t1",
                    "raw_expression": "Tháng 7/2025",  # question has unaccented lowercase "thang 7/2025"
                    "calendar": "gregorian",
                    "kind": "month",
                    "year": 2025,
                    "month": 7,
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
    proposal, rejected = parse_mentions(raw)
    assert rejected == []
    payload = verify_mentions(
        proposal,
        QuestionRequest(
            question_id="q_064d58d5530f",
            business_id="biz",
            question="coi gium dthu thang 7/2025 bao nhieu",
            as_of_date="2025-08-05",
        ),
        idx,
        rejected_claims=rejected,
    )
    windows = payload["temporal_plan"]["resolved_windows"]
    assert len(windows) == 1
    assert windows[0]["start_inclusive"] == "2025-07-01"
    assert windows[0]["end_exclusive"] == "2025-08-01"


def test_week_missing_relative_is_inferred_from_raw_expression(tmp_path: Path) -> None:
    idx, _ = _setup_index(tmp_path)
    raw = json.dumps(
        {
            "metric_mentions": [{"id": "m1", "text": "dthu"}],
            "entity_mentions": [],
            "condition_mentions": [],
            "temporal_intent": "single_period",
            "time": [
                {
                    "id": "t1",
                    "raw_expression": "tuần trc",  # 3B frequently omits relative="previous"
                    "calendar": "gregorian",
                    "kind": "week",
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
    proposal, rejected = parse_mentions(raw)
    assert rejected == []
    payload = verify_mentions(
        proposal,
        QuestionRequest(
            question_id="q_058bd677f168",
            business_id="biz",
            question="ê trung bình mỗi đơn tuần trc mang về bao nhiu dthu",
            as_of_date="2025-04-08",  # Tuesday -> previous Mon..Sun = 2025-03-31 .. 2025-04-07
        ),
        idx,
        rejected_claims=rejected,
    )
    windows = payload["temporal_plan"]["resolved_windows"]
    assert len(windows) == 1
    assert windows[0]["start_inclusive"] == "2025-03-31"
    assert windows[0]["end_exclusive"] == "2025-04-07"


def test_this_week_omitted_relative_infers_to_as_of(tmp_path: Path) -> None:
    validated = MentionProposal.model_validate(
        {
            "metric_mentions": [],
            "entity_mentions": [],
            "condition_mentions": [],
            "temporal_intent": "single_period",
            "time": [
                {
                    "id": "t1",
                    "raw_expression": "tuần này",
                    "calendar": "gregorian",
                    "kind": "week",
                    "period_extent": "full_period",
                    "comparison": "none",
                    "role": "primary",
                    "applies_to": [],
                }
            ],
            "unresolved": [],
        }
    )
    assert validated.time[0].relative == "this"
    assert validated.time[0].period_extent == "to_as_of"


def test_neo_prompt_includes_previous_week_and_yesterday_examples() -> None:
    assert '"kind":"week"' in SYSTEM
    assert '"relative":"previous"' in SYSTEM
    assert "hôm qua" in SYSTEM
