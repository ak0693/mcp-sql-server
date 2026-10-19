import pytest

from mcp_sql_server.guard import GuardError, check_query

TABLES = frozenset({"orders", "lineitem", "customer", "nation", "region"})


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders",
        "select o_orderkey from main.orders where o_totalprice > 1000",
        "WITH big AS (SELECT * FROM orders WHERE o_totalprice > 1e5) SELECT count(*) FROM big",
        "SELECT o_orderkey FROM orders UNION ALL SELECT l_orderkey FROM lineitem",
        "SELECT n_name, count(*) FROM customer JOIN nation ON c_nationkey = n_nationkey GROUP BY 1",
        "SELECT * FROM orders WHERE o_custkey IN (SELECT c_custkey FROM customer)",
        "SELECT 1",
        "SELECT * FROM orders;",
    ],
)
def test_read_queries_are_allowed(sql):
    check_query(sql, TABLES)


def test_reports_the_tables_used():
    checked = check_query(
        "WITH x AS (SELECT * FROM orders) SELECT * FROM x JOIN customer ON true", TABLES
    )
    assert checked.tables == {"orders", "customer"}


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("DROP TABLE orders", "Only SELECT"),
        ("DELETE FROM orders", "Only SELECT"),
        ("INSERT INTO orders SELECT * FROM orders", "Only SELECT"),
        ("UPDATE orders SET o_totalprice = 0", "Only SELECT"),
        ("CREATE TABLE t AS SELECT 1", "Only SELECT"),
        ("ATTACH 'other.db'", "Only SELECT"),
        ("COPY orders TO 'out.csv'", "Only SELECT"),
        ("PRAGMA database_list", "Only SELECT"),
        ("SET threads = 1", "Only SELECT"),
        ("INSTALL httpfs", "Only SELECT"),
        ("DESCRIBE orders", "Only SELECT"),
        ("SELECT 1; DROP TABLE orders", "exactly one statement"),
        ("SELECT 1; SELECT 2", "exactly one statement"),
        ("SELECT * FROM read_csv('/etc/passwd')", "read_csv"),
        ("SELECT * FROM read_parquet('s3://bucket/x.parquet')", "read_parquet"),
        ("SELECT getenv('HOME')", "getenv"),
        ("SELECT * FROM glob('*')", "glob"),
        ("SELECT * FROM range(10)", "Table functions"),
        ("SELECT * FROM '/etc/passwd'", "Unknown table"),
        ("SELECT * FROM secrets", "Unknown table"),
        ("SELECT * FROM other_db.main.orders", "main schema"),
        ("SELECT * FROM information_schema.tables", "main schema"),
        ("", "Empty"),
        ("SELEC * FROM orders", "Could not parse"),
    ],
)
def test_unsafe_or_invalid_queries_are_refused(sql, message):
    with pytest.raises(GuardError, match=message):
        check_query(sql, TABLES)


def test_parse_errors_are_plain_text():
    with pytest.raises(GuardError) as info:
        check_query("SELEC * FROM orders", TABLES)
    assert "\x1b" not in str(info.value)


def test_cte_name_does_not_unlock_unknown_tables():
    # A CTE may shadow nothing outside the allowlist.
    with pytest.raises(GuardError, match="Unknown table 'secrets'"):
        check_query("WITH x AS (SELECT * FROM secrets) SELECT * FROM x", TABLES)


def test_error_lists_available_tables():
    with pytest.raises(GuardError) as info:
        check_query("SELECT * FROM order", TABLES)
    assert "customer, lineitem, nation, orders, region" in str(info.value)
