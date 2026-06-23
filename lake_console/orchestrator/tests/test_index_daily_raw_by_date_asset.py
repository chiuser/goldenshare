import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.assets.index_daily import (
    INDEX_DAILY_RAW_COLUMNS,
    _write_raw_index_daily_rows_from_prod_db_source,
)
from orchestrator.defs.paths import raw_index_daily_path, raw_index_daily_staging_path
from orchestrator.defs.resources import DuckDBResource


class IndexDailyRawByDateAssetTests(unittest.TestCase):
    def test_raw_index_daily_path_contract(self) -> None:
        root = Path("/lake")

        self.assertEqual(
            raw_index_daily_path(root, "2026-06-22"),
            Path("/lake/raw/index_daily/trade_date=2026-06-22/part-000.parquet"),
        )
        self.assertEqual(
            raw_index_daily_staging_path(root, "run-1", "2026-06-22"),
            Path(
                "/lake/raw/index_daily/_staging/run_id=run-1/"
                "trade_date=2026-06-22/part-000.parquet"
            ),
        )

    def test_write_raw_index_daily_replaces_target_after_contract_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source_path = root / "source.parquet"
            self._write_source_parquet(
                source_path,
                [
                    ("000001.SH", "20260622", 1.0, 2.0, 0.5, 1.5, None, None, 1.2, 10.0, 20.0),
                    ("399001.SZ", "20260622", None, 3.0, 1.0, 2.5, 2.0, 0.5, 2.0, 30.0, 40.0),
                ],
            )
            target_path = raw_index_daily_path(root, "2026-06-22")
            target_path.parent.mkdir(parents=True)
            target_path.write_text("stale", encoding="utf-8")

            result = _write_raw_index_daily_rows_from_prod_db_source(
                duckdb=DuckDBResource(),
                source_sql=self._source_sql(source_path),
                target_path=target_path,
                staging_path=raw_index_daily_staging_path(root, "run-1", "2026-06-22"),
                index_codes=("000001.SH", "399001.SZ"),
                partition_key="2026-06-22",
                load_postgres_extension=False,
            )

            self.assertEqual(result.row_count, 2)
            self.assertEqual(result.source_row_count, 2)
            self.assertEqual(result.expected_code_count, 2)
            self.assertEqual(result.returned_code_count, 2)
            self.assertEqual(result.missing_code_count, 0)
            self.assertEqual(result.extra_code_count, 0)
            self.assertEqual(result.observed_columns, INDEX_DAILY_RAW_COLUMNS)
            self.assertTrue(target_path.exists())
            self.assertFalse(raw_index_daily_staging_path(root, "run-1", "2026-06-22").exists())
            with duckdb.connect(database=":memory:") as connection:
                row_count = connection.execute(
                    f"SELECT count(*) FROM read_parquet('{target_path.as_posix()}')"
                ).fetchone()[0]
            self.assertEqual(row_count, 2)

    def test_write_raw_index_daily_fails_closed_for_missing_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source_path = root / "source.parquet"
            self._write_source_parquet(
                source_path,
                [("000001.SH", "20260622", 1.0, 2.0, 0.5, 1.5, 1.0, 0.5, 1.2, 10.0, 20.0)],
            )
            target_path = raw_index_daily_path(root, "2026-06-22")

            with self.assertRaisesRegex(RuntimeError, "missing_code_count=1"):
                _write_raw_index_daily_rows_from_prod_db_source(
                    duckdb=DuckDBResource(),
                    source_sql=self._source_sql(source_path),
                    target_path=target_path,
                    staging_path=raw_index_daily_staging_path(root, "run-2", "2026-06-22"),
                    index_codes=("000001.SH", "399001.SZ"),
                    partition_key="2026-06-22",
                    load_postgres_extension=False,
                )
            self.assertFalse(target_path.exists())

    def test_write_raw_index_daily_fails_closed_for_duplicate_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source_path = root / "source.parquet"
            self._write_source_parquet(
                source_path,
                [
                    ("000001.SH", "20260622", 1.0, 2.0, 0.5, 1.5, 1.0, 0.5, 1.2, 10.0, 20.0),
                    ("000001.SH", "20260622", 1.1, 2.1, 0.6, 1.6, 1.0, 0.6, 1.3, 11.0, 21.0),
                ],
            )

            with self.assertRaisesRegex(RuntimeError, "duplicate"):
                _write_raw_index_daily_rows_from_prod_db_source(
                    duckdb=DuckDBResource(),
                    source_sql=self._source_sql(source_path),
                    target_path=raw_index_daily_path(root, "2026-06-22"),
                    staging_path=raw_index_daily_staging_path(root, "run-3", "2026-06-22"),
                    index_codes=("000001.SH",),
                    partition_key="2026-06-22",
                    load_postgres_extension=False,
                )

    def test_write_raw_index_daily_fails_closed_for_date_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source_path = root / "source.parquet"
            self._write_source_parquet(
                source_path,
                [("000001.SH", "20260621", 1.0, 2.0, 0.5, 1.5, 1.0, 0.5, 1.2, 10.0, 20.0)],
            )

            with self.assertRaisesRegex(RuntimeError, "outside the requested code/date"):
                _write_raw_index_daily_rows_from_prod_db_source(
                    duckdb=DuckDBResource(),
                    source_sql=self._source_sql(source_path),
                    target_path=raw_index_daily_path(root, "2026-06-22"),
                    staging_path=raw_index_daily_staging_path(root, "run-4", "2026-06-22"),
                    index_codes=("000001.SH",),
                    partition_key="2026-06-22",
                    load_postgres_extension=False,
                )

    @staticmethod
    def _write_source_parquet(path: Path, rows: list[tuple[object, ...]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        values_sql = ", ".join(
            "("
            + ", ".join(
                IndexDailyRawByDateAssetTests._sql_literal(value) for value in row
            )
            + ")"
            for row in rows
        )
        with duckdb.connect(database=":memory:") as connection:
            connection.execute(
                f"""
                COPY (
                  SELECT *
                  FROM (
                    VALUES {values_sql}
                  ) AS rows(
                    ts_code, trade_date, open, high, low, close, pre_close,
                    change, pct_chg, vol, amount
                  )
                ) TO '{path.as_posix()}' (FORMAT PARQUET)
                """
            )

    @staticmethod
    def _source_sql(path: Path) -> str:
        return f"""
        SELECT {", ".join(INDEX_DAILY_RAW_COLUMNS)}
        FROM read_parquet('{path.as_posix()}', hive_partitioning=false)
        """

    @staticmethod
    def _sql_literal(value: object) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, str):
            return "'" + value.replace("'", "''") + "'"
        return str(value)
