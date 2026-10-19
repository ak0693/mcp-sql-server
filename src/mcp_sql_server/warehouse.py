"""Read-only access to the DuckDB warehouse.

Every query passes three layers:

1. ``guard.check_query`` refuses anything that is not a single SELECT over
   known tables.
2. The connection is opened read-only, with external access disabled and the
   configuration locked, so even a query that slipped past the guard cannot
   write, read files or reach the network.
3. Execution is wrapped in a row cap and a wall-clock timeout, so a valid but
   expensive query cannot flood the model's context or hang the server.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from .guard import GuardError, check_query

DEFAULT_MAX_ROWS = 200
DEFAULT_TIMEOUT_S = 10.0


class QueryTimeout(RuntimeError):
    pass


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: int
    sql: str = field(repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "elapsed_ms": self.elapsed_ms,
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


class Warehouse:
    def __init__(
        self,
        path: str | Path,
        max_rows: int = DEFAULT_MAX_ROWS,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(
                f"No warehouse at {self.path}. Build one with: python -m mcp_sql_server.build"
            )
        self.max_rows = max_rows
        self.timeout_s = timeout_s
        self._con = duckdb.connect(str(self.path), read_only=True)
        self._con.execute("SET enable_external_access = false")
        self._con.execute("SET autoinstall_known_extensions = false")
        self._con.execute("SET autoload_known_extensions = false")
        self._con.execute("SET lock_configuration = true")
        self._lock = threading.Lock()
        self.tables = frozenset(
            row[0].lower()
            for row in self._con.execute(
                "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main'"
            ).fetchall()
        )

    def close(self) -> None:
        self._con.close()

    # Schema discovery ------------------------------------------------------

    def list_tables(self) -> list[dict[str, Any]]:
        rows = self._con.execute(
            """
            SELECT table_name, estimated_size, comment
            FROM duckdb_tables()
            WHERE schema_name = 'main'
            ORDER BY table_name
            """
        ).fetchall()
        return [{"table": t, "approx_rows": n, "description": c} for t, n, c in rows]

    def describe_table(self, table: str) -> dict[str, Any]:
        name = table.strip().lower()
        if name not in self.tables:
            raise GuardError(
                f"Unknown table '{table}'. Available tables: {', '.join(sorted(self.tables))}."
            )
        columns = self._con.execute(
            """
            SELECT column_name, data_type, is_nullable, comment
            FROM duckdb_columns()
            WHERE schema_name = 'main' AND table_name = ?
            ORDER BY column_index
            """,
            [name],
        ).fetchall()
        comment = self._con.execute(
            "SELECT comment FROM duckdb_tables() WHERE schema_name = 'main' AND table_name = ?",
            [name],
        ).fetchone()[0]
        return {
            "table": name,
            "description": comment,
            "columns": [
                {"name": c, "type": t, "nullable": n, "description": d}
                for c, t, n, d in columns
            ],
        }

    # Query execution -------------------------------------------------------

    def run_query(self, sql: str) -> QueryResult:
        checked = check_query(sql, self.tables)
        # Fetch one row past the cap so we know whether the result was cut.
        limited = f"SELECT * FROM ({checked.sql}) AS _q LIMIT {self.max_rows + 1}"

        with self._lock:
            cursor = self._con.cursor()
            timer = threading.Timer(self.timeout_s, cursor.interrupt)
            started = time.perf_counter()
            timer.start()
            try:
                cursor.execute(limited)
                columns = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
            except duckdb.InterruptException as err:
                raise QueryTimeout(
                    f"Query exceeded the {self.timeout_s:g}s limit. "
                    "Add filters or aggregate before returning rows."
                ) from err
            finally:
                timer.cancel()
                cursor.close()
            elapsed_ms = int((time.perf_counter() - started) * 1000)

        truncated = len(rows) > self.max_rows
        rows = rows[: self.max_rows]
        return QueryResult(
            columns=columns,
            rows=[[_jsonable(v) for v in row] for row in rows],
            row_count=len(rows),
            truncated=truncated,
            elapsed_ms=elapsed_ms,
            sql=checked.sql,
        )
