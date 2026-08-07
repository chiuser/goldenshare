import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import duckdb

import orchestrator.defs.asset_guards.stk_mins_lake_readiness as lake_readiness_module
from orchestrator.defs.asset_guards.adj_factor_lake_readiness import (
    batch_adj_factor_lake_readiness,
)
from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    batch_gold_stk_mins_qfq_lake_readiness,
    batch_raw_stk_mins_lake_readiness,
    batch_silver_stk_mins_lake_readiness,
)
from orchestrator.defs.checks.stk_mins_checks import (
    GOLD_STK_MINS_QFQ_CONTRACT_CHECK,
    GOLD_STK_MINS_QFQ_DERIVED_SOURCE_COVERAGE_CHECK,
    RAW_STK_MINS_CONTRACT_CHECK,
    RAW_STK_MINS_KEY_INTEGRITY_CHECK,
    RAW_STK_MINS_VALUE_DOMAIN_CHECK,
    SILVER_STK_MINS_CONTRACT_CHECK,
    SILVER_STK_MINS_KEY_INTEGRITY_CHECK,
    SILVER_STK_MINS_REFERENCE_COVERAGE_CHECK,
    SILVER_STK_MINS_VALUE_DOMAIN_CHECK,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_path,
    raw_adj_factor_path,
    raw_stk_mins_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
    silver_stock_daily_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    STK_MINS_QFQ_DERIVED_FREQS,
    STK_MINS_QFQ_FREQS,
    qfq_source_freq_for_derived_freq,
)
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    cn_a_derived_minute_window_rows,
)
from orchestrator.defs.stk_mins_qfq import (
    build_gold_stk_mins_qfq_derived_select_sql,
)


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


def _write_silver_file(
    connection,
    lake_root: Path,
    *,
    trade_date: str,
    freq: int,
    ts_code: str = "000001.SZ",
    trade_time: str | None = None,
    row_count: int = 1,
    actual_freq: int | None = None,
    actual_trade_date: str | None = None,
    open_value: float = 10.0,
    vol_value: float = 100.0,
    amount_value: float = 1000.0,
    exchange: str = "SZSE",
    include_exchange: bool = True,
    duplicate_key: bool = False,
) -> None:
    path = silver_stk_mins_path(lake_root, freq, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    trade_time = trade_time or f"{trade_date} 09:31:00"
    actual_freq = actual_freq if actual_freq is not None else freq
    actual_trade_date = actual_trade_date or trade_date
    rows_sql = []
    for index in range(row_count):
        row_trade_time = trade_time
        if not duplicate_key and row_count > 1:
            row_trade_time = f"{trade_date} 09:{31 + index:02d}:00"
        columns = [
            f"{duckdb_string(ts_code)} AS ts_code",
            f"{actual_freq}::INTEGER AS freq",
            f"CAST({duckdb_string(actual_trade_date)} AS DATE) AS trade_date",
            f"CAST({duckdb_string(row_trade_time)} AS TIMESTAMP) AS trade_time",
            f"{open_value}::DOUBLE AS open",
            "10.5::DOUBLE AS high",
            "9.8::DOUBLE AS low",
            "10.2::DOUBLE AS close",
            f"{vol_value}::DOUBLE AS vol",
            f"{amount_value}::DOUBLE AS amount",
        ]
        if include_exchange:
            columns.append(f"{duckdb_string(exchange)} AS exchange")
        rows_sql.append("SELECT " + ", ".join(columns))
    connection.execute(
        f"""
        COPY (
          {" UNION ALL ".join(rows_sql)}
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


def _write_stock_daily_file(
    connection,
    lake_root: Path,
    *,
    trade_date: str,
    ts_code: str = "000001.SZ",
) -> None:
    path = silver_stock_daily_path(lake_root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT
            {duckdb_string(ts_code)} AS ts_code,
            CAST({duckdb_string(trade_date)} AS DATE) AS trade_date,
            10.0::DOUBLE AS open,
            10.5::DOUBLE AS high,
            9.8::DOUBLE AS low,
            10.2::DOUBLE AS close,
            9.9::DOUBLE AS pre_close,
            0.3::DOUBLE AS change_amount,
            3.0::DOUBLE AS pct_chg,
            1000.0::DOUBLE AS vol,
            10000.0::DOUBLE AS amount
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


def _write_suspend_file(
    connection,
    lake_root: Path,
    *,
    trade_date: str,
    ts_code: str = "000001.SZ",
    full_day_suspend: bool = False,
) -> None:
    path = silver_stock_suspend_daily_path(lake_root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    if full_day_suspend:
        select_sql = f"""
          SELECT
            {duckdb_string(ts_code)} AS ts_code,
            CAST({duckdb_string(trade_date)} AS DATE) AS trade_date,
            NULL::VARCHAR AS suspend_timing,
            'S'::VARCHAR AS suspend_type
        """
    else:
        select_sql = """
          SELECT
            NULL::VARCHAR AS ts_code,
            NULL::DATE AS trade_date,
            NULL::VARCHAR AS suspend_timing,
            NULL::VARCHAR AS suspend_type
          WHERE false
        """
    connection.execute(
        f"""
        COPY (
          {select_sql}
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


def _write_stock_lifecycle_file(
    connection,
    lake_root: Path,
    *,
    ts_code: str = "000001.SZ",
    list_status: str = "L",
    list_date: str = "2010-01-01",
    delist_date: str | None = None,
) -> None:
    path = silver_stock_lifecycle_path(lake_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT
            {duckdb_string(ts_code)} AS ts_code,
            '000001'::VARCHAR AS symbol,
            'sample'::VARCHAR AS name,
            'SZSE'::VARCHAR AS exchange,
            '主板'::VARCHAR AS market,
            'CNY'::VARCHAR AS curr_type,
            true AS is_cny_stock,
            {duckdb_string(list_status)} AS list_status,
            DATE {duckdb_string(list_date)} AS list_date,
            {f"DATE {duckdb_string(delist_date)}" if delist_date is not None else "NULL::DATE"} AS delist_date
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


def _write_adj_factor_stock_lifecycle_file(
    connection,
    lake_root: Path,
    *,
    ts_code: str = "000001.SZ",
    list_date: str = "2010-01-01",
) -> None:
    path = silver_stock_lifecycle_path(lake_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT
            {duckdb_string(ts_code)} AS ts_code,
            '000001'::VARCHAR AS symbol,
            'sample'::VARCHAR AS name,
            'SZSE'::VARCHAR AS exchange,
            '主板'::VARCHAR AS market,
            'CNY'::VARCHAR AS curr_type,
            true AS is_cny_stock,
            'L'::VARCHAR AS list_status,
            CAST({duckdb_string(list_date)} AS DATE) AS list_date,
            NULL::DATE AS delist_date
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


def _write_adj_factor_files(
    connection,
    lake_root: Path,
    *,
    trade_date: str,
    ts_code: str = "000001.SZ",
    raw_trade_date: str | None = None,
    silver_trade_date: str | None = None,
    adj_factor: float = 1.0,
) -> None:
    raw_path = raw_adj_factor_path(lake_root, trade_date)
    silver_path = silver_adj_factor_path(lake_root, trade_date)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    silver_path.parent.mkdir(parents=True, exist_ok=True)
    raw_trade_date = raw_trade_date or trade_date.replace("-", "")
    silver_trade_date = silver_trade_date or trade_date
    connection.execute(
        f"""
        COPY (
          SELECT
            {duckdb_string(ts_code)} AS ts_code,
            {duckdb_string(raw_trade_date)} AS trade_date,
            {adj_factor}::DOUBLE AS adj_factor
        ) TO {duckdb_string(raw_path)} (FORMAT PARQUET)
        """
    )
    connection.execute(
        f"""
        COPY (
          SELECT
            {duckdb_string(ts_code)} AS ts_code,
            CAST({duckdb_string(silver_trade_date)} AS DATE) AS trade_date,
            {adj_factor}::DOUBLE AS adj_factor
        ) TO {duckdb_string(silver_path)} (FORMAT PARQUET)
        """
    )


def _write_silver_file_for_times(
    connection,
    lake_root: Path,
    *,
    trade_date: str,
    freq: int,
    trade_times: tuple[str, ...],
    ts_code: str = "000001.SZ",
) -> None:
    path = silver_stk_mins_path(lake_root, freq, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_sql = []
    for index, trade_time in enumerate(trade_times):
        open_value = 10.0 + index
        rows_sql.append(
            "SELECT "
            f"{duckdb_string(ts_code)} AS ts_code, "
            f"{freq}::INTEGER AS freq, "
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


def _write_gold_qfq_file_for_times(
    connection,
    lake_root: Path,
    *,
    trade_date: str,
    freq: int,
    trade_times: tuple[str, ...],
    ts_code: str = "000001.SZ",
    open_shift: float = 0.0,
) -> None:
    path = gold_stk_mins_qfq_path(lake_root, freq, ts_code, trade_date[:4])
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_sql = []
    for index, trade_time in enumerate(trade_times):
        open_value = 10.0 + index + open_shift
        rows_sql.append(
            "SELECT "
            f"{duckdb_string(ts_code)} AS ts_code, "
            f"{freq}::INTEGER AS freq, "
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


def _write_derived_qfq_file(
    connection,
    lake_root: Path,
    *,
    trade_date: str,
    target_freq: int,
    ts_code: str = "000001.SZ",
) -> None:
    source_freq = qfq_source_freq_for_derived_freq(target_freq)
    source_path = gold_stk_mins_qfq_path(lake_root, source_freq, ts_code, trade_date[:4])
    target_path = gold_stk_mins_qfq_path(lake_root, target_freq, ts_code, trade_date[:4])
    target_path.parent.mkdir(parents=True, exist_ok=True)
    derived_sql = build_gold_stk_mins_qfq_derived_select_sql(
        source_qfq_paths=[source_path],
        target_freq=target_freq,
        partition_keys=[trade_date],
    )
    connection.execute(
        f"""
        COPY (
          {derived_sql}
        ) TO {duckdb_string(target_path)} (FORMAT PARQUET)
        """
    )


def _write_gold_qfq_ready_inputs(
    connection,
    lake_root: Path,
    *,
    trade_date: str,
) -> None:
    _write_adj_factor_files(connection, lake_root, trade_date=trade_date)
    native_times = {
        1: ("09:31:00",),
        5: ("09:35:00",),
        15: ("09:45:00",),
        30: tuple(dict.fromkeys(row[0] for row in cn_a_derived_minute_window_rows(90))),
        60: tuple(dict.fromkeys(row[0] for row in cn_a_derived_minute_window_rows(120))),
    }
    for freq, trade_times in native_times.items():
        _write_silver_file_for_times(
            connection,
            lake_root,
            trade_date=trade_date,
            freq=freq,
            trade_times=trade_times,
        )
        _write_gold_qfq_file_for_times(
            connection,
            lake_root,
            trade_date=trade_date,
            freq=freq,
            trade_times=trade_times,
        )
    for target_freq in STK_MINS_QFQ_DERIVED_FREQS:
        _write_derived_qfq_file(
            connection,
            lake_root,
            trade_date=trade_date,
            target_freq=target_freq,
        )
def _write_silver_ready_inputs(
    connection,
    lake_root: Path,
    *,
    trade_date: str,
    ts_code: str = "000001.SZ",
    full_day_suspend: bool = False,
) -> None:
    _write_stock_daily_file(
        connection,
        lake_root,
        trade_date=trade_date,
        ts_code=ts_code,
    )
    _write_suspend_file(
        connection,
        lake_root,
        trade_date=trade_date,
        ts_code=ts_code,
        full_day_suspend=full_day_suspend,
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
        self.assertIn(RAW_STK_MINS_CONTRACT_CHECK, status.failed_check_names)
        self.assertEqual(len(status.missing_file_paths), 1)

    def test_raw_batch_readiness_detects_blocking_check_failures(self) -> None:
        cases = (
            {
                "trade_date": "2026-06-15",
                "kwargs": {"include_vwap": False},
                "check": RAW_STK_MINS_CONTRACT_CHECK,
            },
            {
                "trade_date": "2026-06-16",
                "kwargs": {"actual_freq": 5},
                "check": RAW_STK_MINS_CONTRACT_CHECK,
            },
            {
                "trade_date": "2026-06-17",
                "kwargs": {"trade_time": "2026-06-18 09:31:00"},
                "check": RAW_STK_MINS_CONTRACT_CHECK,
            },
            {
                "trade_date": "2026-06-18",
                "kwargs": {"row_count": 2, "duplicate_key": True},
                "check": RAW_STK_MINS_KEY_INTEGRITY_CHECK,
            },
            {
                "trade_date": "2026-06-19",
                "kwargs": {"open_value": -1.0},
                "check": RAW_STK_MINS_VALUE_DOMAIN_CHECK,
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

    def test_adj_factor_batch_readiness_returns_ready_for_complete_window(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            trade_dates = _trade_dates(3)
            _write_adj_factor_stock_lifecycle_file(connection, lake_root)
            for trade_date in trade_dates:
                _write_adj_factor_files(connection, lake_root, trade_date=trade_date)

            batch_status = batch_adj_factor_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates,
                registered_trade_days=trade_dates,
            )

        self.assertEqual(batch_status.expected_trade_dates, trade_dates)
        self.assertEqual(batch_status.scanned_file_count, len(trade_dates) * 2)
        self.assertTrue(
            all(status.ready for status in batch_status.statuses_by_trade_date.values())
        )

    def test_adj_factor_batch_readiness_detects_blocking_failures(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            _write_adj_factor_stock_lifecycle_file(connection, lake_root)
            _write_adj_factor_files(
                connection,
                lake_root,
                trade_date="2026-06-15",
                raw_trade_date="20260616",
            )
            silver_adj_factor_path(lake_root, "2026-06-16").parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            _write_adj_factor_files(
                connection,
                lake_root,
                trade_date="2026-06-16",
                adj_factor=-1.0,
            )

            batch_status = batch_adj_factor_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=("2026-06-15", "2026-06-16"),
                registered_trade_days=("2026-06-15", "2026-06-16"),
            )

        first_status = batch_status.status_for_trade_date("2026-06-15")
        second_status = batch_status.status_for_trade_date("2026-06-16")
        self.assertFalse(first_status.ready)
        self.assertTrue(first_status.materialized)
        self.assertIn("raw_adj_factor_partition_date_matches", first_status.failed_check_names)
        self.assertFalse(second_status.ready)
        self.assertTrue(second_status.materialized)
        self.assertIn("raw_adj_factor_positive_factor", second_status.failed_check_names)

    def test_silver_batch_readiness_returns_ready_for_complete_window(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            trade_dates = _trade_dates(60)
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

            batch_status = batch_silver_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=trade_dates,
                registered_trade_days=trade_dates,
            )

        self.assertEqual(batch_status.dataset, "silver_stk_mins")
        self.assertEqual(batch_status.expected_count, 60)
        self.assertGreaterEqual(batch_status.elapsed_ms, 0)
        self.assertTrue(all(status.ready for status in batch_status.statuses_by_trade_date.values()))
        self.assertEqual(
            batch_status.status_for_trade_date(trade_dates[-1]).checked_row_count,
            len(STK_MINS_FREQS),
        )

    def test_silver_batch_readiness_marks_missing_file_as_not_materialized(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            _write_stock_lifecycle_file(connection, lake_root)
            _write_silver_ready_inputs(connection, lake_root, trade_date="2026-06-15")
            for freq in STK_MINS_FREQS[:-1]:
                _write_silver_file(connection, lake_root, trade_date="2026-06-15", freq=freq)

            batch_status = batch_silver_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=("2026-06-15",),
                registered_trade_days=("2026-06-15",),
            )

        status = batch_status.status_for_trade_date("2026-06-15")
        self.assertFalse(status.ready)
        self.assertFalse(status.materialized)
        self.assertIn(SILVER_STK_MINS_CONTRACT_CHECK, status.failed_check_names)

    def test_silver_batch_readiness_detects_blocking_check_failures(self) -> None:
        cases = (
            {
                "trade_date": "2026-06-15",
                "kwargs": {"include_exchange": False},
                "check": SILVER_STK_MINS_CONTRACT_CHECK,
            },
            {
                "trade_date": "2026-06-16",
                "kwargs": {"actual_freq": 5},
                "check": SILVER_STK_MINS_CONTRACT_CHECK,
            },
            {
                "trade_date": "2026-06-17",
                "kwargs": {"row_count": 2, "duplicate_key": True},
                "check": SILVER_STK_MINS_KEY_INTEGRITY_CHECK,
            },
            {
                "trade_date": "2026-06-18",
                "kwargs": {"open_value": -1.0},
                "check": SILVER_STK_MINS_VALUE_DOMAIN_CHECK,
            },
            {
                "trade_date": "2026-06-19",
                "kwargs": {"vol_value": 50.0},
                "check": SILVER_STK_MINS_VALUE_DOMAIN_CHECK,
            },
            {
                "trade_date": "2026-06-20",
                "kwargs": {"exchange": "SSE"},
                "check": SILVER_STK_MINS_VALUE_DOMAIN_CHECK,
            },
        )
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            _write_stock_lifecycle_file(connection, lake_root)
            for case in cases:
                _write_silver_ready_inputs(
                    connection,
                    lake_root,
                    trade_date=case["trade_date"],
                )
                for freq in STK_MINS_FREQS:
                    kwargs = case["kwargs"] if freq == 1 else {}
                    _write_silver_file(
                        connection,
                        lake_root,
                        trade_date=case["trade_date"],
                        freq=freq,
                        **kwargs,
                    )

            batch_status = batch_silver_stk_mins_lake_readiness(
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

    def test_silver_batch_readiness_checks_stock_daily_suspend_and_lifecycle(self) -> None:
        cases = (
            {
                "trade_date": "2026-06-15",
                "daily_code": "000002.SZ",
                "full_day_suspend": False,
                "ts_code": "000001.SZ",
                "check": SILVER_STK_MINS_REFERENCE_COVERAGE_CHECK,
            },
            {
                "trade_date": "2026-06-16",
                "daily_code": "000001.SZ",
                "full_day_suspend": True,
                "ts_code": "000001.SZ",
                "check": SILVER_STK_MINS_REFERENCE_COVERAGE_CHECK,
            },
            {
                "trade_date": "2026-06-17",
                "daily_code": "000003.SZ",
                "full_day_suspend": False,
                "ts_code": "000003.SZ",
                "check": SILVER_STK_MINS_REFERENCE_COVERAGE_CHECK,
            },
        )
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            _write_stock_lifecycle_file(connection, lake_root, ts_code="000001.SZ")
            for case in cases:
                _write_silver_ready_inputs(
                    connection,
                    lake_root,
                    trade_date=case["trade_date"],
                    ts_code=case["daily_code"],
                    full_day_suspend=case["full_day_suspend"],
                )
                for freq in STK_MINS_FREQS:
                    _write_silver_file(
                        connection,
                        lake_root,
                        trade_date=case["trade_date"],
                        freq=freq,
                        ts_code=case["ts_code"],
                    )

            batch_status = batch_silver_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=tuple(case["trade_date"] for case in cases),
                registered_trade_days=tuple(case["trade_date"] for case in cases),
            )

        for case in cases:
            status = batch_status.status_for_trade_date(case["trade_date"])
            self.assertFalse(status.ready)
            self.assertTrue(status.materialized)
            self.assertIn(case["check"], status.failed_check_names)

    def test_silver_batch_readiness_accepts_delisted_stock_inside_lifecycle(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            _write_stock_lifecycle_file(
                connection,
                lake_root,
                ts_code="000638.SZ",
                list_status="D",
                list_date="2010-01-01",
                delist_date="2026-04-13",
            )
            _write_silver_ready_inputs(
                connection,
                lake_root,
                trade_date="2026-04-10",
                ts_code="000638.SZ",
            )
            for freq in STK_MINS_FREQS:
                _write_silver_file(
                    connection,
                    lake_root,
                    trade_date="2026-04-10",
                    freq=freq,
                    ts_code="000638.SZ",
                    exchange="SZSE",
                )

            batch_status = batch_silver_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=("2026-04-10",),
                registered_trade_days=("2026-04-10",),
            )

        status = batch_status.status_for_trade_date("2026-04-10")
        self.assertTrue(status.ready)
        self.assertNotIn(SILVER_STK_MINS_REFERENCE_COVERAGE_CHECK, status.failed_check_names)

    def test_silver_batch_readiness_rejects_delist_effective_date_rows(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            _write_stock_lifecycle_file(
                connection,
                lake_root,
                ts_code="000638.SZ",
                list_status="D",
                list_date="2010-01-01",
                delist_date="2026-04-13",
            )
            _write_silver_ready_inputs(
                connection,
                lake_root,
                trade_date="2026-04-13",
                ts_code="000638.SZ",
            )
            for freq in STK_MINS_FREQS:
                _write_silver_file(
                    connection,
                    lake_root,
                    trade_date="2026-04-13",
                    freq=freq,
                    ts_code="000638.SZ",
                    exchange="SZSE",
                )

            batch_status = batch_silver_stk_mins_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=("2026-04-13",),
                registered_trade_days=("2026-04-13",),
            )

        status = batch_status.status_for_trade_date("2026-04-13")
        self.assertFalse(status.ready)
        self.assertIn(
            SILVER_STK_MINS_REFERENCE_COVERAGE_CHECK,
            status.failed_check_names,
        )

    def test_silver_batch_readiness_fails_closed_for_unknown_date(self) -> None:
        with duckdb.connect(":memory:") as connection:
            batch_status = batch_silver_stk_mins_lake_readiness(
                connection=connection,
                lake_root=Path("/tmp/does-not-matter"),
                expected_trade_dates=(),
                registered_trade_days=(),
            )

        status = batch_status.status_for_trade_date("2026-06-15")
        self.assertFalse(status.ready)
        self.assertIn("status_missing", status.failed_check_names[0])

    def test_gold_qfq_batch_readiness_returns_ready_for_native_and_derived(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            _write_gold_qfq_ready_inputs(
                connection,
                lake_root,
                trade_date="2026-06-15",
            )

            batch_status = batch_gold_stk_mins_qfq_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=("2026-06-15",),
                registered_trade_days=("2026-06-15",),
            )

        status = batch_status.status_for_trade_date("2026-06-15")
        self.assertEqual(batch_status.dataset, "gold_stk_mins_qfq")
        self.assertEqual(batch_status.freq_count, len(STK_MINS_QFQ_FREQS))
        self.assertTrue(status.ready)
        self.assertEqual(status.expected_file_count, len(STK_MINS_QFQ_FREQS))

    def test_gold_qfq_batch_readiness_marks_missing_file_as_not_materialized(
        self,
    ) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            _write_gold_qfq_ready_inputs(
                connection,
                lake_root,
                trade_date="2026-06-15",
            )
            gold_stk_mins_qfq_path(
                lake_root,
                120,
                "000001.SZ",
                "2026",
            ).unlink()

            batch_status = batch_gold_stk_mins_qfq_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=("2026-06-15",),
                registered_trade_days=("2026-06-15",),
            )

        status = batch_status.status_for_trade_date("2026-06-15")
        self.assertFalse(status.ready)
        self.assertFalse(status.materialized)
        self.assertIn(
            GOLD_STK_MINS_QFQ_CONTRACT_CHECK,
            status.failed_check_names,
        )

    def test_gold_qfq_batch_readiness_marks_missing_target_date_rows_as_not_materialized(
        self,
    ) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            _write_gold_qfq_ready_inputs(
                connection,
                lake_root,
                trade_date="2026-06-15",
            )
            _write_adj_factor_files(
                connection,
                lake_root,
                trade_date="2026-06-17",
            )
            native_times = {
                1: ("09:31:00",),
                5: ("09:35:00",),
                15: ("09:45:00",),
                30: tuple(dict.fromkeys(row[0] for row in cn_a_derived_minute_window_rows(90))),
                60: tuple(dict.fromkeys(row[0] for row in cn_a_derived_minute_window_rows(120))),
            }
            for freq, trade_times in native_times.items():
                _write_silver_file_for_times(
                    connection,
                    lake_root,
                    trade_date="2026-06-17",
                    freq=freq,
                    trade_times=trade_times,
                )

            batch_status = batch_gold_stk_mins_qfq_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=("2026-06-17",),
                registered_trade_days=("2026-06-17",),
            )
            single_date_status = lake_readiness_module._gold_qfq_status_for_trade_date(
                connection=connection,
                lake_root=lake_root,
                trade_date="2026-06-17",
                registered_trade_day_set={"2026-06-17"},
                full_semantics=True,
            )

        status = batch_status.status_for_trade_date("2026-06-17")
        for readiness_status in (status, single_date_status):
            self.assertFalse(readiness_status.ready)
            self.assertFalse(readiness_status.materialized)
            self.assertEqual(readiness_status.checked_row_count, 0)
            self.assertEqual(
                readiness_status.reason,
                "gold qfq rows are missing for 2026-06-17",
            )
            self.assertIn(
                GOLD_STK_MINS_QFQ_CONTRACT_CHECK,
                readiness_status.failed_check_names,
            )

    def test_gold_qfq_batch_readiness_does_not_recalculate_qfq_prices(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            _write_gold_qfq_ready_inputs(
                connection,
                lake_root,
                trade_date="2026-06-15",
            )
            _write_gold_qfq_file_for_times(
                connection,
                lake_root,
                trade_date="2026-06-15",
                freq=1,
                trade_times=("09:31:00",),
                open_shift=5.0,
            )

            batch_status = batch_gold_stk_mins_qfq_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=("2026-06-15",),
                registered_trade_days=("2026-06-15",),
            )

        status = batch_status.status_for_trade_date("2026-06-15")
        self.assertTrue(status.ready)
        self.assertTrue(status.materialized)
        self.assertNotIn(
            "gold_stk_mins_qfq_formula_matches_silver_adj_factor",
            status.failed_check_names,
        )

    def test_gold_qfq_batch_readiness_rejects_invalid_derived_source_day(
        self,
    ) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            trade_date = "2026-06-15"
            _write_gold_qfq_ready_inputs(
                connection,
                lake_root,
                trade_date=trade_date,
            )
            source_times = tuple(
                dict.fromkeys(row[0] for row in cn_a_derived_minute_window_rows(120))
            )
            _write_gold_qfq_file_for_times(
                connection,
                lake_root,
                trade_date=trade_date,
                freq=60,
                trade_times=(*source_times, "09:31:00"),
            )

            batch_status = batch_gold_stk_mins_qfq_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=(trade_date,),
                registered_trade_days=(trade_date,),
            )

        status = batch_status.status_for_trade_date(trade_date)
        self.assertFalse(status.ready)
        self.assertTrue(status.materialized)
        self.assertIn(
            GOLD_STK_MINS_QFQ_DERIVED_SOURCE_COVERAGE_CHECK,
            status.failed_check_names,
        )

    def test_gold_qfq_batch_readiness_does_not_call_single_date_helpers(self) -> None:
        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            lake_root = Path(directory)
            _write_gold_qfq_ready_inputs(
                connection,
                lake_root,
                trade_date="2026-06-15",
            )

            with (
                patch.object(
                    lake_readiness_module,
                    "_gold_qfq_status_for_trade_date",
                    side_effect=AssertionError("batch must not call per-date status"),
                ),
                patch.object(
                    lake_readiness_module,
                    "_gold_qfq_native_counts_for_trade_date",
                    side_effect=AssertionError("batch must not call per-date native counts"),
                ),
                patch.object(
                    lake_readiness_module,
                    "_gold_qfq_derived_counts_for_trade_date",
                    side_effect=AssertionError("batch must not call per-date derived counts"),
                ),
            ):
                batch_status = batch_gold_stk_mins_qfq_lake_readiness(
                    connection=connection,
                    lake_root=lake_root,
                    expected_trade_dates=("2026-06-15",),
                    registered_trade_days=("2026-06-15",),
                )

        self.assertTrue(batch_status.status_for_trade_date("2026-06-15").ready)


if __name__ == "__main__":
    unittest.main()
