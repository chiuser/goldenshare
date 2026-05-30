import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.bootstrap.specs.stk_mins import (
    STK_MINS_BOOTSTRAP_DATASET_KEYS,
    all_stk_mins_bootstrap_specs,
    bootstrap_stk_mins_partition_to_raw,
    resolve_stk_mins_backup_partition_path,
    stk_mins_bootstrap_spec,
)
from orchestrator.defs.bootstrap.specs.stock_identity_map import (
    bootstrap_stock_identity_map_to_silver,
    stock_identity_map_bootstrap_spec,
)
from orchestrator.defs.duckdb_sql import (
    SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS,
    STK_MINS_RAW_REQUIRED_COLUMNS,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.metadata import (
    DAGSTER_ROW_COUNT_METADATA_KEY,
    DAGSTER_URI_METADATA_KEY,
    OBSERVED_COLUMNS_METADATA_KEY,
)


PARTITION_KEY = "2026-05-07"


def _backup_stk_mins_path(backup_root: Path, freq: int, file_name: str) -> Path:
    return backup_root / f"freq={freq}" / f"trade_date={PARTITION_KEY}" / file_name


def _write_backup_stk_mins_file(
    path: Path,
    *,
    freq: int = 30,
    include_rows: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    where_clause = "" if include_rows else "WHERE false"
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                '000001.SZ'::VARCHAR AS ts_code,
                {freq}::BIGINT AS freq,
                TIMESTAMP '2026-05-07 09:30:00' AS trade_time,
                1.0::DOUBLE AS open,
                1.1::DOUBLE AS close,
                1.2::DOUBLE AS high,
                0.9::DOUBLE AS low,
                100::BIGINT AS vol,
                1234.5::DOUBLE AS amount,
                NULL AS exchange,
                1.05::DOUBLE AS vwap
              {where_clause}
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


def _write_stock_identity_map_file(path: Path, *, include_rows: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    where_clause = "" if include_rows else "WHERE false"
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                '001872.SZ'::VARCHAR AS latest_ts_code,
                '000022.SZ'::VARCHAR AS source_ts_code,
                DATE '1993-04-30' AS valid_from,
                NULL::DATE AS valid_to,
                DATE '1993-04-30' AS effective_list_date,
                NULL::DATE AS effective_delist_date,
                'namechange'::VARCHAR AS identity_source,
                'inferred'::VARCHAR AS confidence,
                '代码变更映射'::VARCHAR AS reason,
                TIMESTAMPTZ '2026-05-12 10:00:00+08' AS created_at
              {where_clause}
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


def _read_columns(path: Path) -> tuple[tuple[str, str], ...]:
    with duckdb.connect(database=":memory:") as connection:
        rows = connection.execute(
            f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        ).fetchall()
    return tuple((row[0], row[1]) for row in rows)


class StkMinsBootstrapSpecTests(unittest.TestCase):
    def test_stk_mins_bootstrap_specs_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "data_lake"
            backup_root = Path(temp_dir) / "backup"
            specs = all_stk_mins_bootstrap_specs(
                lake_root=lake_root,
                backup_root=backup_root,
            )

        self.assertEqual(
            tuple(spec.dataset_key for spec in specs),
            tuple(STK_MINS_BOOTSTRAP_DATASET_KEYS[freq] for freq in (1, 5, 15, 30, 60)),
        )
        for spec, freq in zip(specs, (1, 5, 15, 30, 60), strict=True):
            self.assertEqual(spec.layer, "raw")
            self.assertEqual(spec.partition_type, "trade_date")
            self.assertEqual(spec.empty_policy, "require_positive")
            self.assertEqual(spec.business_key, ("ts_code", "trade_time"))
            self.assertEqual(spec.source_fields, STK_MINS_RAW_REQUIRED_COLUMNS)
            self.assertEqual(spec.target_raw_fields, STK_MINS_RAW_REQUIRED_COLUMNS)
            self.assertEqual(
                spec.old_lake_path_pattern,
                str(backup_root / f"freq={freq}" / "trade_date={partition_key}" / "*.parquet"),
            )
            self.assertEqual(
                spec.target_path_pattern,
                str(
                    lake_root
                    / "raw"
                    / "tushare"
                    / "stk_mins"
                    / f"freq={freq}"
                    / "trade_date={partition_key}"
                    / "part-000.parquet"
                ),
            )

    def test_stk_mins_bootstrap_rejects_invalid_frequency(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported stk_mins freq"):
            stk_mins_bootstrap_spec(2)

    def test_stk_mins_source_resolver_accepts_single_part_00000_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_root = Path(temp_dir) / "backup"
            source_path = _backup_stk_mins_path(backup_root, 30, "part-00000.parquet")
            _write_backup_stk_mins_file(source_path)
            spec = stk_mins_bootstrap_spec(
                30,
                lake_root=Path(temp_dir) / "data_lake",
                backup_root=backup_root,
            )

            resolved_path = resolve_stk_mins_backup_partition_path(spec, PARTITION_KEY)

        self.assertEqual(resolved_path, source_path)

    def test_stk_mins_source_resolver_requires_exactly_one_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_root = Path(temp_dir) / "backup"
            spec = stk_mins_bootstrap_spec(
                30,
                lake_root=Path(temp_dir) / "data_lake",
                backup_root=backup_root,
            )

            with self.assertRaisesRegex(FileNotFoundError, "No stk_mins backup parquet"):
                resolve_stk_mins_backup_partition_path(spec, PARTITION_KEY)

            _write_backup_stk_mins_file(
                _backup_stk_mins_path(backup_root, 30, "part-000.parquet")
            )
            _write_backup_stk_mins_file(
                _backup_stk_mins_path(backup_root, 30, "part-00000.parquet")
            )
            with self.assertRaisesRegex(ValueError, "Expected exactly one"):
                resolve_stk_mins_backup_partition_path(spec, PARTITION_KEY)

    def test_stk_mins_bootstrap_writes_new_lake_part_000_file(self) -> None:
        target_path, metadata = self._bootstrap_stk_mins_sample("part-00000.parquet")

        self.assertEqual(target_path.name, "part-000.parquet")
        self.assertEqual(_read_columns(target_path), self._expected_stk_mins_columns())
        self.assertEqual(metadata[DAGSTER_ROW_COUNT_METADATA_KEY], 1)
        self.assertEqual(
            metadata[OBSERVED_COLUMNS_METADATA_KEY],
            list(STK_MINS_RAW_REQUIRED_COLUMNS),
        )
        self.assertEqual(metadata["goldenshare/bootstrap_spec"], "raw_stk_mins_30m")
        self.assertEqual(metadata["goldenshare/partition_key"], PARTITION_KEY)
        self.assertTrue(metadata[DAGSTER_URI_METADATA_KEY].endswith("part-000.parquet"))

        with duckdb.connect(database=":memory:") as connection:
            rows = connection.execute(
                f"""
                SELECT ts_code, freq, exchange, typeof(exchange)
                FROM {read_parquet(target_path, hive_partitioning=False)}
                """
            ).fetchall()
        self.assertEqual(rows, [("000001.SZ", 30, None, "VARCHAR")])

    def test_stk_mins_bootstrap_accepts_part_000_source_file(self) -> None:
        target_path, _metadata = self._bootstrap_stk_mins_sample("part-000.parquet")

        self.assertTrue(target_path.exists())
        self.assertEqual(target_path.name, "part-000.parquet")

    def test_stk_mins_bootstrap_rejects_existing_target_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "data_lake"
            backup_root = Path(temp_dir) / "backup"
            spec = stk_mins_bootstrap_spec(30, lake_root=lake_root, backup_root=backup_root)
            _write_backup_stk_mins_file(
                _backup_stk_mins_path(backup_root, 30, "part-000.parquet")
            )
            target_path = spec.target_path(PARTITION_KEY)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"existing")

            with self.assertRaisesRegex(FileExistsError, "already exists"):
                bootstrap_stk_mins_partition_to_raw(
                    spec,
                    PARTITION_KEY,
                    DuckDBResource(),
                )

            self.assertEqual(target_path.read_bytes(), b"existing")

    def test_stk_mins_bootstrap_rejects_empty_required_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "data_lake"
            backup_root = Path(temp_dir) / "backup"
            spec = stk_mins_bootstrap_spec(30, lake_root=lake_root, backup_root=backup_root)
            _write_backup_stk_mins_file(
                _backup_stk_mins_path(backup_root, 30, "part-000.parquet"),
                include_rows=False,
            )

            with self.assertRaisesRegex(ValueError, "Bootstrap produced no rows"):
                bootstrap_stk_mins_partition_to_raw(
                    spec,
                    PARTITION_KEY,
                    DuckDBResource(),
                )

            self.assertFalse(spec.target_path(PARTITION_KEY).exists())

    def _bootstrap_stk_mins_sample(self, source_file_name: str) -> tuple[Path, dict[str, object]]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        lake_root = root / "data_lake"
        backup_root = root / "backup"
        spec = stk_mins_bootstrap_spec(30, lake_root=lake_root, backup_root=backup_root)
        _write_backup_stk_mins_file(
            _backup_stk_mins_path(backup_root, 30, source_file_name)
        )

        metadata = bootstrap_stk_mins_partition_to_raw(
            spec,
            PARTITION_KEY,
            DuckDBResource(),
        )
        return spec.target_path(PARTITION_KEY), metadata

    @staticmethod
    def _expected_stk_mins_columns() -> tuple[tuple[str, str], ...]:
        return (
            ("ts_code", "VARCHAR"),
            ("freq", "INTEGER"),
            ("trade_time", "TIMESTAMP"),
            ("open", "DOUBLE"),
            ("close", "DOUBLE"),
            ("high", "DOUBLE"),
            ("low", "DOUBLE"),
            ("vol", "BIGINT"),
            ("amount", "DOUBLE"),
            ("exchange", "VARCHAR"),
            ("vwap", "DOUBLE"),
        )


class StockIdentityMapBootstrapTests(unittest.TestCase):
    def test_stock_identity_map_bootstrap_spec_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "data_lake"
            old_lake_root = Path(temp_dir) / "old_lake"
            spec = stock_identity_map_bootstrap_spec(
                lake_root=lake_root,
                old_lake_root=old_lake_root,
            )

        self.assertEqual(spec.dataset_key, "silver_stock_identity_map")
        self.assertEqual(
            spec.source_path,
            old_lake_root
            / "manifest"
            / "security_identity"
            / "security_identity_map.parquet",
        )
        self.assertEqual(
            spec.target_path,
            lake_root / "silver" / "basic" / "stock_identity_map" / "part-000.parquet",
        )
        self.assertEqual(spec.source_fields, SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS)
        self.assertEqual(spec.target_fields, SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS)
        self.assertEqual(spec.empty_policy, "require_positive")
        self.assertEqual(spec.business_key, ("source_ts_code",))

    def test_stock_identity_map_bootstrap_writes_silver_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "data_lake"
            old_lake_root = Path(temp_dir) / "old_lake"
            spec = stock_identity_map_bootstrap_spec(
                lake_root=lake_root,
                old_lake_root=old_lake_root,
            )
            _write_stock_identity_map_file(spec.source_path)

            metadata = bootstrap_stock_identity_map_to_silver(spec, DuckDBResource())

            self.assertTrue(spec.target_path.exists())
            self.assertEqual(_read_columns(spec.target_path), self._expected_identity_columns())
            self.assertEqual(metadata[DAGSTER_ROW_COUNT_METADATA_KEY], 1)
            self.assertEqual(
                metadata[OBSERVED_COLUMNS_METADATA_KEY],
                list(SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS),
            )
            self.assertEqual(
                metadata["goldenshare/bootstrap_spec"],
                "silver_stock_identity_map",
            )
            self.assertTrue(metadata[DAGSTER_URI_METADATA_KEY].endswith("part-000.parquet"))

            with duckdb.connect(database=":memory:") as connection:
                rows = connection.execute(
                    f"""
                    SELECT
                      latest_ts_code,
                      source_ts_code,
                      strftime(valid_from, '%Y-%m-%d'),
                      valid_to IS NULL,
                      identity_source,
                      confidence,
                      typeof(created_at)
                    FROM {read_parquet(spec.target_path, hive_partitioning=False)}
                    """
                ).fetchall()
        self.assertEqual(
            rows,
            [
                (
                    "001872.SZ",
                    "000022.SZ",
                    "1993-04-30",
                    True,
                    "namechange",
                    "inferred",
                    "TIMESTAMP WITH TIME ZONE",
                )
            ],
        )

    def test_stock_identity_map_bootstrap_requires_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            spec = stock_identity_map_bootstrap_spec(
                lake_root=Path(temp_dir) / "data_lake",
                old_lake_root=Path(temp_dir) / "old_lake",
            )

            with self.assertRaisesRegex(FileNotFoundError, "source file is missing"):
                bootstrap_stock_identity_map_to_silver(spec, DuckDBResource())

    def test_stock_identity_map_bootstrap_rejects_existing_target_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            spec = stock_identity_map_bootstrap_spec(
                lake_root=Path(temp_dir) / "data_lake",
                old_lake_root=Path(temp_dir) / "old_lake",
            )
            _write_stock_identity_map_file(spec.source_path)
            spec.target_path.parent.mkdir(parents=True, exist_ok=True)
            spec.target_path.write_bytes(b"existing")

            with self.assertRaisesRegex(FileExistsError, "already exists"):
                bootstrap_stock_identity_map_to_silver(spec, DuckDBResource())

            self.assertEqual(spec.target_path.read_bytes(), b"existing")

    def test_stock_identity_map_bootstrap_rejects_empty_required_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            spec = stock_identity_map_bootstrap_spec(
                lake_root=Path(temp_dir) / "data_lake",
                old_lake_root=Path(temp_dir) / "old_lake",
            )
            _write_stock_identity_map_file(spec.source_path, include_rows=False)

            with self.assertRaisesRegex(ValueError, "Bootstrap produced no rows"):
                bootstrap_stock_identity_map_to_silver(spec, DuckDBResource())

            self.assertFalse(spec.target_path.exists())

    @staticmethod
    def _expected_identity_columns() -> tuple[tuple[str, str], ...]:
        return (
            ("latest_ts_code", "VARCHAR"),
            ("source_ts_code", "VARCHAR"),
            ("valid_from", "DATE"),
            ("valid_to", "DATE"),
            ("effective_list_date", "DATE"),
            ("effective_delist_date", "DATE"),
            ("identity_source", "VARCHAR"),
            ("confidence", "VARCHAR"),
            ("reason", "VARCHAR"),
            ("created_at", "TIMESTAMP WITH TIME ZONE"),
        )


if __name__ == "__main__":
    unittest.main()
