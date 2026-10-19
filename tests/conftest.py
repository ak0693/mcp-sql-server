from pathlib import Path

import pytest

from mcp_sql_server.build import build_warehouse
from mcp_sql_server.warehouse import Warehouse


@pytest.fixture(scope="session")
def warehouse_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # Scale factor 0.01 builds in about a second: ~60k line items.
    return build_warehouse(tmp_path_factory.mktemp("wh") / "tpch.duckdb", scale_factor=0.01)


@pytest.fixture
def warehouse(warehouse_path: Path):
    wh = Warehouse(warehouse_path, max_rows=50, timeout_s=2.0)
    yield wh
    wh.close()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
