"""Tests for C2: Question-level Temporal Resolver."""

from __future__ import annotations

import pytest

from datamate.grounding.contracts import DateRole
from datamate.grounding.mock_provider import MockBusinessContextProvider
from datamate.grounding.temporal import QuestionTemporalResolver


class TestQuestionTemporalResolver:
    """Verify deterministic relative, explicit, and calendar-based date resolution."""

    @pytest.fixture()
    def resolver(self) -> QuestionTemporalResolver:
        return QuestionTemporalResolver()

    def test_resolve_today_and_yesterday(self, resolver: QuestionTemporalResolver) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        r_today = resolver.resolve("Hôm nay bán được bao nhiêu đơn?", "2026-08-27", ctx)
        assert len(r_today) == 1
        assert r_today[0].start_date == "2026-08-27"
        assert r_today[0].end_date == "2026-08-27"
        assert r_today[0].date_role == DateRole.ORDER_DATE

        r_yesterday = resolver.resolve("Doanh thu ngày hôm qua là bao nhiêu?", "2026-08-27", ctx)
        assert len(r_yesterday) == 1
        assert r_yesterday[0].start_date == "2026-08-26"
        assert r_yesterday[0].end_date == "2026-08-26"

    def test_resolve_this_month_and_last_month(self, resolver: QuestionTemporalResolver) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        r_this = resolver.resolve(
            "Trong tháng này, ca tối thu được bao nhiêu tiền mặt?",
            "2026-08-27",
            ctx,
            preferred_date_role=DateRole.PAYMENT_DATE,
        )
        assert len(r_this) == 1
        assert r_this[0].start_date == "2026-08-01"
        assert r_this[0].end_date == "2026-08-27"
        assert r_this[0].date_role == DateRole.PAYMENT_DATE

        r_last = resolver.resolve("Tổng doanh thu tháng trước là bao nhiêu?", "2026-08-27", ctx)
        assert len(r_last) == 1
        assert r_last[0].start_date == "2026-07-01"
        assert r_last[0].end_date == "2026-07-31"

    def test_resolve_recent_n_days(self, resolver: QuestionTemporalResolver) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        r_7d = resolver.resolve("Có bao nhiêu đơn hàng trong 7 ngày gần đây?", "2026-08-27", ctx)
        assert len(r_7d) == 1
        # 7 days inclusive ending 2026-08-27 -> 2026-08-21..2026-08-27
        assert r_7d[0].start_date == "2026-08-21"
        assert r_7d[0].end_date == "2026-08-27"

        r_30d = resolver.resolve("Doanh thu 30 ngày qua là bao nhiêu?", "2026-08-27", ctx)
        assert len(r_30d) == 1
        assert r_30d[0].start_date == "2026-07-29"
        assert r_30d[0].end_date == "2026-08-27"

    def test_resolve_quarters_and_years(self, resolver: QuestionTemporalResolver) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        r_q = resolver.resolve("Doanh thu quý này đạt bao nhiêu?", "2026-08-27", ctx)
        assert len(r_q) == 1
        assert r_q[0].start_date == "2026-07-01"
        assert r_q[0].end_date == "2026-08-27"

        r_q2 = resolver.resolve("Doanh thu quý 2 năm 2026 là bao nhiêu?", "2026-08-27", ctx)
        assert len(r_q2) == 1
        assert r_q2[0].start_date == "2026-04-01"
        assert r_q2[0].end_date == "2026-06-30"

        r_year = resolver.resolve("Từ đầu năm nay cửa hàng bán được bao nhiêu đơn?", "2026-08-27", ctx)
        assert len(r_year) == 1
        assert r_year[0].start_date == "2026-01-01"
        assert r_year[0].end_date == "2026-08-27"

    def test_resolve_explicit_month_and_date(self, resolver: QuestionTemporalResolver) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        r_m = resolver.resolve("Tổng doanh thu tháng 05/2026 là bao nhiêu?", "2026-08-27", ctx)
        assert len(r_m) == 1
        assert r_m[0].start_date == "2026-05-01"
        assert r_m[0].end_date == "2026-05-31"

        r_d = resolver.resolve("Ngày 15/08/2026 có bao nhiêu đơn hoàn thành?", "2026-08-27", ctx)
        assert len(r_d) == 1
        assert r_d[0].start_date == "2026-08-15"
        assert r_d[0].end_date == "2026-08-15"

    def test_resolve_tet_and_calendar_events(self, resolver: QuestionTemporalResolver) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        r_tet = resolver.resolve("Doanh thu dịp Tết năm nay là bao nhiêu?", "2026-08-27", ctx)
        assert len(r_tet) == 1
        assert r_tet[0].start_date == "2026-02-14"
        assert r_tet[0].end_date == "2026-02-22"

    def test_resolve_comparison_periods(self, resolver: QuestionTemporalResolver) -> None:
        ctx = MockBusinessContextProvider.create_fnb_context()
        r_yoy = resolver.resolve(
            "Doanh thu tháng này thay đổi bao nhiêu phần trăm so với cùng kỳ năm ngoái?",
            "2026-08-27",
            ctx,
        )
        assert len(r_yoy) == 1
        assert r_yoy[0].start_date == "2026-08-01"
        assert r_yoy[0].end_date == "2026-08-27"
        assert r_yoy[0].comparison_start_date == "2025-08-01"
        assert r_yoy[0].comparison_end_date == "2025-08-27"

