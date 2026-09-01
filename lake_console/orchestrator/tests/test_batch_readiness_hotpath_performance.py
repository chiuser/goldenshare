import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.asset_guards.adj_factor_lake_readiness import (
    batch_adj_factor_lake_readiness,
    batch_raw_adj_factor_lake_readiness,
    batch_silver_adj_factor_lake_readiness,
)
from orchestrator.defs.asset_guards.market_breadth_lake_readiness import (
    batch_clickhouse_market_breadth_readiness,
    batch_gold_market_breadth_lake_readiness,
    batch_gold_stock_return_distribution_lake_readiness,
    batch_prod_clickhouse_market_breadth_readiness,
)
from orchestrator.defs.asset_guards.market_major_indices_lake_readiness import (
    batch_market_major_indices_lake_readiness,
)
from orchestrator.defs.asset_guards.stk_nineturn_lake_readiness import (
    batch_raw_stk_nineturn_lake_readiness,
    batch_silver_stock_nineturn_daily_lake_readiness,
)
from orchestrator.defs.asset_guards.stock_daily_trend_channel_lake_readiness import (
    batch_gold_stock_daily_trend_channel_readiness,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.seeds.market.major_indices import load_major_indices_seed
from tests.test_market_breadth_lake_readiness import (
    _clickhouse_row,
    _copy_gold_breadth,
    _copy_gold_distribution,
    _copy_silver_stock_daily,
    _FakeClickHouseClient,
)
from tests.test_market_major_indices_lake_readiness import (
    _copy_gold_daily,
    _copy_index_basic,
)
from tests.test_stk_mins_lake_readiness import (
    _write_adj_factor_files,
    _write_adj_factor_stock_lifecycle_file,
)
from tests.test_stk_nineturn_lake_readiness import (
    _write_identity,
    _write_raw,
    _write_silver,
)
from tests.test_stock_daily_trend_channel_m4 import _write_ready_days

ADJ_FACTOR_10_DAY_BUDGET_MS = 10_000
MARKET_MAJOR_INDICES_10_DAY_BUDGET_MS = 3_000
MARKET_BREADTH_10_DAY_BUDGET_MS = 3_000
CLICKHOUSE_10_DAY_BUDGET_MS = 3_000
STK_NINETURN_10_DAY_BUDGET_MS = 5_000
STOCK_DAILY_TREND_CHANNEL_10_DAY_BUDGET_MS = 5_000


def _ten_trade_dates() -> tuple[str, ...]:
    start = date(2026, 6, 1)
    return tuple((start + timedelta(days=index)).isoformat() for index in range(10))


def _assert_batch_ready(test_case, batch_status) -> None:
    test_case.assertTrue(
        all(status.ready for status in batch_status.statuses_by_trade_date.values()),
        batch_status.to_cursor_details(),
    )


class BatchReadinessHotPathPerformanceTests(unittest.TestCase):
    def test_stock_daily_trend_channel_batch_helper_covers_ten_day_budget(
        self,
    ) -> None:
        start = date(2026, 6, 1)
        all_trade_dates = tuple(
            (start + timedelta(days=index)).isoformat() for index in range(11)
        )
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            root = Path(directory) / "lake"
            _write_ready_days(
                connection,
                root=root,
                staging=Path(directory) / "staging",
                trade_dates=all_trade_dates,
            )
            batch_status = batch_gold_stock_daily_trend_channel_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=all_trade_dates[1:],
                previous_trade_date=all_trade_dates[0],
            )

        _assert_batch_ready(self, batch_status)
        self.assertEqual(batch_status.sql_count, 2)
        self.assertEqual(batch_status.scanned_file_count, 21)
        self.assertLess(
            batch_status.elapsed_ms,
            STOCK_DAILY_TREND_CHANNEL_10_DAY_BUDGET_MS,
            batch_status.to_cursor_details(),
        )

    def test_stk_nineturn_batch_helpers_cover_ten_day_budget(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            trade_dates = _ten_trade_dates()
            _write_identity(lake_root)
            for trade_date in trade_dates:
                _write_raw(lake_root, trade_date)
                _write_silver(lake_root, trade_date)
            with connect_configured_duckdb() as connection:
                raw_status = batch_raw_stk_nineturn_lake_readiness(
                    connection=connection,
                    lake_root=lake_root,
                    expected_trade_dates=trade_dates,
                    registered_trade_days=set(trade_dates),
                )
                silver_status = batch_silver_stock_nineturn_daily_lake_readiness(
                    connection=connection,
                    lake_root=lake_root,
                    expected_trade_dates=trade_dates,
                    registered_trade_days=set(trade_dates),
                )

        for batch_status in (raw_status, silver_status):
            _assert_batch_ready(self, batch_status)
            self.assertEqual(batch_status.expected_trade_dates, trade_dates)
            self.assertLess(
                batch_status.elapsed_ms,
                STK_NINETURN_10_DAY_BUDGET_MS,
                batch_status.to_cursor_details(),
            )

    def test_adj_factor_batch_helpers_cover_ten_day_hot_path_budget(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            trade_dates = _ten_trade_dates()
            _write_adj_factor_stock_lifecycle_file(connection, lake_root)
            for trade_date in trade_dates:
                _write_adj_factor_files(
                    connection,
                    lake_root,
                    trade_date=trade_date,
                )

            raw_status = batch_raw_adj_factor_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates,
                registered_trade_days=trade_dates,
            )
            silver_status = batch_silver_adj_factor_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates,
                registered_trade_days=trade_dates,
            )
            combined_status = batch_adj_factor_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates,
                registered_trade_days=trade_dates,
            )

        for batch_status in (raw_status, silver_status, combined_status):
            _assert_batch_ready(self, batch_status)
            self.assertEqual(batch_status.expected_trade_dates, trade_dates)
            self.assertEqual(batch_status.scanned_file_count, len(trade_dates) * 2)
            self.assertLess(
                batch_status.elapsed_ms,
                ADJ_FACTOR_10_DAY_BUDGET_MS,
                batch_status.to_cursor_details(),
            )

    def test_market_major_indices_batch_helper_covers_ten_day_budget(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            trade_dates = _ten_trade_dates()
            with connect_configured_duckdb() as connection:
                _copy_index_basic(connection, lake_root)
                for trade_date in trade_dates:
                    _copy_gold_daily(connection, lake_root, trade_date)
                batch_status = batch_market_major_indices_lake_readiness(
                    connection=connection,
                    lake_root_path=lake_root,
                    expected_trade_dates=trade_dates,
                    registered_index_codes=tuple(
                        row.ts_code for row in load_major_indices_seed()
                    ),
                )

        _assert_batch_ready(self, batch_status)
        self.assertEqual(batch_status.expected_trade_dates, trade_dates)
        self.assertEqual(batch_status.scanned_file_count, len(trade_dates))
        self.assertLess(
            batch_status.elapsed_ms,
            MARKET_MAJOR_INDICES_10_DAY_BUDGET_MS,
            batch_status.to_cursor_details(),
        )

    def test_market_breadth_batch_helpers_cover_ten_day_budget(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            trade_dates = _ten_trade_dates()
            with connect_configured_duckdb() as connection:
                for trade_date in trade_dates:
                    _copy_silver_stock_daily(connection, lake_root, trade_date)
                    _copy_gold_breadth(connection, lake_root, trade_date)
                    _copy_gold_distribution(connection, lake_root, trade_date)

                breadth_status = batch_gold_market_breadth_lake_readiness(
                    connection=connection,
                    lake_root_path=lake_root,
                    expected_trade_dates=trade_dates,
                )
                distribution_status = (
                    batch_gold_stock_return_distribution_lake_readiness(
                        connection=connection,
                        lake_root_path=lake_root,
                        expected_trade_dates=trade_dates,
                    )
                )

        for batch_status in (breadth_status, distribution_status):
            _assert_batch_ready(self, batch_status)
            self.assertEqual(batch_status.expected_trade_dates, trade_dates)
            self.assertEqual(batch_status.scanned_file_count, len(trade_dates))
            self.assertLess(
                batch_status.elapsed_ms,
                MARKET_BREADTH_10_DAY_BUDGET_MS,
                batch_status.to_cursor_details(),
            )

    def test_clickhouse_batch_helpers_fetch_partition_set_once(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            trade_dates = _ten_trade_dates()
            clickhouse_client = _FakeClickHouseClient(
                [_clickhouse_row(trade_date) for trade_date in trade_dates]
            )
            with connect_configured_duckdb() as connection:
                for trade_date in trade_dates:
                    _copy_silver_stock_daily(connection, lake_root, trade_date)
                    _copy_gold_breadth(connection, lake_root, trade_date)
                    _copy_gold_distribution(connection, lake_root, trade_date)

                batch_status = batch_clickhouse_market_breadth_readiness(
                    connection=connection,
                    lake_root_path=lake_root,
                    clickhouse_client=clickhouse_client,
                    expected_trade_dates=trade_dates,
                )

        _assert_batch_ready(self, batch_status)
        self.assertEqual(clickhouse_client.execute_count, 1)
        self.assertEqual(batch_status.scanned_file_count, len(trade_dates))
        self.assertLess(
            batch_status.elapsed_ms,
            CLICKHOUSE_10_DAY_BUDGET_MS,
            batch_status.to_cursor_details(),
        )

    def test_prod_clickhouse_batch_helper_fetches_local_and_prod_once(self) -> None:
        trade_dates = _ten_trade_dates()
        local_client = _FakeClickHouseClient(
            [_clickhouse_row(trade_date) for trade_date in trade_dates]
        )
        prod_client = _FakeClickHouseClient(
            [_clickhouse_row(trade_date) for trade_date in trade_dates]
        )

        batch_status = batch_prod_clickhouse_market_breadth_readiness(
            local_clickhouse_client=local_client,
            prod_clickhouse_client=prod_client,
            expected_trade_dates=trade_dates,
        )

        _assert_batch_ready(self, batch_status)
        self.assertEqual(local_client.execute_count, 1)
        self.assertEqual(prod_client.execute_count, 1)
        self.assertEqual(batch_status.scanned_file_count, len(trade_dates))
        self.assertLess(
            batch_status.elapsed_ms,
            CLICKHOUSE_10_DAY_BUDGET_MS,
            batch_status.to_cursor_details(),
        )


if __name__ == "__main__":
    unittest.main()
