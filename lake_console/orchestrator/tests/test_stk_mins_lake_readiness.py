import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    batch_raw_stk_mins_lake_readiness,
)
from orchestrator.defs.checks.stk_mins_checks import (
    RAW_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
    RAW_STK_MINS_FREQ_MATCHES_ASSET_CHECK,
    RAW_STK_MINS_PARTITION_DATE_MATCHES_CHECK,
    RAW_STK_MINS_PRICE_VOLUME_SANITY_CHECK,
    RAW_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK,
    RAW_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import raw_stk_mins_path
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS


def _trade_dates(count: int, *, start: date = date(2026, 4, 1)) -> tuple[str, ...]:
    return tuple((start + timedelta(days=offset)).isoformat() for offset in range(count))


def _write_raw_file(
    connection,
    lake_root: Path,
    *,
    trade_date: str,
    freq: int,
    ts_code: str = "000001.SZ",
    trade_time: str | None = None,
    row_count: int = 1,
    actual_freq: int | None = None,
    open_value: float = 10.0,
    include_vwap: bool = True,
    duplicate_key: bool = False,
) -> None:
    path = raw_stk_mins_path(lake_root, freq, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    trade_time = trade_time or f"{trade_date} 09:31:00"
    actual_freq = actual_freq if actual_freq is not None else freq
    rows_sql = []
    for index in range(row_count):
        row_trade_time = trade_time
        if not duplicate_key and row_count > 1:
            row_trade_time = f"{trade_date} 09:{31 + index:02d}:00"
        columns = [
            f"{duckdb_string(ts_code)} AS ts_code",
            f"{actual_freq}::INTEGER AS freq",
            f"CAST({duckdb_string(row_trade_time)} AS TIMESTAMP) AS trade_time",
            f"{open_value}::DOUBLE AS open",
            "10.2::DOUBLE AS close",
            "10.5::DOUBLE AS high",
            "9.8::DOUBLE AS low",
            "100::BIGINT AS vol",
            "1000.0::DOUBLE AS amount",
            "'SZSE'::VARCHAR AS exchange",
        ]
        if include_vwap:
            columns.append("10.0::DOUBLE AS vwap")
        rows_sql.append("SELECT " + ", ".join(columns))
    connection.execute(
        f"""
        COPY (
          {" UNION ALL ".join(rows_sql)}
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


class StkMinsLakeReadinessTests(unittest.TestCase):
    def test_raw_batch_readiness_returns_ready_for_complete_window(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            trade_dates = _trade_dates(60)
            for trade_date in trade_dates:
                for freq in STK_MINS_FREQS:
                    _write_raw_file(
                        connection,
                        lake_root,
                        trade_date=trade_date,
                        freq=freq,
                    )

            batch_status = batch_raw_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates,
                registered_trade_days=trade_dates,
            )

        self.assertEqual(batch_status.expected_count, 60)
        self.assertEqual(batch_status.freq_count, len(STK_MINS_FREQS))
        self.assertGreaterEqual(batch_status.elapsed_ms, 0)
        self.assertTrue(all(status.ready for status in batch_status.statuses_by_trade_date.values()))
        self.assertEqual(
            batch_status.status_for_trade_date(trade_dates[-1]).checked_row_count,
            len(STK_MINS_FREQS),
        )

    def test_raw_batch_readiness_marks_missing_file_as_not_materialized(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            for freq in STK_MINS_FREQS[:-1]:
                _write_raw_file(connection, lake_root, trade_date="2026-06-15", freq=freq)

            batch_status = batch_raw_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=("2026-06-15",),
                registered_trade_days=("2026-06-15",),
            )

        status = batch_status.status_for_trade_date("2026-06-15")
        self.assertFalse(status.ready)
        self.assertFalse(status.materialized)
        self.assertIn(RAW_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK, status.failed_check_names)
        self.assertEqual(len(status.missing_file_paths), 1)

    def test_raw_batch_readiness_detects_blocking_check_failures(self) -> None:
        cases = (
            {
                "trade_date": "2026-06-15",
                "kwargs": {"include_vwap": False},
                "check": RAW_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK,
            },
            {
                "trade_date": "2026-06-16",
                "kwargs": {"actual_freq": 5},
                "check": RAW_STK_MINS_FREQ_MATCHES_ASSET_CHECK,
            },
            {
                "trade_date": "2026-06-17",
                "kwargs": {"trade_time": "2026-06-18 09:31:00"},
                "check": RAW_STK_MINS_PARTITION_DATE_MATCHES_CHECK,
            },
            {
                "trade_date": "2026-06-18",
                "kwargs": {"row_count": 2, "duplicate_key": True},
                "check": RAW_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
            },
            {
                "trade_date": "2026-06-19",
                "kwargs": {"open_value": -1.0},
                "check": RAW_STK_MINS_PRICE_VOLUME_SANITY_CHECK,
            },
        )
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            for case in cases:
                for freq in STK_MINS_FREQS:
                    kwargs = case["kwargs"] if freq == 1 else {}
                    _write_raw_file(
                        connection,
                        lake_root,
                        trade_date=case["trade_date"],
                        freq=freq,
                        **kwargs,
                    )

            batch_status = batch_raw_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=tuple(case["trade_date"] for case in cases),
                registered_trade_days=tuple(case["trade_date"] for case in cases),
            )

        for case in cases:
            status = batch_status.status_for_trade_date(case["trade_date"])
            self.assertFalse(status.ready)
            self.assertTrue(status.materialized)
            self.assertFalse(status.checks_passed)
            self.assertIn(case["check"], status.failed_check_names)

    def test_raw_batch_readiness_fails_closed_for_unregistered_or_unknown_date(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            for freq in STK_MINS_FREQS:
                _write_raw_file(connection, lake_root, trade_date="2026-06-15", freq=freq)

            batch_status = batch_raw_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=("2026-06-15",),
                registered_trade_days=(),
            )

        unregistered_status = batch_status.status_for_trade_date("2026-06-15")
        self.assertFalse(unregistered_status.ready)
        self.assertFalse(unregistered_status.materialized)

        unknown_status = batch_status.status_for_trade_date("2026-06-16")
        self.assertFalse(unknown_status.ready)
        self.assertIn("status_missing", unknown_status.failed_check_names[0])


if __name__ == "__main__":
    unittest.main()
