import time

import duckdb
import pytest

from mcp_sql_server.guard import GuardError
from mcp_sql_server.warehouse import QueryTimeout, Warehouse


def test_lists_all_tpch_tables_with_descriptions(warehouse):
    tables = {t["table"]: t for t in warehouse.list_tables()}
    assert set(tables) == {
        "customer", "lineitem", "nation", "orders", "part", "partsupp", "region", "supplier"
    }
    assert all(t["description"] for t in tables.values())


def test_every_column_has_a_description(warehouse):
    for table in warehouse.tables:
        for column in warehouse.describe_table(table)["columns"]:
            assert column["description"], f"{table}.{column['name']} has no description"


def test_describe_unknown_table(warehouse):
    with pytest.raises(GuardError, match="Unknown table"):
        warehouse.describe_table("users")


def test_query_returns_json_friendly_values(warehouse):
    result = warehouse.run_query(
        "SELECT o_orderdate, o_totalprice FROM orders ORDER BY o_orderkey LIMIT 1"
    )
    date_value, price = result.rows[0]
    assert isinstance(date_value, str) and len(date_value) == 10
    assert isinstance(price, float)
    assert result.truncated is False


def test_results_are_capped_and_flagged(warehouse):
    result = warehouse.run_query("SELECT * FROM orders")
    assert result.row_count == warehouse.max_rows
    assert result.truncated is True


def test_cap_respects_a_smaller_user_limit(warehouse):
    result = warehouse.run_query("SELECT * FROM orders LIMIT 3")
    assert result.row_count == 3
    assert result.truncated is False


def test_slow_query_is_cancelled_and_connection_recovers(warehouse_path):
    wh = Warehouse(warehouse_path, timeout_s=0.5)
    started = time.perf_counter()
    with pytest.raises(QueryTimeout):
        wh.run_query("SELECT sum(a.l_quantity * b.l_quantity) FROM lineitem a, lineitem b")
    assert time.perf_counter() - started < 3
    assert wh.run_query("SELECT count(*) FROM region").rows == [[5]]
    wh.close()


# Defence in depth: these bypass the guard on purpose and talk to the
# connection directly, to prove the database layer holds on its own.

def test_connection_is_read_only(warehouse):
    with pytest.raises(duckdb.Error):
        warehouse._con.execute("CREATE TABLE pwned (a INT)")
    with pytest.raises(duckdb.Error):
        warehouse._con.execute("DELETE FROM orders")


def test_connection_cannot_touch_the_file_system(warehouse):
    with pytest.raises(duckdb.Error, match="disabled"):
        warehouse._con.execute("SELECT * FROM read_csv('/etc/passwd')").fetchall()


def test_connection_settings_are_locked(warehouse):
    with pytest.raises(duckdb.Error):
        warehouse._con.execute("SET enable_external_access = true")


def test_missing_warehouse_gives_build_hint(tmp_path):
    with pytest.raises(FileNotFoundError, match="mcp_sql_server.build"):
        Warehouse(tmp_path / "missing.duckdb")
