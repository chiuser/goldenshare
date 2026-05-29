import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

import duckdb

from orchestrator.defs.assets import adj_factor as adj_factor_assets
from orchestrator.defs.assets.adj_factor import SilverAdjFactorPartitionWriteResult
from orchestrator.defs.bootstrap.adj_factor_silver_history import (
    GENERATED_STATUS,
    SKIPPED_EXISTING_STATUS,
    discover_adj_factor_raw_partition_keys,
    write_adj_factor_silver_history,
    write_adj_factor_silver_history_partition,
)
from orchestrator.defs.duckdb_sql import (
    ADJ_FACTOR_SILVER_REQUIRED_COLUMNS,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_basic_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


TARGET_TRADE_DATE = "2026-05-29"


class _PartitionContext:
    partition_key = TARGET_TRADE_DATE


def _sql_string(value: str) -> str:
    return f"{duckdb_string(value)}::VARCHAR"


def _write_raw_adj_factor_file(
    root: Path,
    trade_date: str,
    rows: tuple[tuple[str, str, float], ...],
) -> Path:
    path = raw_adj_factor_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        f"({_sql_string(ts_code)}, {_sql_string(row_trade_date)}, {factor}::DOUBLE)"
        for ts_code, row_trade_date, factor in rows
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (VALUES {values_sql}) rows(ts_code, trade_date, adj_factor)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )
    return path


def _write_silver_stock_basic_file(
    root: Path,
    rows: tuple[tuple[str, str, str], ...],
) -> Path:
    path = silver_stock_basic_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        f"({_sql_string(ts_code)}, {_sql_string(list_status)}, DATE {duckdb_string(list_date)})"
        for ts_code, list_status, list_date in rows
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (VALUES {values_sql}) rows(ts_code, list_status, list_date)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )
    return path


def _write_existing_silver_file(root: Path, trade_date: str) -> Path:
    path = silver_adj_factor_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                '000001.SZ'::VARCHAR AS ts_code,
                DATE {duckdb_string(trade_date)} AS trade_date,
                1.0::DOUBLE AS adj_factor
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )
    return path


def _read_silver_rows(path: Path) -> list[tuple[str, str, float]]:
    with duckdb.connect(database=":memory:") as connection:
        return connection.execute(
            f"""
            SELECT ts_code, strftime(trade_date, '%Y-%m-%d'), adj_factor
            FROM {read_parquet(path, hive_partitioning=False)}
            ORDER BY ts_code
            """
        ).fetchall()


def _read_silver_columns(path: Path) -> tuple[str, ...]:
    with duckdb.connect(database=":memory:") as connection:
        rows = connection.execute(
            f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        ).fetchall()
    return tuple(row[0] for row in rows)


class AdjFactorSilverHistoryTests(unittest.TestCase):
    def test_generates_silver_partition_from_migrated_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_raw_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (
                    ("000001.SZ", "20260529", 1.1),
                    ("000002.SZ", "20260529", 2.2),
                    ("000003.SZ", "20260529", 3.3),
                ),
            )
            _write_silver_stock_basic_file(
                root,
                (
                    ("000001.SZ", "L", "2020-01-01"),
                    ("000002.SZ", "D", "2020-01-01"),
                    ("000003.SZ", "L", "2026-05-30"),
                ),
            )

            audit = write_adj_factor_silver_history_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_key=TARGET_TRADE_DATE,
            )
            target_path = silver_adj_factor_path(root, TARGET_TRADE_DATE)
            target_columns = _read_silver_columns(target_path)
            target_rows = _read_silver_rows(target_path)

        self.assertEqual(audit.status, GENERATED_STATUS)
        self.assertEqual(audit.source_row_count, 3)
        self.assertEqual(audit.selected_row_count, 1)
        self.assertEqual(audit.rejected_row_count, 2)
        self.assertEqual(audit.observed_columns, ADJ_FACTOR_SILVER_REQUIRED_COLUMNS)
        self.assertEqual(target_columns, ADJ_FACTOR_SILVER_REQUIRED_COLUMNS)
        self.assertEqual(target_rows, [("000001.SZ", "2026-05-29", 1.1)])

    def test_discovers_raw_partitions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for partition_key in ("2026-05-28", "2026-05-29"):
                _write_raw_adj_factor_file(
                    root,
                    partition_key,
                    (("000001.SZ", partition_key.replace("-", ""), 1.0),),
                )
            ignored_path = root / "raw" / "tushare" / "adj_factor" / "bad" / "part-000.parquet"
            ignored_path.parent.mkdir(parents=True, exist_ok=True)
            ignored_path.touch()

            partition_keys = discover_adj_factor_raw_partition_keys(root)

        self.assertEqual(partition_keys, ("2026-05-28", "2026-05-29"))

    def test_existing_target_requires_explicit_overwrite_for_single_partition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_raw_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (("000001.SZ", "20260529", 1.1),),
            )
            _write_silver_stock_basic_file(
                root,
                (("000001.SZ", "L", "2020-01-01"),),
            )
            _write_existing_silver_file(root, TARGET_TRADE_DATE)

            with self.assertRaisesRegex(FileExistsError, "already exists"):
                write_adj_factor_silver_history_partition(
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    partition_key=TARGET_TRADE_DATE,
                )

            audit = write_adj_factor_silver_history_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_key=TARGET_TRADE_DATE,
                overwrite=True,
            )

        self.assertEqual(audit.status, GENERATED_STATUS)

    def test_bulk_generation_skips_existing_targets_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for partition_key in ("2026-05-28", "2026-05-29"):
                _write_raw_adj_factor_file(
                    root,
                    partition_key,
                    (("000001.SZ", partition_key.replace("-", ""), 1.0),),
                )
            _write_silver_stock_basic_file(
                root,
                (("000001.SZ", "L", "2020-01-01"),),
            )
            _write_existing_silver_file(root, "2026-05-28")

            audits = write_adj_factor_silver_history(
                lake_root=root,
                duckdb=DuckDBResource(),
            )

        self.assertEqual([audit.partition_key for audit in audits], ["2026-05-28", "2026-05-29"])
        self.assertEqual([audit.status for audit in audits], [SKIPPED_EXISTING_STATUS, GENERATED_STATUS])

    def test_missing_inputs_raise_clear_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with self.assertRaisesRegex(FileNotFoundError, "Missing raw adj factor file"):
                write_adj_factor_silver_history_partition(
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    partition_key=TARGET_TRADE_DATE,
                )

            _write_raw_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (("000001.SZ", "20260529", 1.1),),
            )
            with self.assertRaisesRegex(FileNotFoundError, "Missing silver stock basic file"):
                write_adj_factor_silver_history_partition(
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    partition_key=TARGET_TRADE_DATE,
                )

    def test_silver_asset_uses_shared_partition_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for layer_name in ("raw", "silver", "gold"):
                (root / layer_name).mkdir()
            write_result = SilverAdjFactorPartitionWriteResult(
                raw_file_path=raw_adj_factor_path(root, TARGET_TRADE_DATE),
                stock_basic_file_path=silver_stock_basic_path(root),
                silver_file_path=silver_adj_factor_path(root, TARGET_TRADE_DATE),
                source_row_count=2,
                current_listed_stock_count=1,
                selected_row_count=1,
                rejected_row_count=1,
                row_count=1,
                observed_columns=ADJ_FACTOR_SILVER_REQUIRED_COLUMNS,
            )
            asset_fn = adj_factor_assets.silver_adj_factor.node_def.compute_fn.decorated_fn

            with patch(
                "orchestrator.defs.assets.adj_factor.write_silver_adj_factor_partition",
                return_value=write_result,
            ) as shared_writer:
                asset_fn(
                    _PartitionContext(),
                    LakeRootResource(root_path=str(root)),
                    DuckDBResource(),
                )

        shared_writer.assert_called_once_with(
            lake_root=root,
            duckdb=ANY,
            partition_key=TARGET_TRADE_DATE,
            overwrite=True,
        )


if __name__ == "__main__":
    unittest.main()
