"""Tests for B0.5 Typed Output Formatter."""

import pytest
from datamate.gate.formatter import format_answer, normalize_match_key
from datamate.gate.errors import FormattingError


def test_normalize_match_key():
    assert normalize_match_key("  Cà phê   sữa!  ") == "cà phê sữa"
    assert normalize_match_key("Sting Dâu (330ml)") == "sting dâu 330ml"


def test_format_number_count():
    # Integer count
    assert format_answer("number", 125, {"numeric_kind": "count"}) == 125
    assert format_answer("number", "125", {"numeric_kind": "count"}) == 125
    assert format_answer("number", 125.0, {"numeric_kind": "count"}) == 125
    assert format_answer("number", 0, {"numeric_kind": "count"}) == 0

    # Invalid count with fraction
    with pytest.raises(FormattingError):
        format_answer("number", 125.5, {"numeric_kind": "count"})


def test_format_number_money_vnd():
    # ROUND_HALF_UP to unit
    assert format_answer("number", 1250000.5, {"numeric_kind": "money_vnd"}) == 1250001
    assert format_answer("number", 1250000.4, {"numeric_kind": "money_vnd"}) == 1250000
    assert format_answer("number", "50000", {"numeric_kind": "money_vnd"}) == 50000


def test_format_number_average_nonmoney():
    # 2 decimal places
    assert format_answer("number", 12.345, {"numeric_kind": "average_nonmoney"}) == 12.35
    assert format_answer("number", -12.445, {"numeric_kind": "average_nonmoney"}) == -12.45


def test_format_percent():
    # percent_points
    assert format_answer("percent", -12.445, {"percent_unit": "percent_points"}) == -12.45
    assert format_answer("percent", 5.5, {}) == 5.5

    # fraction
    assert format_answer("percent", 0.125, {"percent_unit": "fraction"}) == 12.5

    # near zero rounding
    assert format_answer("percent", -0.004, {}) == 0


def test_format_string():
    assert format_answer("string", "  Cà phê sữa  ", {}) == "Cà phê sữa"
    assert format_answer("string", "Sting dâu 330ml", {}) == "Sting dâu 330ml"

    with pytest.raises(FormattingError):
        format_answer("string", "", {})

    with pytest.raises(FormattingError):
        format_answer("string", 123, {})


def test_format_date():
    assert format_answer("date", "2026-03-04", {}) == "2026-03-04"
    assert format_answer("date", "2026-02-28", {}) == "2026-02-28"
    assert format_answer("date", "2026-03", {"time_role": "month"}) == "2026-03"

    # Invalid calendar date
    with pytest.raises(FormattingError):
        format_answer("date", "2026-02-30", {})

    # Invalid ambiguous format
    with pytest.raises(FormattingError):
        format_answer("date", "04/03/2026", {})


def test_format_boolean():
    assert format_answer("boolean", True, {}) is True
    assert format_answer("boolean", False, {}) is False

    with pytest.raises(FormattingError):
        format_answer("boolean", 1, {})

    with pytest.raises(FormattingError):
        format_answer("boolean", "true", {})


def test_format_list():
    assert format_answer("list", ["B", "A"], {}) == ["B", "A"]
    assert format_answer("list", [1, 2, 3], {}) == [1, 2, 3]

    with pytest.raises(FormattingError):
        format_answer("list", "not a list", {})


def test_format_table():
    table_data = {
        "columns": ["ma", "qty"],
        "rows": [["SP01", 10], ["SP02", 20]]
    }
    res = format_answer("table", table_data, {})
    assert res == table_data

    # Invalid shape
    bad_table = {
        "columns": ["ma", "qty"],
        "rows": [["SP01"]]  # missing column cell
    }
    with pytest.raises(FormattingError):
        format_answer("table", bad_table, {})

