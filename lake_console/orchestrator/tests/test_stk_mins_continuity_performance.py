import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    batch_gold_stk_mins_qfq_lake_readiness,
    batch_raw_stk_mins_lake_readiness,
    batch_silver_stk_mins_lake_readiness,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
)
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    expected_canonical_gold_source_times,
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    STK_MINS_QFQ_DERIVED_FREQS,
    STK_MINS_QFQ_NATIVE_FREQS,
)
from orchestrator.defs.stk_mins_qfq import (
    build_canonical_gold_stk_mins_qfq_select_sql,
    gold_stk_mins_qfq_source_freq,
)
from tests.test_stk_mins_lake_readiness import (
    _trade_dates,
    _write_adj_factor_files,
    _write_raw_file,
    _write_silver_file,
    _write_silver_file_for_times,
    _write_silver_ready_inputs,
    _write_stock_lifecycle_file,
)

RAW_10_DAY_BUDGET_MS = 5_000
RAW_60_DAY_BUDGET_MS = 5_000
SILVER_10_DAY_BUDGET_MS = 5_000
SILVER_60_DAY_BUDGET_MS = 7_000
GOLD_QFQ_10_DAY_BUDGET_MS = 15_000
GOLD_QFQ_60_DAY_BUDGET_MS = 15_000


def _write_raw_ready_window(
    connection,
    lake_root: Path,
    trade_dates: tuple[str, ...],
) -> None:
    for trade_date in trade_dates:
        for freq in STK_MINS_FREQS:
            _write_raw_file(
                connection,
                lake_root,
                trade_date=trade_date,
                freq=freq,
            )


def _write_silver_ready_window(
    connection,
    lake_root: Path,
    trade_dates: tuple[str, ...],
) -> None:
    _write_stock_lifecycle_file(connection, lake_root)
    for trade_date in trade_dates:
        _write_silver_ready_inputs(connection, lake_root, trade_date=trade_date)
        for freq in STK_MINS_FREQS:
            _write_silver_file(
                connection,
                lake_root,
                trade_date=trade_date,
                freq=freq,
            )


def _write_gold_qfq_year_file(
    connection,
    lake_root: Path,
    *,
    target_freq: int,
    trade_dates: tuple[str, ...],
    ts_code: str = "000001.SZ",
) -> None:
    source_freq = gold_stk_mins_qfq_source_freq(target_freq)
    silver_paths = tuple(
        silver_stk_mins_path(lake_root, source_freq, trade_date)
        for trade_date in trade_dates
    )
    adj_factor_paths = tuple(
        silver_adj_factor_path(lake_root, trade_date) for trade_date in trade_dates
    )
    target_path = gold_stk_mins_qfq_path(lake_root, target_freq, ts_code, "2026")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    qfq_sql = build_canonical_gold_stk_mins_qfq_select_sql(
        silver_paths=silver_paths,
        trade_adj_factor_paths=adj_factor_paths,
        as_of_adj_factor_paths=adj_factor_paths,
        target_freq=target_freq,
        partition_keys=trade_dates,
        stock_codes=(ts_code,),
        match_as_of_by_trade_date=True,
    )
    connection.execute(
        f"""
        COPY (
          {qfq_sql}
        ) TO {duckdb_string(target_path)} (FORMAT PARQUET)
        """
    )


def _write_gold_qfq_ready_window(
    connection,
    lake_root: Path,
    trade_dates: tuple[str, ...],
) -> None:
    source_times_by_freq: dict[int, tuple[str, ...]] = {}
    for target_freq in (*STK_MINS_QFQ_NATIVE_FREQS, *STK_MINS_QFQ_DERIVED_FREQS):
        source_freq = gold_stk_mins_qfq_source_freq(target_freq)
        source_times_by_freq[source_freq] = tuple(
            dict.fromkeys(
                (
                    *source_times_by_freq.get(source_freq, ()),
                    *expected_canonical_gold_source_times(target_freq),
                )
            )
        )
    for trade_date in trade_dates:
        _write_adj_factor_files(connection, lake_root, trade_date=trade_date)
        for source_freq, trade_times in source_times_by_freq.items():
            _write_silver_file_for_times(
                connection,
                lake_root,
                trade_date=trade_date,
                freq=source_freq,
                trade_times=trade_times,
            )
    for target_freq in (*STK_MINS_QFQ_NATIVE_FREQS, *STK_MINS_QFQ_DERIVED_FREQS):
        _write_gold_qfq_year_file(
            connection,
            lake_root,
            target_freq=target_freq,
            trade_dates=trade_dates,
        )


class StkMinsContinuityPerformanceTests(unittest.TestCase):
    def test_raw_and_silver_batch_readiness_20_and_60_day_budget(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            trade_dates = _trade_dates(60)
            _write_raw_ready_window(connection, lake_root, trade_dates)
            _write_silver_ready_window(connection, lake_root, trade_dates)

            raw_10 = batch_raw_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates[-10:],
                registered_trade_days=trade_dates,
            )
            raw_20 = batch_raw_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates[-20:],
                registered_trade_days=trade_dates,
            )
            raw_60 = batch_raw_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates,
                registered_trade_days=trade_dates,
            )
            silver_10 = batch_silver_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates[-10:],
                registered_trade_days=trade_dates,
            )
            silver_20 = batch_silver_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates[-20:],
                registered_trade_days=trade_dates,
            )
            silver_60 = batch_silver_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates,
                registered_trade_days=trade_dates,
            )

        for batch_status in (raw_10, raw_20, raw_60, silver_10, silver_20, silver_60):
            self.assertTrue(
                all(
                    status.ready
                    for status in batch_status.statuses_by_trade_date.values()
                ),
                f"{batch_status.dataset} batch should be fully ready",
            )

        self.assertEqual(raw_10.expected_count, 10)
        self.assertLess(raw_10.elapsed_ms, RAW_10_DAY_BUDGET_MS, raw_10)
        self.assertLess(raw_60.elapsed_ms, RAW_60_DAY_BUDGET_MS, raw_60)
        self.assertEqual(silver_10.expected_count, 10)
        self.assertLess(silver_10.elapsed_ms, SILVER_10_DAY_BUDGET_MS, silver_10)
        self.assertLess(
            silver_60.elapsed_ms,
            SILVER_60_DAY_BUDGET_MS,
            silver_60,
        )

    def test_gold_qfq_batch_readiness_20_and_60_day_budget(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            trade_dates = _trade_dates(60)
            _write_gold_qfq_ready_window(connection, lake_root, trade_dates)

            gold_10 = batch_gold_stk_mins_qfq_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates[-10:],
                registered_trade_days=trade_dates,
            )
            gold_20 = batch_gold_stk_mins_qfq_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates[-20:],
                registered_trade_days=trade_dates,
            )
            gold_60 = batch_gold_stk_mins_qfq_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates,
                registered_trade_days=trade_dates,
            )

        for batch_status in (gold_10, gold_20, gold_60):
            self.assertTrue(
                all(
                    status.ready
                    for status in batch_status.statuses_by_trade_date.values()
                ),
                f"{batch_status.dataset} batch should be fully ready",
            )

        self.assertEqual(gold_10.expected_count, 10)
        self.assertLess(
            gold_10.elapsed_ms,
            GOLD_QFQ_10_DAY_BUDGET_MS,
            gold_10,
        )
        self.assertLess(
            gold_60.elapsed_ms,
            GOLD_QFQ_60_DAY_BUDGET_MS,
            gold_60,
        )


if __name__ == "__main__":
    unittest.main()
