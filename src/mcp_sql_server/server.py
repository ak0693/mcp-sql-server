"""MCP server exposing the warehouse as three read-only tools."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import duckdb
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .guard import GuardError
from .warehouse import DEFAULT_MAX_ROWS, DEFAULT_TIMEOUT_S, QueryTimeout, Warehouse

# Failures the model can fix by rewriting its query. Their messages are passed
# back verbatim; anything else is reported by the SDK as a generic error so
# internals never leak.
_EXPECTED_ERRORS = (GuardError, QueryTimeout, duckdb.Error)

INSTRUCTIONS = """\
Read-only SQL access to a TPC-H sales warehouse in DuckDB.
Work in this order: list_tables, then describe_table for the tables you need
(column descriptions explain the terse TPC-H names), then run_query.
Only single SELECT statements are accepted. Results are capped, so aggregate
in SQL rather than pulling raw rows. If a query is refused, the error says why;
fix the query and try again.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)


def create_server(warehouse: Warehouse) -> MCPServer:
    server = MCPServer(name="tpch-warehouse", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    def list_tables() -> list[dict[str, Any]]:
        """List the warehouse tables with approximate row counts and a one-line description."""
        return warehouse.list_tables()

    @server.tool(annotations=READ_ONLY)
    def describe_table(table: str) -> dict[str, Any]:
        """Show a table's columns: name, type, nullability and what each column means."""
        try:
            return warehouse.describe_table(table)
        except _EXPECTED_ERRORS as err:
            raise ToolError(str(err)) from err

    @server.tool(annotations=READ_ONLY)
    def run_query(sql: str) -> dict[str, Any]:
        """Run one read-only SELECT (DuckDB dialect) and return columns and rows.

        Results are capped at a fixed number of rows; `truncated` tells you if
        more rows existed. Queries over the time limit are cancelled.
        """
        try:
            return warehouse.run_query(sql).as_dict()
        except _EXPECTED_ERRORS as err:
            raise ToolError(str(err)) from err

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the TPC-H warehouse MCP server over stdio.")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("MCP_SQL_DB", "data/tpch.duckdb")),
        help="Path to the DuckDB warehouse file.",
    )
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="Seconds per query.")
    args = parser.parse_args()

    warehouse = Warehouse(args.db, max_rows=args.max_rows, timeout_s=args.timeout)
    create_server(warehouse).run()


if __name__ == "__main__":
    main()
