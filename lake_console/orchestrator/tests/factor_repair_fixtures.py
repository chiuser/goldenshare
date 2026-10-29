"""Small lifecycle fixtures matching SILVER_STOCK_LIFECYCLE_SCHEMA.

The producer contract is defs/assets/stock_lifecycle.py and the schema in
defs/run_contracts/asset_column_schemas.py. Values below are declared test facts,
not outputs inferred from the repair implementation.
"""

from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_STOCK_LIFECYCLE_SCHEMA,
)


@pytest.fixture
def isolated_factor_repair_connections(tmp_path, monkeypatch):
    """Keep real configured DuckDB, replacing only its test-owned temp path.

    Marked tests never inherit /Volumes/datasource/.goldenshare_duckdb_tmp.
    Memory, threads and temp-size settings and all real SQL remain unchanged.
    """
    from orchestrator.defs import duckdb_connection, resources, stk_mins_qfq
    from orchestrator.defs import stk_mins_qfq_factor_repair as repair

    actual = duckdb_connection.connect_configured_duckdb
    directory = tmp_path / "configured_duckdb_temp"
    directory.mkdir()

    @contextmanager
    def connection(settings=duckdb_connection.DEFAULT_DUCKDB_CONNECTION_SETTINGS,
                   *, temp_policy="managed"):
        isolated = replace(settings, temp_directory=directory)
        with actual(isolated, temp_policy=temp_policy) as con:
            yield con

    for module in (resources, stk_mins_qfq, repair):
        monkeypatch.setattr(module, "connect_configured_duckdb", connection)
    yield directory


def write_repair_lifecycle(path: Path, rows: Sequence[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column.name for column in SILVER_STOCK_LIFECYCLE_SCHEMA)
    values = []
    for row in rows:
        code = row["ts_code"]
        declared = {
            "ts_code": code, "symbol": code.split(".")[0], "name": "fixture stock",
            "exchange": "SSE" if code.endswith(".SH") else "SZSE",
            "market": "主板", "curr_type": "CNY", "is_cny_stock": True,
            "list_status": "L", "list_date": "2000-01-01", "delist_date": None,
        } | row
        values.append([declared[column] for column in columns])
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TEMP TABLE lifecycle (" + ",".join(
            f'"{column.name}" {column.type}' for column in SILVER_STOCK_LIFECYCLE_SCHEMA
        ) + ")")
        if values:
            connection.executemany("INSERT INTO lifecycle VALUES (" + ",".join("?" for _ in columns) + ")", values)
        connection.execute(copy_query_to_parquet("SELECT * FROM lifecycle ORDER BY ts_code", path))
    return path
