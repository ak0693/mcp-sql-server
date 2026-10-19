"""End-to-end tests through a real MCP client connected in-process."""

import pytest
from mcp import Client

from mcp_sql_server.server import create_server

pytestmark = pytest.mark.anyio


async def test_exposes_three_read_only_tools(warehouse):
    async with Client(create_server(warehouse)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"list_tables", "describe_table", "run_query"}
    for tool in tools.values():
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is False


async def test_run_query_returns_structured_rows(warehouse):
    async with Client(create_server(warehouse)) as client:
        result = await client.call_tool(
            "run_query", {"sql": "SELECT r_name FROM region ORDER BY r_name"}
        )
    assert result.is_error is False
    data = result.structured_content
    assert data["columns"] == ["r_name"]
    assert [row[0] for row in data["rows"]] == [
        "AFRICA", "AMERICA", "ASIA", "EUROPE", "MIDDLE EAST"
    ]


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("DELETE FROM orders", "Only SELECT"),
        ("SELECT * FROM users", "Unknown table 'users'"),
        ("SELECT o_nonexistent FROM orders", "o_nonexistent"),
    ],
)
async def test_errors_reach_the_model_verbatim(warehouse, sql, message):
    # The model can only self-correct if it sees why a query failed.
    async with Client(create_server(warehouse)) as client:
        result = await client.call_tool("run_query", {"sql": sql})
    assert result.is_error is True
    assert message in result.content[0].text


async def test_describe_table_through_mcp(warehouse):
    async with Client(create_server(warehouse)) as client:
        result = await client.call_tool("describe_table", {"table": "lineitem"})
    columns = {c["name"]: c for c in result.structured_content["columns"]}
    assert "Revenue" in columns["l_discount"]["description"]
