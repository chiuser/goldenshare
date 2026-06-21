import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.checks import adj_factor_checks as checks
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


TARGET_TRADE_DATE = "2026-05-29"


class _PartitionContext:
    def __init__(self, partition_key: str) -> None:
        self.partition_key = partition_key


def _check_function(check_definition):
    return check_definition.node_def.compute_fn.decorated_fn


def _check_name(check_definition) -> str:
    return check_definition.node_def.name


def _sql_string(value: str) -> str:
    return f"{duckdb_string(value)}::VARCHAR"


def _sql_double(value: float | None) -> str:
    return "NULL::DOUBLE" if value is None else f"{value}::DOUBLE"


def _write_raw_adj_factor_file(
    root: Path,
    trade_date: str,
    rows: tuple[tuple[str, str, float | None], ...],
) -> Path:
    path = raw_adj_factor_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        f"({_sql_string(ts_code)}, {_sql_string(row_trade_date)}, {_sql_double(factor)})"
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


def _write_silver_adj_factor_file(
    root: Path,
    trade_date: str,
    rows: tuple[tuple[str, str, float | None], ...],
) -> Path:
    path = silver_adj_factor_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        "("
        f"{_sql_string(ts_code)}, "
        f"DATE {duckdb_string(row_trade_date)}, "
        f"{_sql_double(factor)}"
        ")"
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


def _write_silver_stock_lifecycle_file(
    root: Path,
    rows: tuple[tuple[str, str, str, str, str | None], ...],
) -> Path:
    path = silver_stock_lifecycle_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        "("
        f"{_sql_string(ts_code)}, "
        f"{_sql_string(curr_type)}, "
        f"{_sql_string(list_status)}, "
        f"DATE {duckdb_string(list_date)}, "
        f"{f'DATE {duckdb_string(delist_date)}' if delist_date else 'NULL::DATE'}"
        ")"
        for ts_code, curr_type, list_status, list_date, delist_date in rows
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                ts_code,
                split_part(ts_code, '.', 1)::VARCHAR AS symbol,
                'sample'::VARCHAR AS name,
                CASE WHEN ends_with(ts_code, '.SZ') THEN 'SZSE' ELSE 'SSE' END::VARCHAR AS exchange,
                '主板'::VARCHAR AS market,
                curr_type,
                curr_type = 'CNY' AS is_cny_stock,
                list_status,
                list_date,
                delist_date
              FROM (VALUES {values_sql})
                rows(ts_code, curr_type, list_status, list_date, delist_date)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )
    return path


class AdjFactorCheckTests(unittest.TestCase):
    def test_raw_adj_factor_checks_pass_for_valid_partition_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_raw_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (
                    ("000001.SZ", "20260529", 1.1),
                    ("000002.SZ", "20260529", 2.2),
                ),
            )
            context = _PartitionContext(TARGET_TRADE_DATE)
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()

            for check_definition in (
                checks.raw_adj_factor_file_exists,
                checks.raw_adj_factor_row_count_positive,
                checks.raw_adj_factor_required_columns,
                checks.raw_adj_factor_schema_matches_tushare_contract,
                checks.raw_adj_factor_partition_date_matches,
                checks.raw_adj_factor_unique_ts_code_trade_date,
                checks.raw_adj_factor_positive_factor,
            ):
                with self.subTest(check=_check_name(check_definition)):
                    check_fn = _check_function(check_definition)
                    if _check_name(check_definition).endswith(
                        "raw_adj_factor_file_exists"
                    ):
                        result = check_fn(context, lake_root)
                    else:
                        result = check_fn(context, lake_root, duckdb_resource)
                    self.assertTrue(result.passed)

    def test_raw_adj_factor_checks_catch_bad_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = _PartitionContext(TARGET_TRADE_DATE)
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()

            _write_raw_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (
                    ("000001.SZ", "20260529", 1.1),
                    ("000001.SZ", "20260529", 1.2),
                ),
            )
            unique_check = _check_function(checks.raw_adj_factor_unique_ts_code_trade_date)
            self.assertFalse(unique_check(context, lake_root, duckdb_resource).passed)

            _write_raw_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (("000001.SZ", "20260528", 1.1),),
            )
            date_check = _check_function(checks.raw_adj_factor_partition_date_matches)
            self.assertFalse(date_check(context, lake_root, duckdb_resource).passed)

            _write_raw_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (("000001.SZ", "20260529", 0.0),),
            )
            positive_check = _check_function(checks.raw_adj_factor_positive_factor)
            self.assertFalse(positive_check(context, lake_root, duckdb_resource).passed)

    def test_silver_adj_factor_checks_pass_for_valid_partition_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_silver_stock_lifecycle_file(
                root,
                (
                    ("000001.SZ", "CNY", "L", "2020-01-01", None),
                    ("000002.SZ", "CNY", "D", "2021-01-01", "2026-06-30"),
                    ("000003.SZ", "CNY", "L", "2026-05-30", None),
                    ("000004.SZ", "CNY", "D", "2020-01-01", "2026-04-13"),
                    ("200001.SZ", "HKD", "L", "2020-01-01", None),
                ),
            )
            _write_silver_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (
                    ("000001.SZ", TARGET_TRADE_DATE, 1.1),
                    ("000002.SZ", TARGET_TRADE_DATE, 2.2),
                ),
            )
            context = _PartitionContext(TARGET_TRADE_DATE)
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()

            for check_definition in (
                checks.silver_adj_factor_file_exists,
                checks.silver_adj_factor_row_count_positive,
                checks.silver_adj_factor_required_columns,
                checks.silver_adj_factor_schema_matches_contract,
                checks.silver_adj_factor_partition_date_matches,
                checks.silver_adj_factor_unique_ts_code_trade_date,
                checks.silver_adj_factor_positive_factor,
                checks.silver_adj_factor_listed_stock_only,
                checks.silver_adj_factor_coverage_complete,
            ):
                with self.subTest(check=_check_name(check_definition)):
                    check_fn = _check_function(check_definition)
                    if _check_name(check_definition).endswith(
                        "silver_adj_factor_file_exists"
                    ):
                        result = check_fn(context, lake_root)
                    else:
                        result = check_fn(context, lake_root, duckdb_resource)
                    self.assertTrue(result.passed)

    def test_silver_adj_factor_checks_catch_unlisted_and_missing_coverage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_silver_stock_lifecycle_file(
                root,
                (
                    ("000001.SZ", "CNY", "L", "2020-01-01", None),
                    ("000002.SZ", "CNY", "L", "2021-01-01", None),
                    ("000004.SZ", "CNY", "D", "2020-01-01", "2026-04-13"),
                    ("200001.SZ", "HKD", "L", "2020-01-01", None),
                ),
            )
            context = _PartitionContext(TARGET_TRADE_DATE)
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()

            _write_silver_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (
                    ("000001.SZ", TARGET_TRADE_DATE, 1.1),
                    ("000004.SZ", TARGET_TRADE_DATE, 4.4),
                ),
            )
            listed_check = _check_function(checks.silver_adj_factor_listed_stock_only)
            self.assertFalse(listed_check(context, lake_root, duckdb_resource).passed)

            coverage_check = _check_function(checks.silver_adj_factor_coverage_complete)
            self.assertFalse(coverage_check(context, lake_root, duckdb_resource).passed)

    def test_silver_adj_factor_unique_check_catches_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_silver_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (
                    ("000001.SZ", TARGET_TRADE_DATE, 1.1),
                    ("000001.SZ", TARGET_TRADE_DATE, 1.2),
                ),
            )
            context = _PartitionContext(TARGET_TRADE_DATE)
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()

            unique_check = _check_function(
                checks.silver_adj_factor_unique_ts_code_trade_date
            )
            self.assertFalse(unique_check(context, lake_root, duckdb_resource).passed)

    def test_stock_current_partition_allowed_status(self) -> None:
        self.assertTrue(
            checks._stock_current_partition_allowed_status(
                partition_key=TARGET_TRADE_DATE,
                registered_keys={TARGET_TRADE_DATE},
                today=TARGET_TRADE_DATE,
            )["passed"]
        )
        self.assertFalse(
            checks._stock_current_partition_allowed_status(
                partition_key=TARGET_TRADE_DATE,
                registered_keys=set(),
                today=TARGET_TRADE_DATE,
            )["passed"]
        )
        self.assertFalse(
            checks._stock_current_partition_allowed_status(
                partition_key="2008-12-31",
                registered_keys={"2008-12-31"},
                today=TARGET_TRADE_DATE,
            )["passed"]
        )
        self.assertFalse(
            checks._stock_current_partition_allowed_status(
                partition_key="2026-05-30",
                registered_keys={"2026-05-30"},
                today=TARGET_TRADE_DATE,
            )["passed"]
        )


if __name__ == "__main__":
    unittest.main()
