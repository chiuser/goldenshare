from __future__ import annotations

import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.asset_guards.market_breadth_lake_readiness import (
    batch_clickhouse_market_breadth_readiness,
    batch_gold_market_breadth_lake_readiness,
    batch_gold_stock_return_distribution_lake_readiness,
    batch_prod_clickhouse_market_breadth_readiness,
)
from orchestrator.defs.assets.clickhouse_serving import (
    CLICKHOUSE_MARKET_BREADTH_COLUMNS,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    gold_market_breadth_daily_path,
    gold_stock_return_distribution_path,
    silver_stock_daily_path,
)


DATE_1 = "2026-06-15"
DATE_2 = "2026-06-16"


class _FakeClickHouseClient:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = list(rows)
        self.execute_count = 0

    def execute(self, query: str, params=None):
        self.execute_count += 1
        selected_dates = {
            value.isoformat() if hasattr(value, "isoformat") else str(value)
            for key, value in (params or {}).items()
            if key.startswith("trade_date_")
        }
        return [
            row
            for row in sorted(self.rows, key=lambda item: item[0])
            if (row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]))
            in selected_dates
        ]


def _copy_silver_stock_daily(connection, root: Path, trade_date: str) -> None:
    path = silver_stock_daily_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT *
          FROM (VALUES
            ('000001.SZ', DATE {duckdb_string(trade_date)}, 1.0),
            ('000002.SZ', DATE {duckdb_string(trade_date)}, 0.0),
            ('000003.SZ', DATE {duckdb_string(trade_date)}, -1.0)
          ) AS t(ts_code, trade_date, pct_chg)
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


def _copy_gold_breadth(
    connection,
    root: Path,
    trade_date: str,
    *,
    up_count: int = 1,
) -> None:
    path = gold_market_breadth_daily_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT
            DATE {duckdb_string(trade_date)} AS trade_date,
            {up_count}::BIGINT AS up_count,
            1::BIGINT AS down_count,
            1::BIGINT AS flat_count,
            3::BIGINT AS total_count,
            33.33::DOUBLE AS red_rate
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


def _copy_gold_distribution(connection, root: Path, trade_date: str) -> None:
    path = gold_stock_return_distribution_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT
            DATE {duckdb_string(trade_date)} AS trade_date,
            0::BIGINT AS down_gt_10_count,
            0::BIGINT AS down_7_10_count,
            0::BIGINT AS down_5_7_count,
            0::BIGINT AS down_3_5_count,
            1::BIGINT AS down_0_3_count,
            1::BIGINT AS flat_count,
            1::BIGINT AS up_0_3_count,
            0::BIGINT AS up_3_5_count,
            0::BIGINT AS up_5_7_count,
            0::BIGINT AS up_7_10_count,
            0::BIGINT AS up_gt_10_count,
            3::BIGINT AS total_count
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


def _clickhouse_row(
    trade_date: str,
    *,
    up_count: int = 1,
    updated_at: str = "2026-06-20 16:00:00",
) -> tuple:
    values = {
        "trade_date": date.fromisoformat(trade_date),
        "up_count": up_count,
        "down_count": 1,
        "flat_count": 1,
        "total_count": 3,
        "red_rate": 33.33,
        "down_gt_10_count": 0,
        "down_7_10_count": 0,
        "down_5_7_count": 0,
        "down_3_5_count": 0,
        "down_0_3_count": 1,
        "up_0_3_count": 1,
        "up_3_5_count": 0,
        "up_5_7_count": 0,
        "up_7_10_count": 0,
        "up_gt_10_count": 0,
        "updated_at": datetime.fromisoformat(updated_at),
    }
    return tuple(values[column] for column in CLICKHOUSE_MARKET_BREADTH_COLUMNS)


class MarketBreadthLakeReadinessTests(unittest.TestCase):
    def test_gold_breadth_batch_ready_for_window(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with connect_configured_duckdb() as connection:
                for trade_date in (DATE_1, DATE_2):
                    _copy_silver_stock_daily(connection, root, trade_date)
                    _copy_gold_breadth(connection, root, trade_date)
                status = batch_gold_market_breadth_lake_readiness(
                    connection=connection,
                    lake_root_path=root,
                    expected_trade_dates=(DATE_1, DATE_2),
                )

        self.assertTrue(status.status_for_trade_date(DATE_1).ready)
        self.assertTrue(status.status_for_trade_date(DATE_2).ready)
        self.assertEqual(status.scanned_file_count, 2)

    def test_gold_breadth_missing_file_is_not_materialized(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with connect_configured_duckdb() as connection:
                _copy_silver_stock_daily(connection, root, DATE_2)
                _copy_gold_breadth(connection, root, DATE_2)
                status = batch_gold_market_breadth_lake_readiness(
                    connection=connection,
                    lake_root_path=root,
                    expected_trade_dates=(DATE_1, DATE_2),
                ).status_for_trade_date(DATE_1)

        self.assertFalse(status.ready)
        self.assertFalse(status.materialized)
        self.assertIn("gold_market_breadth_row_count_is_one", status.missing_check_names)

    def test_gold_breadth_existing_bad_file_blocks_later_dates(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with connect_configured_duckdb() as connection:
                _copy_silver_stock_daily(connection, root, DATE_1)
                _copy_gold_breadth(connection, root, DATE_1, up_count=2)
                status = batch_gold_market_breadth_lake_readiness(
                    connection=connection,
                    lake_root_path=root,
                    expected_trade_dates=(DATE_1,),
                ).status_for_trade_date(DATE_1)

        self.assertFalse(status.ready)
        self.assertTrue(status.materialized)
        self.assertIn("gold_market_breadth_counts_add_up", status.failed_check_names)

    def test_gold_distribution_batch_ready(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with connect_configured_duckdb() as connection:
                _copy_silver_stock_daily(connection, root, DATE_1)
                _copy_gold_distribution(connection, root, DATE_1)
                status = batch_gold_stock_return_distribution_lake_readiness(
                    connection=connection,
                    lake_root_path=root,
                    expected_trade_dates=(DATE_1,),
                ).status_for_trade_date(DATE_1)

        self.assertTrue(status.ready)

    def test_clickhouse_readiness_batches_selected_dates_once(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            client = _FakeClickHouseClient([_clickhouse_row(DATE_1)])
            with connect_configured_duckdb() as connection:
                _copy_silver_stock_daily(connection, root, DATE_1)
                _copy_gold_breadth(connection, root, DATE_1)
                _copy_gold_distribution(connection, root, DATE_1)
                status = batch_clickhouse_market_breadth_readiness(
                    connection=connection,
                    lake_root_path=root,
                    clickhouse_client=client,
                    expected_trade_dates=(DATE_1,),
                ).status_for_trade_date(DATE_1)

        self.assertTrue(status.ready)
        self.assertEqual(client.execute_count, 1)

    def test_clickhouse_missing_row_is_not_materialized(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            client = _FakeClickHouseClient([])
            with connect_configured_duckdb() as connection:
                status = batch_clickhouse_market_breadth_readiness(
                    connection=connection,
                    lake_root_path=root,
                    clickhouse_client=client,
                    expected_trade_dates=(DATE_1,),
                ).status_for_trade_date(DATE_1)

        self.assertFalse(status.ready)
        self.assertFalse(status.materialized)
        self.assertEqual(client.execute_count, 1)

    def test_prod_clickhouse_readiness_compares_local_and_prod_once(self) -> None:
        local_client = _FakeClickHouseClient([_clickhouse_row(DATE_1)])
        prod_client = _FakeClickHouseClient([_clickhouse_row(DATE_1)])

        status = batch_prod_clickhouse_market_breadth_readiness(
            local_clickhouse_client=local_client,
            prod_clickhouse_client=prod_client,
            expected_trade_dates=(DATE_1,),
        ).status_for_trade_date(DATE_1)

        self.assertTrue(status.ready)
        self.assertEqual(local_client.execute_count, 1)
        self.assertEqual(prod_client.execute_count, 1)


if __name__ == "__main__":
    unittest.main()
