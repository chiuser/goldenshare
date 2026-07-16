from __future__ import annotations

from pathlib import Path

import duckdb

from orchestrator.defs.assets.dc_board import (
    write_dc_daily_partition,
    write_dc_index_partition,
    write_dc_member_rows_streaming,
)
from orchestrator.defs.assets.dc_board_silver import (
    write_silver_dc_daily_partition,
    write_silver_dc_index_partition,
    write_silver_dc_member_partition,
)
from orchestrator.defs.paths import (
    raw_dc_daily_path,
    raw_dc_index_path,
    raw_dc_member_path,
    silver_dc_daily_path,
    silver_dc_index_path,
    silver_dc_member_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.dc_board import DC_INDEX_TYPES
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy


class _MemoryDuckDB:
    def connect(self):
        connection = duckdb.connect(":memory:")

        class _Context:
            def __enter__(self):
                return connection

            def __exit__(self, exc_type, exc, tb):
                connection.close()
                return False

        return _Context()


class _FakeTushare:
    def call(self, api_name, params, fields):
        trade_date = params["trade_date"]
        if params["offset"]:
            return TushareResult(rows=[], columns=tuple(fields), metadata={})
        if api_name == "dc_index":
            idx_type = params["idx_type"]
            row = {
                "ts_code": f"BK{DC_INDEX_TYPES.index(idx_type) + 1:04d}.DC",
                "trade_date": trade_date,
                "name": "板块",
                "leading": "股票",
                "leading_code": "000001.SZ",
                "pct_change": 1.0,
                "leading_pct": 1.0,
                "total_mv": 100.0,
                "turnover_rate": 1.0,
                "up_num": 1,
                "down_num": 1,
                "idx_type": idx_type,
                "level": "L1",
            }
            return TushareResult(rows=[row], columns=tuple(fields), metadata={})
        if api_name == "dc_daily":
            rows = []
            code_by_category = {
                "行业板块": "BK0001.DC",
                "概念板块": "BK0002.DC",
                "地域板块": "BK0003.DC",
            }
            for category, ts_code in code_by_category.items():
                rows.append(
                    {
                        "ts_code": ts_code,
                        "trade_date": trade_date,
                        "close": 10.0,
                        "open": 9.0,
                        "high": 11.0,
                        "low": 8.0,
                        "change": 1.0,
                        "pct_change": 10.0,
                        "vol": 100.0,
                        "amount": 1000.0,
                        "swing": 3.0,
                        "turnover_rate": 1.0,
                        "category": category,
                    }
                )
            return TushareResult(rows=rows, columns=tuple(fields), metadata={})
        raise AssertionError(api_name)


def _write_calendar(root: Path, dates: tuple[str, ...]) -> None:
    path = silver_trade_calendar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(
        f"('SSE', DATE '{trade_date}', TRUE, NULL::DATE)" for trade_date in dates
    )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) AS t(exchange, trade_date, is_open, pretrade_date)) "
            "TO ? (FORMAT PARQUET)",
            [str(path)],
        )


def _policy() -> TushareRequestPolicy:
    return TushareRequestPolicy(
        minimum_interval_seconds=0,
        max_retries=0,
        max_requests=50,
        max_elapsed_seconds=30,
    )


def test_m7_sample_raw_to_silver_three_dates_uses_atomic_temp_lake(tmp_path):
    root = Path(tmp_path)
    dates = ("2024-12-20", "2025-12-29", "2026-07-14")
    _write_calendar(root, dates)
    tushare = _FakeTushare()
    duckdb_resource = _MemoryDuckDB()

    for trade_date in dates:
        compact_date = trade_date.replace("-", "")
        write_dc_index_partition(
            lake_root_path=root,
            duckdb_resource=duckdb_resource,
            tushare=tushare,
            partition_key=trade_date,
            policy=_policy(),
        )
        write_dc_daily_partition(
            lake_root_path=root,
            duckdb_resource=duckdb_resource,
            tushare=tushare,
            partition_key=trade_date,
            policy=_policy(),
        )
        write_dc_member_rows_streaming(
            lake_root_path=root,
            duckdb_resource=duckdb_resource,
            partition_key=trade_date,
            chunks=(
                (
                    {
                        "trade_date": compact_date,
                        "ts_code": "BK0001.DC",
                        "con_code": "000001.SZ",
                        "name": "股票",
                    },
                ),
            ),
        )

        write_silver_dc_index_partition(
            lake_root_path=root,
            duckdb=duckdb_resource,
            partition_key=trade_date,
        )
        write_silver_dc_member_partition(
            lake_root_path=root,
            duckdb=duckdb_resource,
            partition_key=trade_date,
        )
        write_silver_dc_daily_partition(
            lake_root_path=root,
            duckdb=duckdb_resource,
            partition_key=trade_date,
        )

    with duckdb.connect(":memory:") as connection:
        for builder in (
            raw_dc_index_path,
            raw_dc_member_path,
            raw_dc_daily_path,
            silver_dc_index_path,
            silver_dc_member_path,
            silver_dc_daily_path,
        ):
            paths = [builder(root, trade_date) for trade_date in dates]
            assert all(
                connection.execute(
                    "SELECT count(*) FROM read_parquet(?)", [str(path)]
                ).fetchone()[0] > 0
                for path in paths
            )
        assert not list(root.rglob("*.staging-*"))
