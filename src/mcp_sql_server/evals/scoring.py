"""Compare a submitted query's result with the reference result.

The comparison is on result sets, not SQL text: two different queries that
return the same rows are both right. To avoid marking correct answers wrong
for presentation choices, it ignores:

- row order (as a multiset, so duplicate rows still count),
- column order and column names,
- numeric type and tiny floating-point differences (values compared at six
  significant figures, so 1500, 1500.0 and Decimal('1500.00') are equal).

It does not ignore extra or missing columns or rows: the questions name their
output columns, and returning more or fewer is a different answer.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Sequence

Row = Sequence[Any]


def _norm_value(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float, Decimal)):
        number = float(value)
        if number == 0:
            return "0"
        return f"{number:.6g}"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value).strip()


def _norm_row(row: Row) -> tuple[str, ...]:
    return tuple(sorted(_norm_value(v) for v in row))


@dataclass(frozen=True)
class Comparison:
    match: bool
    reason: str


def compare_results(expected: list[Row], actual: list[Row]) -> Comparison:
    if not expected and not actual:
        return Comparison(True, "both empty")
    expected_width = len(expected[0]) if expected else None
    actual_width = len(actual[0]) if actual else None
    if expected and actual and expected_width != actual_width:
        return Comparison(False, f"expected {expected_width} columns, got {actual_width}")
    if len(expected) != len(actual):
        return Comparison(False, f"expected {len(expected)} rows, got {len(actual)}")
    missing = Counter(map(_norm_row, expected)) - Counter(map(_norm_row, actual))
    if missing:
        return Comparison(False, f"{sum(missing.values())} of {len(expected)} rows differ")
    return Comparison(True, "match")
