"""Static checks that decide whether a SQL string may run against the warehouse.

The guard is the first of three layers. It parses the query with sqlglot and
accepts only a single read query over known tables. The other two layers live
in ``warehouse.py``: a read-only DuckDB connection with external access turned
off, and a row cap plus timeout applied at execution time. The guard exists so
that a bad query is refused with a message the model can act on, before the
database has to refuse it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

# Statement types that must never appear anywhere in the tree, including
# inside a CTE.
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name)
    for name in (
        "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter",
        "Command", "Copy", "Attach", "Detach", "Pragma", "Set", "Install",
        "Use", "Transaction", "Commit", "Rollback", "TruncateTable",
        "Describe", "Summarize", "Grant", "Revoke", "Export", "LoadData",
    )
    if hasattr(exp, name)
)

# Functions that read files, the network or the environment. External access
# is also switched off on the connection, so this list is about giving a clear
# error early rather than being the only line of defence.
_FORBIDDEN_FUNCTIONS = frozenset(
    {
        "read_csv", "read_csv_auto", "read_parquet", "parquet_scan",
        "read_json", "read_json_auto", "read_json_objects", "read_ndjson",
        "read_ndjson_auto", "read_ndjson_objects", "read_text", "read_blob",
        "sniff_csv", "parquet_metadata", "parquet_schema", "parquet_file_metadata",
        "glob", "getenv", "query", "query_table", "sqlite_scan", "postgres_scan",
        "mysql_scan", "iceberg_scan", "delta_scan", "load_extension",
    }
)


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class GuardError(ValueError):
    """Raised when a query is refused. The message is written for the model."""


@dataclass(frozen=True)
class CheckedQuery:
    sql: str
    tables: frozenset[str]


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def check_query(sql: str, allowed_tables: frozenset[str]) -> CheckedQuery:
    """Return the normalised query if it is a single read over allowed tables."""
    if not sql or not sql.strip():
        raise GuardError("Empty query.")

    try:
        statements = [s for s in sqlglot.parse(sql, dialect="duckdb") if s is not None]
    except ParseError as err:
        # sqlglot underlines the bad token with terminal colour codes; the
        # model gets plain text.
        detail = _ANSI.sub("", str(err))
        raise GuardError(f"Could not parse the query: {detail}") from err

    if len(statements) != 1:
        raise GuardError(
            f"Send exactly one statement; got {len(statements)}. "
            "Split the work into separate run_query calls."
        )
    tree = statements[0]

    if not isinstance(tree, exp.Query):
        raise GuardError(
            f"Only SELECT queries are allowed; got {type(tree).__name__.upper()}. "
            "Use list_tables and describe_table to inspect the schema."
        )

    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise GuardError(f"{type(node).__name__.upper()} is not allowed inside a query.")
        if isinstance(node, exp.Func) and _function_name(node) in _FORBIDDEN_FUNCTIONS:
            raise GuardError(f"Function {_function_name(node)}() is not allowed.")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    used: set[str] = set()
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise GuardError(
                "Table functions are not allowed in FROM. Query the warehouse tables directly."
            )
        if table.catalog or (table.db and table.db.lower() != "main"):
            raise GuardError(f"Only the main schema is available; got {table.sql()}.")
        name = table.name.lower()
        if name in cte_names:
            continue
        if name not in allowed_tables:
            known = ", ".join(sorted(allowed_tables))
            raise GuardError(f"Unknown table '{table.name}'. Available tables: {known}.")
        used.add(name)

    return CheckedQuery(sql=tree.sql(dialect="duckdb"), tables=frozenset(used))
