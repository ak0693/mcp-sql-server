"""Build the demo warehouse: TPC-H data in a single DuckDB file.

TPC-H is the standard decision-support benchmark schema (orders, line items,
customers, suppliers, parts across nations and regions). The data is generated
locally by DuckDB's tpch extension, so nothing is downloaded and the build is
reproducible for a given scale factor.

The column names in TPC-H are terse (``l_extendedprice``, ``ps_supplycost``),
so the build also writes a plain-English comment on every table and column.
``describe_table`` returns those comments, which is most of what a model needs
to write correct SQL against an unfamiliar schema.

Usage:
    python -m mcp_sql_server.build --sf 0.1 --out data/tpch.duckdb
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

TABLE_COMMENTS = {
    "region": "The 5 world regions.",
    "nation": "The 25 nations; each belongs to one region.",
    "customer": "Customers who place orders; each is based in one nation.",
    "supplier": "Suppliers of parts; each is based in one nation.",
    "part": "Parts that can be ordered.",
    "partsupp": "Which supplier offers which part, with stock and cost. One row per (part, supplier).",
    "orders": "Customer orders (order header).",
    "lineitem": "Order lines: one row per part within an order. The largest table; revenue lives here.",
}

COLUMN_COMMENTS = {
    "region": {
        "r_regionkey": "Region id (primary key).",
        "r_name": "Region name, e.g. 'ASIA', 'EUROPE'.",
        "r_comment": "Free text.",
    },
    "nation": {
        "n_nationkey": "Nation id (primary key).",
        "n_name": "Nation name, e.g. 'INDIA', 'GERMANY'.",
        "n_regionkey": "Region of this nation; joins region.r_regionkey.",
        "n_comment": "Free text.",
    },
    "customer": {
        "c_custkey": "Customer id (primary key).",
        "c_name": "Customer name.",
        "c_address": "Street address.",
        "c_nationkey": "Customer's nation; joins nation.n_nationkey.",
        "c_phone": "Phone number; the first two digits are a country code.",
        "c_acctbal": "Account balance in dollars; can be negative.",
        "c_mktsegment": "Market segment: AUTOMOBILE, BUILDING, FURNITURE, HOUSEHOLD or MACHINERY.",
        "c_comment": "Free text.",
    },
    "supplier": {
        "s_suppkey": "Supplier id (primary key).",
        "s_name": "Supplier name.",
        "s_address": "Street address.",
        "s_nationkey": "Supplier's nation; joins nation.n_nationkey.",
        "s_phone": "Phone number.",
        "s_acctbal": "Account balance in dollars.",
        "s_comment": "Free text; some rows mention customer complaints.",
    },
    "part": {
        "p_partkey": "Part id (primary key).",
        "p_name": "Part name built from colour words, e.g. 'forest green metallic ...'.",
        "p_mfgr": "Manufacturer, e.g. 'Manufacturer#1'.",
        "p_brand": "Brand, e.g. 'Brand#23'.",
        "p_type": "Type as three words, e.g. 'ECONOMY ANODIZED STEEL'.",
        "p_size": "Size, an integer from 1 to 50.",
        "p_container": "Container, e.g. 'SM BOX', 'LG CASE'.",
        "p_retailprice": "List price in dollars.",
        "p_comment": "Free text.",
    },
    "partsupp": {
        "ps_partkey": "Part; joins part.p_partkey.",
        "ps_suppkey": "Supplier; joins supplier.s_suppkey.",
        "ps_availqty": "Units this supplier has in stock.",
        "ps_supplycost": "This supplier's cost per unit, in dollars.",
        "ps_comment": "Free text.",
    },
    "orders": {
        "o_orderkey": "Order id (primary key).",
        "o_custkey": "Customer who placed the order; joins customer.c_custkey.",
        "o_orderstatus": "F = all lines shipped, O = none shipped, P = partly shipped.",
        "o_totalprice": "Order total in dollars, after discount and tax.",
        "o_orderdate": "Date the order was placed.",
        "o_orderpriority": "Priority, e.g. '1-URGENT', '5-LOW'.",
        "o_clerk": "Clerk who handled the order.",
        "o_shippriority": "Shipping priority (always 0 in generated data).",
        "o_comment": "Free text.",
    },
    "lineitem": {
        "l_orderkey": "Order; joins orders.o_orderkey.",
        "l_partkey": "Part; joins part.p_partkey (and partsupp with l_suppkey).",
        "l_suppkey": "Supplier; joins supplier.s_suppkey.",
        "l_linenumber": "Line number within the order.",
        "l_quantity": "Units ordered.",
        "l_extendedprice": "Quantity times part price, in dollars, before discount.",
        "l_discount": "Discount as a fraction, 0.00 to 0.10. Revenue = l_extendedprice * (1 - l_discount).",
        "l_tax": "Tax as a fraction, 0.00 to 0.08.",
        "l_returnflag": "R = returned, A = accepted, N = not yet known.",
        "l_linestatus": "O = open, F = fulfilled.",
        "l_shipdate": "Date the line shipped.",
        "l_commitdate": "Date the line was promised to ship.",
        "l_receiptdate": "Date the customer received it. Late if after l_commitdate.",
        "l_shipinstruct": "Shipping instruction, e.g. 'DELIVER IN PERSON'.",
        "l_shipmode": "Ship mode: AIR, FOB, MAIL, RAIL, REG AIR, SHIP or TRUCK.",
        "l_comment": "Free text.",
    },
}


def _tpch_extension_path() -> Path:
    """Locate the tpch extension shipped in the duckdb-extension-tpch wheel."""
    import duckdb_extension_tpch

    root = Path(duckdb_extension_tpch.__path__[0]) / "extensions"
    matches = sorted(root.glob("*/tpch.duckdb_extension"))
    if not matches:
        raise RuntimeError(f"tpch extension not found under {root}")
    return matches[-1]


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def build_warehouse(out: Path, scale_factor: float = 0.1) -> Path:
    """Generate TPC-H at the given scale factor into ``out`` and annotate it."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    con = duckdb.connect(str(out))
    try:
        con.execute(f"LOAD '{_tpch_extension_path()}'")
        con.execute(f"CALL dbgen(sf={float(scale_factor)})")
        for table, comment in TABLE_COMMENTS.items():
            con.execute(f"COMMENT ON TABLE {table} IS {_quote(comment)}")
        for table, columns in COLUMN_COMMENTS.items():
            for column, comment in columns.items():
                con.execute(f"COMMENT ON COLUMN {table}.{column} IS {_quote(comment)}")
        con.execute("CHECKPOINT")
    finally:
        con.close()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the TPC-H demo warehouse.")
    parser.add_argument("--sf", type=float, default=0.1, help="TPC-H scale factor (0.1 is about 600k line items).")
    parser.add_argument("--out", type=Path, default=Path("data/tpch.duckdb"))
    args = parser.parse_args()
    path = build_warehouse(args.out, args.sf)
    print(f"Built {path} at scale factor {args.sf}")


if __name__ == "__main__":
    main()
