from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from orchestrator.defs.assets import index_mins
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import raw_index_mins_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.index_mins import index_mins_code_set_hash


PARTITION_KEY = "2026-07-27"
SOURCE_FREQ = "1min"
CODE_A = "000001.SZ"
CODE_B = "000300.SH"
CODE_EXTRA = "399001.SZ"


class _FakeProdPostgres:
    def duckdb_connection_string(self) -> str:
        return "host=fake"


class _FailingProdPostgres:
    def duckdb_connection_string(self) -> str:
        raise AssertionError("existing valid partition must not open Prod DB")


def _rows(*, codes: tuple[str, ...] = (CODE_A, CODE_B), duplicate: bool = False):
    values = [
        (CODE_A, SOURCE_FREQ, "2026-07-27 09:30:00", 10.0, 10.2, 10.3, 9.9, 100.0, 1000.0, "XSHE", 10.1),
        (CODE_B, SOURCE_FREQ, "2026-07-27 09:30:00", 20.0, 20.2, 20.3, 19.9, 200.0, 4000.0, "XSHG", 20.1),
    ]
    values = [row for row in values if row[0] in codes]
    if duplicate:
        values.append(values[0])
    return values


def _write_source(path: Path, rows, *, extra_column: bool = False) -> None:
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
            rows,
        )
        columns = ", ".join(index_mins.INDEX_MINS_RAW_COLUMNS)
        if extra_column:
            connection.execute("ALTER TABLE source_rows ADD COLUMN unexpected VARCHAR")
            columns = "*, unexpected"
        connection.execute(copy_query_to_parquet(f"SELECT {columns} FROM source_rows", path))


def _patch_source(path: Path):
    path_sql = str(path).replace("'", "''")
    source_sql = (
        "SELECT ts_code, freq, trade_time, open, close, high, low, vol, amount, "
        f"exchange, vwap FROM read_parquet('{path_sql}', hive_partitioning=false)"
    )
    return patch.object(index_mins, "_load_duckdb_postgres_extension", lambda _connection: None), patch.object(
        index_mins,
        "_attach_prod_postgres_database",
        lambda _connection, *, postgres_connection_string: None,
    ), patch.object(index_mins, "build_prod_index_mins_duckdb_source_sql", lambda **_kwargs: source_sql)


def _write_partition(lake_root: Path, source_path: Path, *, codes=(CODE_A, CODE_B)):
    patches = _patch_source(source_path)
    with patches[0], patches[1], patches[2]:
        return index_mins.write_raw_index_mins_partition_from_prod_db(
            lake_root=lake_root,
            duckdb=DuckDBResource(),
            prod_postgres=_FakeProdPostgres(),
            source_freq=SOURCE_FREQ,
            partition_key=PARTITION_KEY,
            active_pool=codes,
        )


class IndexMinsRawWriterTests(unittest.TestCase):
    def test_path_and_set_based_source_contract(self) -> None:
        with TemporaryDirectory() as directory:
            path = raw_index_mins_path(Path(directory), SOURCE_FREQ, PARTITION_KEY)
            self.assertTrue(path.as_posix().endswith(
                "raw/tushare/index_mins/freq=1min/trade_date=2026-07-27/part-000.parquet"
            ))
        source = Path(index_mins.__file__).read_text()
        self.assertNotIn("executemany", source)
        self.assertNotIn("SELECT * FROM index_mins_source", source)

    def test_success_writes_staging_then_reads_back_and_promotes(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            source_path = lake_root / "source.parquet"
            _write_source(source_path, _rows())

            result = _write_partition(lake_root, source_path)

            self.assertEqual(result.write_mode, "staged_atomic_replace")
            self.assertEqual(result.source_row_count, 2)
            self.assertEqual(result.written_row_count, 2)
            self.assertEqual(result.returned_code_count, 2)
            self.assertEqual(result.missing_code_count, 0)
            self.assertEqual(result.extra_code_count, 0)
            self.assertEqual(result.duplicate_key_count, 0)
            self.assertEqual(result.active_pool_hash, index_mins_code_set_hash((CODE_A, CODE_B)))
            self.assertTrue(result.raw_file_path.exists())
            self.assertEqual(list(result.raw_file_path.parent.glob("*.tmp")), [])

            with DuckDBResource().connect() as connection:
                rows = connection.execute(
                    f"SELECT ts_code, freq FROM {read_parquet(result.raw_file_path)} ORDER BY ts_code"
                ).fetchall()
            self.assertEqual(rows, [(CODE_A, SOURCE_FREQ), (CODE_B, SOURCE_FREQ)])

    def test_missing_active_code_fails_without_creating_target(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            source_path = lake_root / "source.parquet"
            _write_source(source_path, _rows(codes=(CODE_A,)))

            with self.assertRaisesRegex(index_mins.IndexMinsRawValidationError, "missing_active_codes"):
                _write_partition(lake_root, source_path)

            target = raw_index_mins_path(lake_root, SOURCE_FREQ, PARTITION_KEY)
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_extra_code_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            source_path = lake_root / "source.parquet"
            extra = _rows() + [
                (CODE_EXTRA, SOURCE_FREQ, "2026-07-27 09:30:00", 1.0, 1.1, 1.2, 0.9, 1.0, 1.0, "XSHE", 1.05)
            ]
            _write_source(source_path, extra)

            with self.assertRaisesRegex(index_mins.IndexMinsRawValidationError, "extra_codes"):
                _write_partition(lake_root, source_path)

            self.assertFalse(raw_index_mins_path(lake_root, SOURCE_FREQ, PARTITION_KEY).exists())

    def test_duplicate_primary_key_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            source_path = lake_root / "source.parquet"
            _write_source(source_path, _rows(duplicate=True))

            with self.assertRaisesRegex(index_mins.IndexMinsRawValidationError, "duplicate_primary_key"):
                _write_partition(lake_root, source_path)

            self.assertFalse(raw_index_mins_path(lake_root, SOURCE_FREQ, PARTITION_KEY).exists())

    def test_out_of_scope_row_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            source_path = lake_root / "source.parquet"
            bad_rows = [
                (CODE_A, "5min", "2026-07-28 09:30:00", 10.0, 10.2, 10.3, 9.9, 100.0, 1000.0, "XSHE", 10.1),
                (CODE_B, SOURCE_FREQ, "2026-07-27 09:30:00", 20.0, 20.2, 20.3, 19.9, 200.0, 4000.0, "XSHG", 20.1),
            ]
            _write_source(source_path, bad_rows)

            with self.assertRaisesRegex(index_mins.IndexMinsRawValidationError, "out_of_scope_rows"):
                _write_partition(lake_root, source_path)

    def test_existing_valid_partition_is_reused_without_prod_connection(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            source_path = lake_root / "source.parquet"
            _write_source(source_path, _rows())
            initial = _write_partition(lake_root, source_path)

            result = index_mins.write_raw_index_mins_partition_from_prod_db(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                prod_postgres=_FailingProdPostgres(),
                source_freq=SOURCE_FREQ,
                partition_key=PARTITION_KEY,
                active_pool=(CODE_A, CODE_B),
            )

            self.assertEqual(result.write_mode, "reuse_existing")
            self.assertEqual(result.raw_file_path, initial.raw_file_path)
            self.assertEqual(result.query_count, 0)

    def test_existing_invalid_partition_is_not_overwritten(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            target = raw_index_mins_path(lake_root, SOURCE_FREQ, PARTITION_KEY)
            target.parent.mkdir(parents=True)
            source_path = lake_root / "bad_target_source.parquet"
            _write_source(source_path, _rows(codes=(CODE_A,)))
            target.write_bytes(source_path.read_bytes())

            with self.assertRaisesRegex(index_mins.IndexMinsRawValidationError, "Existing index_mins"):
                index_mins.write_raw_index_mins_partition_from_prod_db(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    prod_postgres=_FailingProdPostgres(),
                    source_freq=SOURCE_FREQ,
                    partition_key=PARTITION_KEY,
                    active_pool=(CODE_A, CODE_B),
                )

            self.assertEqual(target.read_bytes(), source_path.read_bytes())

    def test_staging_readback_failure_cleans_staging_and_keeps_target_absent(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            source_path = lake_root / "source.parquet"
            _write_source(source_path, _rows())
            patches = _patch_source(source_path)
            with patches[0], patches[1], patches[2], patch.object(
                index_mins, "_raw_output_sql", lambda: "SELECT * FROM index_mins_source WHERE false"
            ):
                with self.assertRaisesRegex(index_mins.IndexMinsRawValidationError, "empty_source"):
                    index_mins.write_raw_index_mins_partition_from_prod_db(
                        lake_root=lake_root,
                        duckdb=DuckDBResource(),
                        prod_postgres=_FakeProdPostgres(),
                        source_freq=SOURCE_FREQ,
                        partition_key=PARTITION_KEY,
                        active_pool=(CODE_A, CODE_B),
                    )

            target = raw_index_mins_path(lake_root, SOURCE_FREQ, PARTITION_KEY)
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
