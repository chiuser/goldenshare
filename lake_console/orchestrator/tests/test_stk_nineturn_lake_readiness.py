import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.asset_guards.stk_nineturn_lake_readiness import (
    batch_raw_stk_nineturn_lake_readiness,
    batch_silver_stock_nineturn_daily_lake_readiness,
)
from orchestrator.defs.paths import (
    raw_stk_nineturn_path,
    silver_stock_identity_map_path,
    silver_stock_nineturn_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.stk_nineturn_contract import (
    RAW_STK_NINETURN_COLUMNS,
    RAW_STK_NINETURN_COLUMN_TYPES,
    SILVER_STOCK_NINETURN_DAILY_COLUMNS,
    SILVER_STOCK_NINETURN_DAILY_COLUMN_TYPES,
)


TRADE_DATES = ("2026-07-07", "2026-07-08", "2026-07-09")
TS_CODE = "600030.SH"


def _raw_row(trade_date: str, **overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": TS_CODE,
        "trade_date": trade_date,
        "freq": "daily",
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "vol": 100.0,
        "amount": 1000.0,
        "up_count": 0.0,
        "down_count": 3.0,
        "nine_up_turn": None,
        "nine_down_turn": None,
    }
    row.update(overrides)
    return row


def _silver_row(trade_date: str, **overrides) -> dict[str, object]:
    row = _raw_row(trade_date, **overrides)
    row["up_count"] = int(row["up_count"])
    row["down_count"] = int(row["down_count"])
    return row


def _write_rows(
    path: Path,
    *,
    columns: tuple[str, ...],
    column_types: dict[str, str],
    rows: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        definitions = ", ".join(
            f'"{column}" {column_types[column]}' for column in columns
        )
        connection.execute(f"CREATE TEMP TABLE rows_to_write ({definitions})")
        placeholders = ", ".join("?" for _column in columns)
        if rows:
            connection.executemany(
                f"INSERT INTO rows_to_write VALUES ({placeholders})",
                [[row.get(column) for column in columns] for row in rows],
            )
        connection.execute(
            f"""
            COPY (
              SELECT {', '.join(f'"{column}"' for column in columns)}
              FROM rows_to_write
              ORDER BY ts_code
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _write_raw(root: Path, trade_date: str, **overrides) -> None:
    _write_rows(
        raw_stk_nineturn_path(root, trade_date),
        columns=RAW_STK_NINETURN_COLUMNS,
        column_types=RAW_STK_NINETURN_COLUMN_TYPES,
        rows=[_raw_row(trade_date, **overrides)],
    )


def _write_silver(root: Path, trade_date: str, **overrides) -> None:
    _write_rows(
        silver_stock_nineturn_daily_path(root, trade_date),
        columns=SILVER_STOCK_NINETURN_DAILY_COLUMNS,
        column_types=SILVER_STOCK_NINETURN_DAILY_COLUMN_TYPES,
        rows=[_silver_row(trade_date, **overrides)],
    )


def _write_identity(root: Path, *, valid_to: str | None = None) -> None:
    path = silver_stock_identity_map_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            """
            CREATE TEMP TABLE identity_rows (
              latest_ts_code VARCHAR,
              source_ts_code VARCHAR,
              valid_from DATE,
              valid_to DATE
            )
            """
        )
        connection.execute(
            "INSERT INTO identity_rows VALUES (?, ?, ?, ?)",
            [TS_CODE, TS_CODE, "1990-01-01", valid_to],
        )
        connection.execute(
            f"COPY identity_rows TO '{path.as_posix()}' (FORMAT PARQUET)"
        )


class StkNineturnLakeReadinessTests(unittest.TestCase):
    def test_raw_batch_distinguishes_missing_bad_and_ready_files(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_raw(root, TRADE_DATES[0])
            _write_raw(root, TRADE_DATES[1], high=8.0)
            with DuckDBResource().connect() as connection:
                readiness = batch_raw_stk_nineturn_lake_readiness(
                    connection=connection,
                    lake_root=root,
                    expected_trade_dates=TRADE_DATES,
                    registered_trade_days=set(TRADE_DATES),
                    full_semantics=True,
                )

            ready = readiness.status_for_trade_date(TRADE_DATES[0])
            bad = readiness.status_for_trade_date(TRADE_DATES[1])
            missing = readiness.status_for_trade_date(TRADE_DATES[2])
            self.assertTrue(ready.ready)
            self.assertTrue(bad.materialized)
            self.assertFalse(bad.checks_passed)
            self.assertFalse(missing.materialized)
            self.assertEqual(missing.reason, "raw_stk_nineturn_file_missing")

    def test_raw_existing_empty_file_is_materialized_check_problem(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_rows(
                raw_stk_nineturn_path(root, TRADE_DATES[0]),
                columns=RAW_STK_NINETURN_COLUMNS,
                column_types=RAW_STK_NINETURN_COLUMN_TYPES,
                rows=[],
            )
            with DuckDBResource().connect() as connection:
                readiness = batch_raw_stk_nineturn_lake_readiness(
                    connection=connection,
                    lake_root=root,
                    expected_trade_dates=(TRADE_DATES[0],),
                    registered_trade_days={TRADE_DATES[0]},
                )

            status = readiness.status_for_trade_date(TRADE_DATES[0])
            self.assertTrue(status.materialized)
            self.assertFalse(status.checks_passed)

    def test_silver_missing_file_is_actionable_only_when_mapping_is_ready(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_raw(root, TRADE_DATES[0])
            _write_identity(root)
            with DuckDBResource().connect() as connection:
                readiness = batch_silver_stock_nineturn_daily_lake_readiness(
                    connection=connection,
                    lake_root=root,
                    expected_trade_dates=(TRADE_DATES[0],),
                    registered_trade_days={TRADE_DATES[0]},
                )

            status = readiness.status_for_trade_date(TRADE_DATES[0])
            self.assertFalse(status.materialized)
            self.assertEqual(
                status.reason,
                "silver_stock_nineturn_daily_file_missing",
            )

    def test_silver_missing_file_is_blocked_by_expired_identity_mapping(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_raw(root, TRADE_DATES[0])
            _write_identity(root, valid_to=TRADE_DATES[0])
            with DuckDBResource().connect() as connection:
                readiness = batch_silver_stock_nineturn_daily_lake_readiness(
                    connection=connection,
                    lake_root=root,
                    expected_trade_dates=(TRADE_DATES[0],),
                    registered_trade_days={TRADE_DATES[0]},
                )

            status = readiness.status_for_trade_date(TRADE_DATES[0])
            self.assertFalse(status.materialized)
            self.assertEqual(status.reason, "identity_mapping_not_ready")

    def test_silver_existing_tampered_file_is_materialized_check_problem(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_raw(root, TRADE_DATES[0])
            _write_silver(root, TRADE_DATES[0], down_count=4)
            _write_identity(root)
            with DuckDBResource().connect() as connection:
                readiness = batch_silver_stock_nineturn_daily_lake_readiness(
                    connection=connection,
                    lake_root=root,
                    expected_trade_dates=(TRADE_DATES[0],),
                    registered_trade_days={TRADE_DATES[0]},
                )

            status = readiness.status_for_trade_date(TRADE_DATES[0])
            self.assertTrue(status.materialized)
            self.assertFalse(status.checks_passed)
            self.assertIn(
                "silver_stock_nineturn_daily_canonical_integrity_check",
                status.failed_check_names,
            )

    def test_batch_capacity_for_sixty_dates_stays_under_hard_budget(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            trade_dates = tuple(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat()
                for index in range(60)
            )
            _write_identity(root)
            for trade_date in trade_dates:
                _write_raw(root, trade_date)
                _write_silver(root, trade_date)

            started = time.perf_counter()
            with DuckDBResource().connect() as connection:
                raw_readiness = batch_raw_stk_nineturn_lake_readiness(
                    connection=connection,
                    lake_root=root,
                    expected_trade_dates=trade_dates,
                    registered_trade_days=set(trade_dates),
                )
                silver_readiness = batch_silver_stock_nineturn_daily_lake_readiness(
                    connection=connection,
                    lake_root=root,
                    expected_trade_dates=trade_dates,
                    registered_trade_days=set(trade_dates),
                )
            elapsed_seconds = time.perf_counter() - started

            self.assertTrue(
                all(
                    raw_readiness.status_for_trade_date(trade_date).ready
                    for trade_date in trade_dates
                )
            )
            self.assertTrue(
                all(
                    silver_readiness.status_for_trade_date(trade_date).ready
                    for trade_date in trade_dates
                )
            )
            self.assertLess(elapsed_seconds, 5.0)


if __name__ == "__main__":
    unittest.main()
