import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.assets.stock_daily import (
    STOCK_DAILY_RAW_COLUMN_TYPES,
)
from orchestrator.defs.duckdb_sql import (
    STOCK_DAILY_RAW_REQUIRED_COLUMNS,
    copy_query_to_parquet,
    read_parquet,
)
from orchestrator.defs.paths import (
    raw_stock_daily_path,
    silver_stock_basic_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, TushareResult
from orchestrator.defs.sensors.stock_daily_raw_repair import (
    MAX_STOCK_DAILY_REPAIR_ATTEMPTS,
    StockDailyMissingCodeLocatorResult,
    locate_stock_daily_missing_codes,
    select_stock_daily_missing_code_repair,
)
from orchestrator.defs.tushare_api_io import (
    fetch_tushare_stock_daily_missing_codes_to_raw,
)


PARTITION_KEY = "2026-05-29"
COMPACT_TRADE_DATE = "20260529"


class _FakeTushare:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, object], tuple[str, ...]]] = []

    def call(
        self,
        api_name: str,
        params: dict[str, object],
        fields: tuple[str, ...],
    ) -> TushareResult:
        self.calls.append((api_name, dict(params), tuple(fields)))
        return TushareResult(
            rows=[dict(row) for row in self.rows],
            columns=tuple(fields),
            metadata={},
        )


def _write_rows(
    path: Path,
    *,
    column_types: dict[str, str],
    rows: list[dict[str, object]],
    order_by: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column_types)
    with DuckDBResource().connect() as connection:
        column_defs = ", ".join(
            f'"{column}" {column_types[column]}' for column in columns
        )
        connection.execute(f"CREATE TEMP TABLE rows_to_write ({column_defs})")
        if rows:
            placeholders = ", ".join("?" for _column in columns)
            values = [[row.get(column) for column in columns] for row in rows]
            connection.executemany(
                f"INSERT INTO rows_to_write VALUES ({placeholders})",
                values,
            )
        select_columns = ", ".join(
            f'CAST("{column}" AS {column_types[column]}) AS "{column}"'
            for column in columns
        )
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT {select_columns}
                FROM rows_to_write
                ORDER BY {order_by}
                """,
                path,
            )
        )


def _raw_row(ts_code: str, *, close: float = 10.5) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": COMPACT_TRADE_DATE,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": close,
        "pre_close": 10.0,
        "change": close - 10.0,
        "pct_chg": (close - 10.0) * 10,
        "vol": 100.0,
        "amount": close * 100.0,
    }


def _write_raw(lake_root: Path, rows: list[dict[str, object]]) -> Path:
    path = raw_stock_daily_path(lake_root, PARTITION_KEY)
    _write_rows(
        path,
        column_types=dict(STOCK_DAILY_RAW_COLUMN_TYPES),
        rows=rows,
        order_by="ts_code, trade_date",
    )
    return path


def _write_basic(lake_root: Path, codes: list[str]) -> None:
    _write_rows(
        silver_stock_basic_path(lake_root),
        column_types={
            "ts_code": "VARCHAR",
            "list_status": "VARCHAR",
            "list_date": "DATE",
        },
        rows=[
            {"ts_code": code, "list_status": "L", "list_date": "2020-01-01"}
            for code in codes
        ],
        order_by="ts_code",
    )


def _write_suspend(lake_root: Path, rows: list[dict[str, object]] | None = None) -> None:
    _write_rows(
        silver_stock_suspend_daily_path(lake_root, PARTITION_KEY),
        column_types={
            "ts_code": "VARCHAR",
            "trade_date": "DATE",
            "suspend_type": "VARCHAR",
            "suspend_timing": "VARCHAR",
        },
        rows=rows or [],
        order_by="ts_code",
    )


def _raw_codes(path: Path) -> list[str]:
    with DuckDBResource().connect() as connection:
        rows = connection.execute(
            f"SELECT ts_code FROM {read_parquet(path)} ORDER BY ts_code"
        ).fetchall()
    return [row[0] for row in rows]


class StockDailyRawRepairTests(unittest.TestCase):
    def test_locator_returns_missing_codes_with_single_duckdb_scan(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_basic(lake_root, ["000001.SZ", "000002.SZ", "000003.SZ"])
            _write_suspend(lake_root)
            _write_raw(lake_root, [_raw_row("000001.SZ"), _raw_row("000003.SZ")])

            locator = locate_stock_daily_missing_codes(
                lake_root_path=lake_root,
                duckdb=DuckDBResource(),
                trade_date=PARTITION_KEY,
            )

        self.assertTrue(locator.raw_file_exists)
        self.assertEqual(locator.expected_count, 3)
        self.assertEqual(locator.raw_code_count, 2)
        self.assertEqual(locator.missing_codes, ("000002.SZ",))
        self.assertEqual(locator.extra_count, 0)
        self.assertEqual(locator.duplicate_key_count, 0)
        self.assertEqual(locator.conflict_key_count, 0)

    def test_locator_raw_file_missing_does_not_enter_repair(self) -> None:
        with TemporaryDirectory() as directory:
            locator = locate_stock_daily_missing_codes(
                lake_root_path=Path(directory),
                duckdb=DuckDBResource(),
                trade_date=PARTITION_KEY,
            )

        self.assertFalse(locator.raw_file_exists)
        selection = select_stock_daily_missing_code_repair(
            locator=locator,
            evaluated_at=datetime.now(UTC),
            repair_state={"dates": {PARTITION_KEY: {"attempt_count": 1}}},
        )
        self.assertFalse(selection.should_submit)
        self.assertEqual(selection.reason, "raw_file_missing_full_day_required")

    def test_selector_manual_for_large_or_dirty_missing_sets(self) -> None:
        evaluated_at = datetime.now(UTC)
        large_locator = StockDailyMissingCodeLocatorResult(
            trade_date=PARTITION_KEY,
            raw_file_exists=True,
            missing_codes=tuple(f"{index:06d}.SZ" for index in range(101)),
        )
        extra_locator = StockDailyMissingCodeLocatorResult(
            trade_date=PARTITION_KEY,
            raw_file_exists=True,
            missing_codes=("000002.SZ",),
            extra_count=1,
        )
        duplicate_locator = StockDailyMissingCodeLocatorResult(
            trade_date=PARTITION_KEY,
            raw_file_exists=True,
            missing_codes=("000002.SZ",),
            duplicate_key_count=1,
        )

        for locator, reason in (
            (large_locator, "missing_count_exceeds_limit"),
            (extra_locator, "extra_codes_present"),
            (duplicate_locator, "duplicate_keys_present"),
        ):
            with self.subTest(reason=reason):
                selection = select_stock_daily_missing_code_repair(
                    locator=locator,
                    evaluated_at=evaluated_at,
                    repair_state={"dates": {}},
                )
                self.assertFalse(selection.should_submit)
                self.assertTrue(selection.manual_required)
                self.assertEqual(selection.reason, reason)

    def test_selector_waits_and_exhausts_same_missing_hash(self) -> None:
        evaluated_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
        locator = StockDailyMissingCodeLocatorResult(
            trade_date=PARTITION_KEY,
            raw_file_exists=True,
            missing_codes=("000002.SZ",),
        )
        first = select_stock_daily_missing_code_repair(
            locator=locator,
            evaluated_at=evaluated_at,
            repair_state={"dates": {}},
        )
        self.assertTrue(first.should_submit)
        self.assertEqual(first.repair_attempt, 1)

        waiting = select_stock_daily_missing_code_repair(
            locator=locator,
            evaluated_at=evaluated_at + timedelta(minutes=1),
            repair_state=first.repair_state,
        )
        self.assertFalse(waiting.should_submit)
        self.assertTrue(waiting.waiting)

        exhausted_state = {
            "dates": {
                PARTITION_KEY: {
                    "missing_codes_hash": first.missing_codes_hash,
                    "attempt_count": MAX_STOCK_DAILY_REPAIR_ATTEMPTS,
                    "next_retry_at": None,
                }
            }
        }
        exhausted = select_stock_daily_missing_code_repair(
            locator=locator,
            evaluated_at=evaluated_at + timedelta(hours=10),
            repair_state=exhausted_state,
        )
        self.assertFalse(exhausted.should_submit)
        self.assertTrue(exhausted.exhausted)
        self.assertTrue(exhausted.manual_required)

    def test_repair_fetch_calls_tushare_once_and_merges_partial_rows(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            target_path = _write_raw(lake_root, [_raw_row("000001.SZ")])
            tushare = _FakeTushare([_raw_row("000002.SZ")])

            metadata = fetch_tushare_stock_daily_missing_codes_to_raw(
                tushare=tushare,
                duckdb=DuckDBResource(),
                ts_codes=["000002.SZ", "000003.SZ"],
                fields=STOCK_DAILY_RAW_REQUIRED_COLUMNS,
                column_types=STOCK_DAILY_RAW_COLUMN_TYPES,
                target_path=target_path,
                partition_key=PARTITION_KEY,
                missing_codes_hash="a" * 64,
                repair_attempt=1,
            )

            self.assertEqual(_raw_codes(target_path), ["000001.SZ", "000002.SZ"])

        self.assertEqual(len(tushare.calls), 1)
        api_name, params, fields = tushare.calls[0]
        self.assertEqual(api_name, "daily")
        self.assertEqual(params["ts_code"], "000002.SZ,000003.SZ")
        self.assertEqual(params["trade_date"], COMPACT_TRADE_DATE)
        self.assertEqual(fields, STOCK_DAILY_RAW_REQUIRED_COLUMNS)
        self.assertEqual(metadata["goldenshare/fetched_row_count"], 1)
        self.assertEqual(metadata["goldenshare/fetched_code_count"], 1)

    def test_repair_fetch_zero_rows_fails_without_overwriting_target(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            target_path = _write_raw(lake_root, [_raw_row("000001.SZ")])
            tushare = _FakeTushare([])

            with self.assertRaisesRegex(RuntimeError, "returned 0 rows"):
                fetch_tushare_stock_daily_missing_codes_to_raw(
                    tushare=tushare,
                    duckdb=DuckDBResource(),
                    ts_codes=["000002.SZ"],
                    fields=STOCK_DAILY_RAW_REQUIRED_COLUMNS,
                    column_types=STOCK_DAILY_RAW_COLUMN_TYPES,
                    target_path=target_path,
                    partition_key=PARTITION_KEY,
                    missing_codes_hash="a" * 64,
                    repair_attempt=1,
                )

            self.assertEqual(_raw_codes(target_path), ["000001.SZ"])

    def test_repair_fetch_wrong_code_or_date_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            target_path = _write_raw(lake_root, [_raw_row("000001.SZ")])
            wrong_row = _raw_row("000999.SZ")
            tushare = _FakeTushare([wrong_row])

            with self.assertRaisesRegex(RuntimeError, "outside the requested"):
                fetch_tushare_stock_daily_missing_codes_to_raw(
                    tushare=tushare,
                    duckdb=DuckDBResource(),
                    ts_codes=["000002.SZ"],
                    fields=STOCK_DAILY_RAW_REQUIRED_COLUMNS,
                    column_types=STOCK_DAILY_RAW_COLUMN_TYPES,
                    target_path=target_path,
                    partition_key=PARTITION_KEY,
                    missing_codes_hash="a" * 64,
                    repair_attempt=1,
                )

            self.assertEqual(_raw_codes(target_path), ["000001.SZ"])


if __name__ == "__main__":
    unittest.main()
