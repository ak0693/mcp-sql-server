"""Reference SQL and reference results for the 22 TPC-H questions.

The reference SQL comes from DuckDB's tpch extension (``tpch_queries()``), so
it is the standard benchmark text, not something written for this repo. The
reference results are computed by running that SQL against the same warehouse
the model queries, which keeps them correct at any scale factor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from ..build import _tpch_extension_path
from ..warehouse import LOCKDOWN
from .questions import QUESTIONS


@dataclass(frozen=True)
class Case:
    number: int
    question: str
    reference_sql: str
    expected_rows: list[tuple[Any, ...]]


def reference_queries() -> dict[int, str]:
    """The 22 TPC-H queries as shipped in DuckDB's tpch extension."""
    con = duckdb.connect()  # in memory: only needed to read the query text
    try:
        con.execute(f"LOAD '{_tpch_extension_path()}'")
        return dict(con.execute("SELECT query_nr, query FROM tpch_queries()").fetchall())
    finally:
        con.close()


def load_cases(warehouse_path: str | Path, numbers: list[int] | None = None) -> list[Case]:
    queries = reference_queries()
    # Same settings as the served warehouse, so this can share the database
    # instance with it inside one process.
    con = duckdb.connect(str(warehouse_path), read_only=True, config=LOCKDOWN)
    try:
        cases = []
        for number in sorted(numbers or QUESTIONS):
            sql = queries[number].strip()
            cases.append(
                Case(
                    number=number,
                    question=QUESTIONS[number],
                    reference_sql=sql,
                    expected_rows=con.execute(sql).fetchall(),
                )
            )
        return cases
    finally:
        con.close()
