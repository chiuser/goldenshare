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
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    STK_MINS_QFQ_DERIVED_FREQS,
    STK_MINS_QFQ_NATIVE_FREQS,
    qfq_source_freq_for_derived_freq,
)
from orchestrator.defs.stk_mins_qfq import (
    GOLD_STK_MINS_QFQ_DERIVED_WINDOWS,
    build_gold_stk_mins_qfq_derived_select_sql,
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


def _native_trade_times(freq: int) -> tuple[str, ...]:
    if freq == 30:
        return tuple(
            source_time
            for source_time, _window_id, _target_time
            in GOLD_STK_MINS_QFQ_DERIVED_WINDOWS[90]
        )
    if freq == 60:
        return tuple(
            source_time
            for source_time, _window_id, _target_time
            in GOLD_STK_MINS_QFQ_DERIVED_WINDOWS[120]
        )
    return {
        1: ("09:31:00",),
        5: ("09:35:00",),
        15: ("09:45:00",),
    }[freq]


def _write_gold_qfq_native_year_file(
    connection,
    lake_root: Path,
    *,
    freq: int,
    trade_dates: tuple[str, ...],
    ts_code: str = "000001.SZ",
) -> None:
    path = gold_stk_mins_qfq_path(lake_root, freq, ts_code, "2026")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_sql = []
    for trade_date in trade_dates:
        for index, trade_time in enumerate(_native_trade_times(freq)):
            open_value = 10.0 + index
            rows_sql.append(
                "SELECT "
                f"{duckdb_string(ts_code)} AS ts_code, "
                f"{int(freq)}::INTEGER AS freq, "
                f"CAST({duckdb_string(trade_date)} AS DATE) AS trade_date, "
                f"CAST({duckdb_string(f'{trade_date} {trade_time}')} AS TIMESTAMP) "
                "AS trade_time, "
                f"{open_value}::DOUBLE AS open, "
                f"{open_value + 1.0}::DOUBLE AS high, "
                f"{open_value - 1.0}::DOUBLE AS low, "
                f"{open_value + 0.5}::DOUBLE AS close, "
                "1000.0::DOUBLE AS vol, "
                "10000.0::DOUBLE AS amount, "
                "'SZSE'::VARCHAR AS exchange"
            )
    connection.execute(
        f"""
        COPY (
          {" UNION ALL ".join(rows_sql)}
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


def _write_gold_qfq_derived_year_file(
    connection,
    lake_root: Path,
    *,
    target_freq: int,
    trade_dates: tuple[str, ...],
    ts_code: str = "000001.SZ",
) -> None:
    source_freq = qfq_source_freq_for_derived_freq(target_freq)
    source_path = gold_stk_mins_qfq_path(lake_root, source_freq, ts_code, "2026")
    target_path = gold_stk_mins_qfq_path(lake_root, target_freq, ts_code, "2026")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    derived_sql = build_gold_stk_mins_qfq_derived_select_sql(
        source_qfq_paths=[source_path],
        target_freq=target_freq,
        partition_keys=trade_dates,
    )
    connection.execute(
        f"""
        COPY (
          {derived_sql}
        ) TO {duckdb_string(target_path)} (FORMAT PARQUET)
        """
    )


def _write_gold_qfq_ready_window(
    connection,
    lake_root: Path,
    trade_dates: tuple[str, ...],
) -> None:
    for trade_date in trade_dates:
        _write_adj_factor_files(connection, lake_root, trade_date=trade_date)
        for freq in STK_MINS_QFQ_NATIVE_FREQS:
            _write_silver_file_for_times(
                connection,
                lake_root,
                trade_date=trade_date,
                freq=freq,
                trade_times=_native_trade_times(freq),
            )
    for freq in STK_MINS_QFQ_NATIVE_FREQS:
        _write_gold_qfq_native_year_file(
            connection,
            lake_root,
            freq=freq,
            trade_dates=trade_dates,
        )
    for target_freq in STK_MINS_QFQ_DERIVED_FREQS:
        _write_gold_qfq_derived_year_file(
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
