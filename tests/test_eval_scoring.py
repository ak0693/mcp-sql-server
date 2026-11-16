from datetime import date
from decimal import Decimal

from mcp_sql_server.evals.scoring import compare_results


def test_identical_results_match():
    rows = [("ASIA", 10.5), ("EUROPE", 3.0)]
    assert compare_results(rows, list(rows)).match


def test_row_order_is_ignored():
    assert compare_results([("a", 1), ("b", 2)], [("b", 2), ("a", 1)]).match


def test_column_order_is_ignored():
    assert compare_results([("a", 1, date(1995, 1, 1))], [(date(1995, 1, 1), "a", 1)]).match


def test_numeric_types_and_float_noise_are_ignored():
    expected = [(Decimal("1500.00"), 0.1 + 0.2)]
    actual = [(1500, 0.3)]
    assert compare_results(expected, actual).match


def test_a_real_numeric_difference_is_caught():
    result = compare_results([("x", 100.0)], [("x", 100.1)])
    assert not result.match
    assert "rows differ" in result.reason


def test_duplicate_rows_count():
    assert not compare_results([("a",), ("a",)], [("a",), ("b",)]).match


def test_extra_column_is_wrong():
    result = compare_results([("a", 1)], [("a", 1, "extra")])
    assert not result.match
    assert "columns" in result.reason


def test_missing_rows_are_wrong():
    result = compare_results([("a",), ("b",)], [("a",)])
    assert not result.match
    assert "expected 2 rows, got 1" in result.reason


def test_empty_matches_empty():
    assert compare_results([], []).match
