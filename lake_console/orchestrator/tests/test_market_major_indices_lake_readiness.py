from __future__ import annotations

import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.asset_guards.market_major_indices_lake_readiness import (
    batch_market_major_indices_lake_readiness,
    batch_silver_index_daily_lake_readiness,
    silver_index_basic_lake_readiness,
    silver_index_daily_lake_readiness_for_trade_date,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    gold_market_major_indices_daily_path,
    raw_index_daily_path,
    silver_index_basic_path,
    silver_index_daily_path,
)
from orchestrator.seeds.market.major_indices import (
    active_major_indices_seed_rows,
    load_major_indices_seed,
)


def _date_window(count: int) -> tuple[str, ...]:
    start = date(2026, 1, 2)
    return tuple((start + timedelta(days=index)).isoformat() for index in range(count))


def _copy_index_basic(
    connection,
    root: Path,
    *,
    terminated_on: str | None = None,
) -> None:
    path = silver_index_basic_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(
        "("
        f"{duckdb_string(row.ts_code)}, "
        f"{duckdb_string(row.display_name)}, "
        "'SSE', "
        f"{('DATE ' + duckdb_string(terminated_on)) if terminated_on else 'NULL::DATE'}"
        ")"
        for row in load_major_indices_seed()
    )
    connection.execute(
        f"""
        COPY (
          SELECT
            ts_code::VARCHAR AS ts_code,
            name::VARCHAR AS name,
            name::VARCHAR AS fullname,
            market::VARCHAR AS market,
            'publisher'::VARCHAR AS publisher,
            'index'::VARCHAR AS index_type,
            'major'::VARCHAR AS category,
            DATE '1990-01-01' AS base_date,
            100.0::DOUBLE AS base_point,
            DATE '1990-01-01' AS list_date,
            'weighted'::VARCHAR AS weight_rule,
            'desc'::VARCHAR AS "desc",
            exp_date AS exp_date
          FROM (VALUES {values}) AS t(ts_code, name, market, exp_date)
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


def _copy_gold_daily(
    connection,
    root: Path,
    trade_date: str,
    *,
    invalid_price: bool = False,
    rank_offset: int = 0,
) -> None:
    path = gold_market_major_indices_daily_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(
        "("
        f"DATE {duckdb_string(trade_date)}, "
        f"{row.rank + rank_offset}, "
        f"{duckdb_string(row.ts_code)}, "
        f"{duckdb_string(row.display_name)}, "
        "10.0, "
        f"{'8.0' if invalid_price else '12.0'}, "
        "9.0, 11.0, 10.0, 1.0, 0.1, 100.0, 1000.0"
        ")"
        for row in active_major_indices_seed_rows(trade_date)
    )
    connection.execute(
        f"""
        COPY (
          SELECT
            CAST(trade_date AS DATE) AS trade_date,
            CAST(rank AS INTEGER) AS rank,
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(display_name AS VARCHAR) AS display_name,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(pre_close AS DOUBLE) AS pre_close,
            CAST(change_amount AS DOUBLE) AS change_amount,
            CAST(pct_chg AS DOUBLE) AS pct_chg,
            CAST(vol AS DOUBLE) AS vol,
            CAST(amount AS DOUBLE) AS amount
          FROM (VALUES {values}) AS t(
            trade_date, rank, ts_code, display_name, open, high, low, close,
            pre_close, change_amount, pct_chg, vol, amount
          )
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


def _copy_silver_daily_and_raw(
    connection,
    root: Path,
    trade_date: str,
) -> None:
    seed_rows = active_major_indices_seed_rows(trade_date)
    raw_path = raw_index_daily_path(root, trade_date)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_values = ", ".join(
        "("
        f"{duckdb_string(row.ts_code)}, "
        f"{duckdb_string(trade_date.replace('-', ''))}, "
        "10.0, 12.0, 9.0, 11.0, 10.0, 1.0, 0.1, 100.0, 1000.0"
        ")"
        for row in seed_rows
    )
    connection.execute(
        f"""
        COPY (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS VARCHAR) AS trade_date,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(pre_close AS DOUBLE) AS pre_close,
            CAST(change AS DOUBLE) AS change,
            CAST(pct_chg AS DOUBLE) AS pct_chg,
            CAST(vol AS DOUBLE) AS vol,
            CAST(amount AS DOUBLE) AS amount
          FROM (VALUES {raw_values}) AS t(
            ts_code, trade_date, open, high, low, close, pre_close,
            change, pct_chg, vol, amount
          )
        ) TO {duckdb_string(raw_path)} (FORMAT PARQUET)
        """
    )
    silver_path = silver_index_daily_path(root, trade_date)
    silver_path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(
        "("
        f"{duckdb_string(row.ts_code)}, "
        f"DATE {duckdb_string(trade_date)}, "
        "10.0, 12.0, 9.0, 11.0, 10.0, 1.0, 0.1, 100.0, 1000.0"
        ")"
        for row in seed_rows
    )
    connection.execute(
        f"""
        COPY (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(pre_close AS DOUBLE) AS pre_close,
            CAST(change_amount AS DOUBLE) AS change_amount,
            CAST(pct_chg AS DOUBLE) AS pct_chg,
            CAST(vol AS DOUBLE) AS vol,
            CAST(amount AS DOUBLE) AS amount
          FROM (VALUES {values}) AS t(
            ts_code, trade_date, open, high, low, close, pre_close,
            change_amount, pct_chg, vol, amount
          )
        ) TO {duckdb_string(silver_path)} (FORMAT PARQUET)
        """
    )


class MarketMajorIndicesLakeReadinessTests(unittest.TestCase):
    def test_gold_batch_ready_for_sixty_day_window(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            trade_dates = _date_window(60)
            with connect_configured_duckdb() as connection:
                _copy_index_basic(connection, root)
                for trade_date in trade_dates:
                    _copy_gold_daily(connection, root, trade_date)
                status = batch_market_major_indices_lake_readiness(
                    connection=connection,
                    lake_root_path=root,
                    expected_trade_dates=trade_dates,
                    registered_index_codes=tuple(
                        row.ts_code for row in load_major_indices_seed()
                    ),
                )

            self.assertEqual(status.expected_trade_dates, trade_dates)
            self.assertTrue(all(item.ready for item in status.statuses_by_trade_date.values()))
            self.assertEqual(status.scanned_file_count, 60)

    def test_gold_batch_missing_file_is_not_materialized(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            trade_dates = _date_window(2)
            with connect_configured_duckdb() as connection:
                _copy_index_basic(connection, root)
                _copy_gold_daily(connection, root, trade_dates[1])
                status = batch_market_major_indices_lake_readiness(
                    connection=connection,
                    lake_root_path=root,
                    expected_trade_dates=trade_dates,
                    registered_index_codes=tuple(
                        row.ts_code for row in load_major_indices_seed()
                    ),
                )

            missing_status = status.status_for_trade_date(trade_dates[0])
            self.assertFalse(missing_status.ready)
            self.assertFalse(missing_status.materialized)
            self.assertIn(
                "gold_market_major_indices_daily_contract_check",
                missing_status.missing_check_names,
            )

    def test_gold_batch_existing_bad_file_is_materialized_check_problem(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            trade_date = _date_window(1)[0]
            with connect_configured_duckdb() as connection:
                _copy_index_basic(connection, root)
                _copy_gold_daily(connection, root, trade_date, invalid_price=True)
                status = batch_market_major_indices_lake_readiness(
                    connection=connection,
                    lake_root_path=root,
                    expected_trade_dates=(trade_date,),
                    registered_index_codes=tuple(
                        row.ts_code for row in load_major_indices_seed()
                    ),
                ).status_for_trade_date(trade_date)

            self.assertFalse(status.ready)
            self.assertTrue(status.materialized)
            self.assertFalse(status.checks_passed)
            self.assertIn(
                "gold_market_major_indices_daily_value_domain_check",
                status.failed_check_names,
            )

    def test_silver_index_daily_selected_date_ready(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            trade_date = "2026-06-15"
            with connect_configured_duckdb() as connection:
                _copy_silver_daily_and_raw(connection, root, trade_date)
                status = silver_index_daily_lake_readiness_for_trade_date(
                    connection=connection,
                    lake_root_path=root,
                    trade_date=trade_date,
                    registered_index_codes=tuple(
                        row.ts_code for row in active_major_indices_seed_rows(trade_date)
                    ),
                )

            self.assertTrue(status.ready)
            self.assertTrue(status.checks_passed)

    def test_silver_index_daily_batch_statuses_use_lake_readiness(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            trade_dates = ("2026-06-15", "2026-06-16")
            with connect_configured_duckdb() as connection:
                for trade_date in trade_dates:
                    _copy_silver_daily_and_raw(connection, root, trade_date)
                raw_index_daily_path(root, trade_dates[0]).unlink()
                batch_status = batch_silver_index_daily_lake_readiness(
                    connection=connection,
                    lake_root_path=root,
                    expected_trade_dates=trade_dates,
                    registered_index_codes=tuple(
                        row.ts_code
                        for row in active_major_indices_seed_rows(trade_dates[1])
                    ),
                )

            first_status = batch_status.status_for_trade_date(trade_dates[0])
            second_status = batch_status.status_for_trade_date(trade_dates[1])
            self.assertFalse(first_status.ready)
            self.assertFalse(first_status.materialized)
            self.assertIn(
                "silver_index_daily_registered_code_coverage_check",
                first_status.missing_check_names,
            )
            self.assertTrue(second_status.ready)

    def test_silver_index_daily_missing_raw_by_date_is_not_ready(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            trade_date = "2026-06-15"
            with connect_configured_duckdb() as connection:
                _copy_silver_daily_and_raw(connection, root, trade_date)
                raw_index_daily_path(root, trade_date).unlink()
                status = silver_index_daily_lake_readiness_for_trade_date(
                    connection=connection,
                    lake_root_path=root,
                    trade_date=trade_date,
                    registered_index_codes=tuple(
                        row.ts_code for row in active_major_indices_seed_rows(trade_date)
                    ),
                )

            self.assertFalse(status.ready)
            self.assertFalse(status.materialized)
            self.assertIn(
                "silver_index_daily_registered_code_coverage_check",
                status.missing_check_names,
            )

    def test_silver_index_basic_uses_selected_target_date_for_terminated_indexes(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with connect_configured_duckdb() as connection:
                _copy_index_basic(connection, root, terminated_on="2026-06-15")
                ready_before_expiry = silver_index_basic_lake_readiness(
                    connection=connection,
                    lake_root_path=root,
                    ready_for_trade_date="2026-06-14",
                )
                failed_on_expiry = silver_index_basic_lake_readiness(
                    connection=connection,
                    lake_root_path=root,
                    ready_for_trade_date="2026-06-15",
                )

            self.assertTrue(ready_before_expiry.ready)
            self.assertFalse(failed_on_expiry.ready)
            self.assertIn(
                "silver_index_basic_no_terminated_indexes",
                failed_on_expiry.failed_check_names,
            )


if __name__ == "__main__":
    unittest.main()
