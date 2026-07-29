from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from orchestrator.defs.assets import index_mins_silver
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import raw_index_mins_path, silver_index_mins_path
from orchestrator.defs.resources import DuckDBResource


PARTITION_KEY = "2026-07-27"
CODE = "000001.SH"


def _row(
    freq: str,
    trade_time: str,
    value: float,
    *,
    exchange: str | None = "XSHG",
    vwap: float | None = None,
) -> tuple[object, ...]:
    return (
        f" {CODE.lower()} ",
        f" {freq} ",
        f" {PARTITION_KEY} {trade_time}",
        value,
        value + 0.5,
        value + 1.0,
        value - 0.5,
        value * 10,
        value * 100,
        exchange,
        vwap,
    )


def _write_raw(
    root: Path,
    freq: str,
    times: tuple[str, ...],
    *,
    exchange: str | None = "XSHG",
    exchanges: tuple[str | None, ...] | None = None,
) -> Path:
    path = raw_index_mins_path(root, freq, PARTITION_KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            """
            CREATE TABLE source_rows (
              ts_code VARCHAR,
              freq VARCHAR,
              trade_time TIMESTAMP,
              open DOUBLE,
              close DOUBLE,
              high DOUBLE,
              low DOUBLE,
              vol DOUBLE,
              amount DOUBLE,
              exchange VARCHAR,
              vwap DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO source_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                _row(
                    freq,
                    time_value,
                    float(index + 1),
                    exchange=exchanges[index] if exchanges is not None else exchange,
                    vwap=float(index) + 0.25,
                )
                for index, time_value in enumerate(times)
            ],
        )
        connection.execute(
            copy_query_to_parquet(
                "SELECT ts_code, freq, trade_time, open, close, high, low, "
                "vol, amount, exchange, vwap FROM source_rows",
                path,
            )
        )
    return path


def _read_rows(path: Path) -> list[tuple[object, ...]]:
    with DuckDBResource().connect() as connection:
        return connection.execute(
            f"SELECT * FROM {read_parquet(path, hive_partitioning=False)} "
            "ORDER BY trade_time"
        ).fetchall()


class IndexMinsSilverWriterTests(unittest.TestCase):
    def test_native_silver_normalizes_fields_and_preserves_vwap(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_raw(root, "1min", ("09:30:00",))

            result = index_mins_silver.write_silver_index_mins_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                freq=1,
                partition_key=PARTITION_KEY,
            )

            self.assertEqual(result.silver_freq, "1min")
            self.assertEqual(result.source_row_count, 1)
            self.assertEqual(result.written_row_count, 1)
            self.assertEqual(result.write_mode, "staged_atomic_replace")
            row = _read_rows(result.silver_file_path)[0]
            self.assertEqual(row[0:2], (CODE, "1min"))
            self.assertEqual(row[2].strftime("%H:%M:%S"), "09:30:00")
            self.assertEqual(row[9], "XSHG")
            self.assertEqual(row[10], 0.25)
            self.assertEqual(list(result.silver_file_path.parent.glob("*.tmp")), [])

    def test_derived_90m_uses_fixed_windows_and_null_vwap(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_raw(
                root,
                "30min",
                (
                    "09:30:00",
                    "10:00:00",
                    "10:30:00",
                    "11:00:00",
                    "11:30:00",
                    "13:30:00",
                    "14:00:00",
                    "14:30:00",
                    "15:00:00",
                ),
            )
            index_mins_silver.write_silver_index_mins_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                freq=30,
                partition_key=PARTITION_KEY,
            )

            result = index_mins_silver.write_silver_index_mins_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                freq=90,
                partition_key=PARTITION_KEY,
            )

            self.assertEqual(result.source_row_count, 9)
            self.assertEqual(result.expected_window_count, 3)
            self.assertEqual(result.generated_window_count, 3)
            self.assertEqual(result.incomplete_window_count, 0)
            rows = _read_rows(result.silver_file_path)
            self.assertEqual([row[2].strftime("%H:%M:%S") for row in rows], [
                "11:00:00",
                "14:00:00",
                "15:00:00",
            ])
            self.assertEqual(rows[0][0:2], (CODE, "90min"))
            self.assertEqual(rows[0][2].date().isoformat(), PARTITION_KEY)
            self.assertEqual(rows[0][3:9], (2.0, 4.5, 5.0, 1.5, 90.0, 900.0))
            self.assertIsNone(rows[0][10])

    def test_derived_120m_uses_fixed_windows_and_ignores_non_window_bar(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_raw(
                root,
                "60min",
                ("09:30:00", "10:30:00", "11:30:00", "14:00:00", "15:00:00"),
            )
            index_mins_silver.write_silver_index_mins_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                freq=60,
                partition_key=PARTITION_KEY,
            )

            result = index_mins_silver.write_silver_index_mins_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                freq=120,
                partition_key=PARTITION_KEY,
            )

            self.assertEqual(result.expected_window_count, 2)
            self.assertEqual(result.generated_window_count, 2)
            self.assertEqual(result.written_row_count, 2)
            rows = _read_rows(result.silver_file_path)
            self.assertEqual([row[2].strftime("%H:%M:%S") for row in rows], [
                "10:30:00",
                "14:00:00",
            ])
            self.assertTrue(all(row[1] == "120min" and row[10] is None for row in rows))

    def test_incomplete_derived_window_fails_without_target_or_staging(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_raw(
                root,
                "30min",
                (
                    "10:00:00",
                    "10:30:00",
                    "11:00:00",
                    "11:30:00",
                    "13:30:00",
                    "14:30:00",
                    "15:00:00",
                ),
            )
            index_mins_silver.write_silver_index_mins_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                freq=30,
                partition_key=PARTITION_KEY,
            )

            with self.assertRaisesRegex(
                index_mins_silver.IndexMinsSilverValidationError,
                "derived window is incomplete",
            ):
                index_mins_silver.write_silver_index_mins_partition(
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    freq=90,
                    partition_key=PARTITION_KEY,
                )

            target = silver_index_mins_path(root, 90, PARTITION_KEY)
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_mixed_exchange_in_one_derived_window_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_raw(
                root,
                "60min",
                ("09:30:00", "10:30:00", "11:30:00", "14:00:00"),
                exchanges=("XSHG", "XSHG", "XSHG", "XSHE"),
            )
            index_mins_silver.write_silver_index_mins_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                freq=60,
                partition_key=PARTITION_KEY,
            )

            with self.assertRaisesRegex(
                index_mins_silver.IndexMinsSilverValidationError,
                "mixed exchange",
            ):
                index_mins_silver.write_silver_index_mins_partition(
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    freq=120,
                    partition_key=PARTITION_KEY,
                )

            target = silver_index_mins_path(root, 120, PARTITION_KEY)
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_invalid_existing_native_target_is_not_overwritten(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_raw(root, "1min", ("09:30:00",))
            target = silver_index_mins_path(root, 1, PARTITION_KEY)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"invalid parquet")
            original = target.read_bytes()

            with self.assertRaises(index_mins_silver.IndexMinsSilverValidationError):
                index_mins_silver.write_silver_index_mins_partition(
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    freq=1,
                    partition_key=PARTITION_KEY,
                )

            self.assertEqual(target.read_bytes(), original)

    def test_writer_module_has_no_active_dagster_definitions(self) -> None:
        source = Path(index_mins_silver.__file__).read_text()
        self.assertNotIn("@dg.asset", source)
        self.assertNotIn("@dg.sensor", source)
