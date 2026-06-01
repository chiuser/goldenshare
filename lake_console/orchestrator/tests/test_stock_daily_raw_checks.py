import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.checks import stock_daily_checks
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.paths import (
    raw_stock_daily_path,
    silver_stock_daily_path,
    silver_stock_basic_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors import readiness


PARTITION_KEY = "2026-05-29"


def _write_rows(
    path: Path,
    *,
    column_types: dict[str, str],
    rows: list[dict[str, object]],
    order_by: str = "1",
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


def _basic_row(
    ts_code: str,
    *,
    list_status: str = "L",
    list_date: str = "2020-01-01",
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "list_status": list_status,
        "list_date": list_date,
    }


def _raw_row(
    ts_code: str,
    *,
    trade_date: str = "20260529",
) -> dict[str, object]:
    return {"ts_code": ts_code, "trade_date": trade_date}


def _silver_row(
    ts_code: str,
    *,
    trade_date: str = PARTITION_KEY,
) -> dict[str, object]:
    return {"ts_code": ts_code, "trade_date": trade_date}


def _suspend_row(
    ts_code: str,
    *,
    suspend_type: str = "S",
    suspend_timing: str | None = None,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": PARTITION_KEY,
        "suspend_type": suspend_type,
        "suspend_timing": suspend_timing,
    }


def _write_raw(lake_root: Path, rows: list[dict[str, object]]) -> Path:
    path = raw_stock_daily_path(lake_root, PARTITION_KEY)
    _write_rows(
        path,
        column_types={"ts_code": "VARCHAR", "trade_date": "VARCHAR"},
        rows=rows,
        order_by="ts_code, trade_date",
    )
    return path


def _write_silver(lake_root: Path, rows: list[dict[str, object]]) -> Path:
    path = silver_stock_daily_path(lake_root, PARTITION_KEY)
    _write_rows(
        path,
        column_types={"ts_code": "VARCHAR", "trade_date": "DATE"},
        rows=rows,
        order_by="ts_code, trade_date",
    )
    return path


def _write_basic(lake_root: Path, rows: list[dict[str, object]]) -> Path:
    path = silver_stock_basic_path(lake_root)
    _write_rows(
        path,
        column_types={
            "ts_code": "VARCHAR",
            "list_status": "VARCHAR",
            "list_date": "DATE",
        },
        rows=rows,
        order_by="ts_code",
    )
    return path


def _write_suspend(lake_root: Path, rows: list[dict[str, object]]) -> Path:
    path = silver_stock_suspend_daily_path(lake_root, PARTITION_KEY)
    _write_rows(
        path,
        column_types={
            "ts_code": "VARCHAR",
            "trade_date": "DATE",
            "suspend_type": "VARCHAR",
            "suspend_timing": "VARCHAR",
        },
        rows=rows,
        order_by="ts_code",
    )
    return path


def _raw_universe_metadata(
    lake_root: Path,
    *,
    basic_rows: list[dict[str, object]],
    suspend_rows: list[dict[str, object]],
    raw_rows: list[dict[str, object]],
) -> dict[str, object]:
    raw_path = _write_raw(lake_root, raw_rows)
    basic_path = _write_basic(lake_root, basic_rows)
    suspend_path = _write_suspend(lake_root, suspend_rows)
    with DuckDBResource().connect() as connection:
        return stock_daily_checks._expected_tradable_universe_metadata(
            connection,
            partition_key=PARTITION_KEY,
            daily_path=raw_path,
            basic_path=basic_path,
            suspend_path=suspend_path,
            daily_code_set_sql=stock_daily_checks._raw_daily_code_set_sql(
                raw_path, PARTITION_KEY
            ),
        )


def _silver_universe_metadata(
    lake_root: Path,
    *,
    basic_rows: list[dict[str, object]],
    suspend_rows: list[dict[str, object]],
    silver_rows: list[dict[str, object]],
) -> dict[str, object]:
    silver_path = _write_silver(lake_root, silver_rows)
    basic_path = _write_basic(lake_root, basic_rows)
    suspend_path = _write_suspend(lake_root, suspend_rows)
    with DuckDBResource().connect() as connection:
        return stock_daily_checks._expected_tradable_universe_metadata(
            connection,
            partition_key=PARTITION_KEY,
            daily_path=silver_path,
            basic_path=basic_path,
            suspend_path=suspend_path,
            daily_code_set_sql=stock_daily_checks._silver_daily_code_set_sql(
                silver_path, PARTITION_KEY
            ),
        )


class StockDailyRawCheckTests(unittest.TestCase):
    def test_silver_coverage_check_is_blocking_readiness_gate(self) -> None:
        self.assertIn(
            "silver_stock_daily_covers_expected_tradable_universe",
            readiness.SILVER_STOCK_DAILY_BLOCKING_CHECKS,
        )
        self.assertNotIn(
            "silver_stock_daily_row_count_matches_expected_tradable_count",
            readiness.SILVER_STOCK_DAILY_BLOCKING_CHECKS,
        )

    def test_raw_universe_complete_excludes_full_day_suspend(self) -> None:
        with TemporaryDirectory() as directory:
            metadata = _raw_universe_metadata(
                Path(directory),
                basic_rows=[
                    _basic_row("000001.SZ"),
                    _basic_row("000002.SZ"),
                    _basic_row("000003.SZ"),
                ],
                suspend_rows=[_suspend_row("000003.SZ")],
                raw_rows=[_raw_row("000001.SZ"), _raw_row("000002.SZ")],
            )

        self.assertEqual(metadata["listed_count"], 3)
        self.assertEqual(metadata["full_day_suspend_count"], 1)
        self.assertEqual(metadata["expected_count"], 2)
        self.assertEqual(metadata["daily_count"], 2)
        self.assertEqual(metadata["unexplained_missing_count"], 0)
        self.assertEqual(metadata["unexplained_extra_count"], 0)

    def test_raw_universe_reports_missing_expected_code(self) -> None:
        with TemporaryDirectory() as directory:
            metadata = _raw_universe_metadata(
                Path(directory),
                basic_rows=[_basic_row("000001.SZ"), _basic_row("000002.SZ")],
                suspend_rows=[],
                raw_rows=[_raw_row("000001.SZ")],
            )

        self.assertEqual(metadata["expected_count"], 2)
        self.assertEqual(metadata["daily_count"], 1)
        self.assertEqual(metadata["unexplained_missing_count"], 1)
        self.assertEqual(metadata["missing_sample_ts_codes"], ["000002.SZ"])

    def test_raw_universe_reports_unexpected_extra_code(self) -> None:
        with TemporaryDirectory() as directory:
            metadata = _raw_universe_metadata(
                Path(directory),
                basic_rows=[_basic_row("000001.SZ")],
                suspend_rows=[],
                raw_rows=[_raw_row("000001.SZ"), _raw_row("000999.SZ")],
            )

        self.assertEqual(metadata["expected_count"], 1)
        self.assertEqual(metadata["daily_count"], 2)
        self.assertEqual(metadata["unexplained_extra_count"], 1)
        self.assertEqual(metadata["extra_sample_ts_codes"], ["000999.SZ"])

    def test_intraday_suspend_does_not_explain_missing_raw_daily(self) -> None:
        with TemporaryDirectory() as directory:
            metadata = _raw_universe_metadata(
                Path(directory),
                basic_rows=[_basic_row("000001.SZ"), _basic_row("000002.SZ")],
                suspend_rows=[_suspend_row("000002.SZ", suspend_timing="10:00-15:00")],
                raw_rows=[_raw_row("000001.SZ")],
            )

        self.assertEqual(metadata["intraday_suspend_count"], 1)
        self.assertEqual(metadata["unexplained_missing_count"], 1)
        self.assertEqual(metadata["missing_sample_ts_codes"], ["000002.SZ"])

    def test_raw_duplicate_key_metadata_reports_duplicate_ts_code_trade_date(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            raw_path = _write_raw(
                Path(directory),
                [_raw_row("000001.SZ"), _raw_row("000001.SZ")],
            )
            with DuckDBResource().connect() as connection:
                metadata = stock_daily_checks._raw_duplicate_key_metadata(
                    connection,
                    raw_path=raw_path,
                )

        self.assertEqual(metadata["duplicate_key_count"], 1)
        self.assertEqual(metadata["duplicate_extra_row_count"], 1)
        self.assertEqual(
            metadata["duplicate_sample_rows"],
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260529",
                    "duplicate_row_count": 2,
                }
            ],
        )

    def test_silver_universe_complete_excludes_full_day_suspend(self) -> None:
        with TemporaryDirectory() as directory:
            metadata = _silver_universe_metadata(
                Path(directory),
                basic_rows=[
                    _basic_row("000001.SZ"),
                    _basic_row("000002.SZ"),
                    _basic_row("000003.SZ"),
                ],
                suspend_rows=[_suspend_row("000003.SZ")],
                silver_rows=[_silver_row("000001.SZ"), _silver_row("000002.SZ")],
            )

        self.assertEqual(metadata["listed_count"], 3)
        self.assertEqual(metadata["full_day_suspend_count"], 1)
        self.assertEqual(metadata["expected_count"], 2)
        self.assertEqual(metadata["daily_count"], 2)
        self.assertEqual(metadata["unexplained_missing_count"], 0)
        self.assertEqual(metadata["unexplained_extra_count"], 0)

    def test_silver_universe_reports_missing_expected_code(self) -> None:
        with TemporaryDirectory() as directory:
            metadata = _silver_universe_metadata(
                Path(directory),
                basic_rows=[_basic_row("000001.SZ"), _basic_row("000002.SZ")],
                suspend_rows=[],
                silver_rows=[_silver_row("000001.SZ")],
            )

        self.assertEqual(metadata["expected_count"], 2)
        self.assertEqual(metadata["daily_count"], 1)
        self.assertEqual(metadata["unexplained_missing_count"], 1)
        self.assertEqual(metadata["missing_sample_ts_codes"], ["000002.SZ"])

    def test_silver_universe_reports_unexpected_extra_code(self) -> None:
        with TemporaryDirectory() as directory:
            metadata = _silver_universe_metadata(
                Path(directory),
                basic_rows=[_basic_row("000001.SZ")],
                suspend_rows=[],
                silver_rows=[_silver_row("000001.SZ"), _silver_row("000999.SZ")],
            )

        self.assertEqual(metadata["expected_count"], 1)
        self.assertEqual(metadata["daily_count"], 2)
        self.assertEqual(metadata["unexplained_extra_count"], 1)
        self.assertEqual(metadata["extra_sample_ts_codes"], ["000999.SZ"])

    def test_silver_full_day_suspend_explains_missing_daily(self) -> None:
        with TemporaryDirectory() as directory:
            metadata = _silver_universe_metadata(
                Path(directory),
                basic_rows=[_basic_row("000001.SZ"), _basic_row("000002.SZ")],
                suspend_rows=[_suspend_row("000002.SZ")],
                silver_rows=[_silver_row("000001.SZ")],
            )

        self.assertEqual(metadata["full_day_suspend_count"], 1)
        self.assertEqual(metadata["expected_count"], 1)
        self.assertEqual(metadata["unexplained_missing_count"], 0)

    def test_silver_intraday_suspend_does_not_explain_missing_daily(self) -> None:
        with TemporaryDirectory() as directory:
            metadata = _silver_universe_metadata(
                Path(directory),
                basic_rows=[_basic_row("000001.SZ"), _basic_row("000002.SZ")],
                suspend_rows=[_suspend_row("000002.SZ", suspend_timing="10:00-15:00")],
                silver_rows=[_silver_row("000001.SZ")],
            )

        self.assertEqual(metadata["intraday_suspend_count"], 1)
        self.assertEqual(metadata["unexplained_missing_count"], 1)
        self.assertEqual(metadata["missing_sample_ts_codes"], ["000002.SZ"])


if __name__ == "__main__":
    unittest.main()
