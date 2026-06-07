import tempfile
import unittest
from pathlib import Path

from orchestrator.defs.checks import stock_partition_checks
from orchestrator.defs.checks import suspend_d_checks as checks
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.paths import raw_suspend_d_path, silver_stock_suspend_daily_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.sensors import readiness


PARTITION_KEY = "2026-06-05"


class _FakeInstance:
    def __init__(self, partitions: tuple[str, ...]) -> None:
        self._partitions = partitions

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(self._partitions)


class _PartitionContext:
    def __init__(self, partition_key: str = PARTITION_KEY) -> None:
        self.partition_key = partition_key
        self.instance = _FakeInstance((partition_key,))


def _check_function(check_definition):
    return check_definition.node_def.compute_fn.decorated_fn


def _check_name(check_definition) -> str:
    return check_definition.node_def.name


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


def _write_raw_suspend_file(
    root: Path,
    rows: list[dict[str, object]],
    *,
    column_types: dict[str, str] | None = None,
) -> Path:
    path = raw_suspend_d_path(root, PARTITION_KEY)
    _write_rows(
        path,
        column_types=column_types
        or {
            "ts_code": "VARCHAR",
            "trade_date": "VARCHAR",
            "suspend_timing": "VARCHAR",
            "suspend_type": "VARCHAR",
        },
        rows=rows,
        order_by="ts_code, trade_date",
    )
    return path


def _write_silver_suspend_file(root: Path, rows: list[dict[str, object]]) -> Path:
    path = silver_stock_suspend_daily_path(root, PARTITION_KEY)
    _write_rows(
        path,
        column_types={
            "ts_code": "VARCHAR",
            "trade_date": "DATE",
            "suspend_timing": "VARCHAR",
            "suspend_type": "VARCHAR",
        },
        rows=rows,
        order_by="ts_code, trade_date",
    )
    return path


class SuspendDCheckTests(unittest.TestCase):
    def test_existing_suspend_d_check_names_are_not_renamed(self) -> None:
        self.assertEqual(
            readiness.RAW_SUSPEND_D_CHECKS,
            (
                "raw_suspend_d_file_exists",
                "raw_suspend_d_partition_date_matches",
                "raw_suspend_d_required_columns",
                "raw_suspend_d_schema_matches_tushare_contract",
                "raw_suspend_d_stock_partition_key_allowed",
            ),
        )
        self.assertEqual(
            readiness.SILVER_SUSPEND_D_CHECKS,
            (
                "silver_suspend_d_known_type_values",
                "silver_suspend_d_stock_partition_key_allowed",
                "silver_suspend_d_unique_business_key",
            ),
        )
        self.assertNotIn(
            "raw_suspend_d_row_count_positive",
            readiness.RAW_SUSPEND_D_CHECKS,
        )

    def test_empty_raw_parquet_passes_raw_blocking_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_raw_suspend_file(root, [])
            context = _PartitionContext()
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()

            check_definitions = (
                checks.raw_suspend_d_file_exists,
                checks.raw_suspend_d_required_columns,
                checks.raw_suspend_d_partition_date_matches,
                checks.raw_suspend_d_schema_matches_tushare_contract,
                stock_partition_checks.raw_suspend_d_stock_partition_key_allowed,
            )
            for check_definition in check_definitions:
                with self.subTest(check=_check_name(check_definition)):
                    check_fn = _check_function(check_definition)
                    if _check_name(check_definition).endswith("_file_exists"):
                        result = check_fn(context, lake_root)
                    elif _check_name(check_definition).endswith(
                        "_stock_partition_key_allowed"
                    ):
                        result = check_fn(context)
                    else:
                        result = check_fn(context, lake_root, duckdb_resource)
                    self.assertTrue(result.passed)

    def test_raw_parquet_missing_required_column_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_raw_suspend_file(
                root,
                [],
                column_types={
                    "ts_code": "VARCHAR",
                    "trade_date": "VARCHAR",
                    "suspend_type": "VARCHAR",
                },
            )
            context = _PartitionContext()
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()
            check_fn = _check_function(checks.raw_suspend_d_required_columns)

            result = check_fn(context, lake_root, duckdb_resource)

        self.assertFalse(result.passed)

    def test_raw_parquet_wrong_partition_date_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_raw_suspend_file(
                root,
                [
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": "20260604",
                        "suspend_timing": "09:30",
                        "suspend_type": "S",
                    }
                ],
            )
            context = _PartitionContext()
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()
            check_fn = _check_function(checks.raw_suspend_d_partition_date_matches)

            result = check_fn(context, lake_root, duckdb_resource)

        self.assertFalse(result.passed)

    def test_empty_silver_parquet_passes_silver_blocking_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_silver_suspend_file(root, [])
            context = _PartitionContext()
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()

            check_definitions = (
                checks.silver_suspend_d_known_type_values,
                stock_partition_checks.silver_suspend_d_stock_partition_key_allowed,
                checks.silver_suspend_d_unique_business_key,
            )
            for check_definition in check_definitions:
                with self.subTest(check=_check_name(check_definition)):
                    check_fn = _check_function(check_definition)
                    if _check_name(check_definition).endswith(
                        "_stock_partition_key_allowed"
                    ):
                        result = check_fn(context)
                    else:
                        result = check_fn(context, lake_root, duckdb_resource)
                    self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
