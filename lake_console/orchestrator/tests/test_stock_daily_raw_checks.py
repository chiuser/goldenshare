import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import dagster as dg

from orchestrator.defs.checks import stock_daily_checks
from orchestrator.defs.assets.stock_daily import STOCK_DAILY_RAW_COLUMN_TYPES
from orchestrator.defs.catalog.lake_assets import SILVER_STOCK_DAILY_CHECKS
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, silver_stock_daily_select
from orchestrator.defs.paths import (
    raw_stock_daily_path,
    silver_stock_daily_path,
    silver_stock_basic_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.sensors import readiness


PARTITION_KEY = "2026-05-29"


class _PartitionContext:
    def __init__(self, partition_key: str) -> None:
        self.partition_key = partition_key


def _metadata_value(value):
    return value.value if hasattr(value, "value") else value


def _check_function(check_definition):
    if not hasattr(check_definition, "node_def"):
        return check_definition
    return check_definition.node_def.compute_fn.decorated_fn


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
    curr_type: str = "CNY",
    list_status: str = "L",
    list_date: str = "2020-01-01",
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "curr_type": curr_type,
        "list_status": list_status,
        "list_date": list_date,
    }


def _stock_lifecycle_row(
    ts_code: str,
    *,
    curr_type: str = "CNY",
    list_status: str = "L",
    list_date: str = "2020-01-01",
    delist_date: str | None = None,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "symbol": ts_code.split(".")[0],
        "name": ts_code,
        "exchange": ts_code.split(".")[1] if "." in ts_code else "",
        "market": "主板",
        "curr_type": curr_type,
        "is_cny_stock": curr_type == "CNY",
        "list_status": list_status,
        "list_date": list_date,
        "delist_date": delist_date,
    }


def _raw_row(
    ts_code: str,
    *,
    trade_date: str = "20260529",
) -> dict[str, object]:
    return {"ts_code": ts_code, "trade_date": trade_date}


def _full_raw_row(ts_code: str) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": "20260529",
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "pre_close": 10.0,
        "change": 0.5,
        "pct_chg": 5.0,
        "vol": 100.0,
        "amount": 1050.0,
    }


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
            "curr_type": "VARCHAR",
            "list_status": "VARCHAR",
            "list_date": "DATE",
        },
        rows=rows,
        order_by="ts_code",
    )
    return path


def _write_stock_lifecycle(lake_root: Path, rows: list[dict[str, object]]) -> Path:
    path = silver_stock_lifecycle_path(lake_root)
    _write_rows(
        path,
        column_types={
            "ts_code": "VARCHAR",
            "symbol": "VARCHAR",
            "name": "VARCHAR",
            "exchange": "VARCHAR",
            "market": "VARCHAR",
            "curr_type": "VARCHAR",
            "is_cny_stock": "BOOLEAN",
            "list_status": "VARCHAR",
            "list_date": "DATE",
            "delist_date": "DATE",
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
            stock_lifecycle_path=basic_path,
            stock_lifecycle_sql=(
                stock_daily_checks._current_cny_stock_lifecycle_select(basic_path)
            ),
            suspend_path=suspend_path,
            daily_code_set_sql=stock_daily_checks._raw_daily_code_set_sql(
                raw_path, PARTITION_KEY
            ),
        )


def _silver_universe_metadata(
    lake_root: Path,
    *,
    lifecycle_rows: list[dict[str, object]],
    suspend_rows: list[dict[str, object]],
    silver_rows: list[dict[str, object]],
) -> dict[str, object]:
    silver_path = _write_silver(lake_root, silver_rows)
    lifecycle_path = _write_stock_lifecycle(lake_root, lifecycle_rows)
    suspend_path = _write_suspend(lake_root, suspend_rows)
    with DuckDBResource().connect() as connection:
        return stock_daily_checks._expected_tradable_universe_metadata(
            connection,
            partition_key=PARTITION_KEY,
            daily_path=silver_path,
            stock_lifecycle_path=lifecycle_path,
            stock_lifecycle_sql=stock_daily_checks.silver_cny_stock_lifecycle_select(
                lifecycle_path
            ),
            suspend_path=suspend_path,
            daily_code_set_sql=stock_daily_checks._silver_daily_code_set_sql(
                silver_path, PARTITION_KEY
            ),
        )


class StockDailyRawCheckTests(unittest.TestCase):
    def test_combined_check_metadata_is_human_readable_and_keeps_rule_names(
        self,
    ) -> None:
        result = stock_daily_checks._combined_check_result(
            check_scope=stock_daily_checks.CheckScope.SCHEMA,
            rule_results=(
                ("rule_ok", dg.AssetCheckResult(passed=True)),
                ("rule_bad", dg.AssetCheckResult(passed=False)),
            ),
        )

        self.assertFalse(result.passed)
        self.assertEqual(
            _metadata_value(result.metadata["goldenshare/failed_rule_names"]),
            ["rule_bad"],
        )
        self.assertIn("失败", _metadata_value(result.metadata["goldenshare/summary"]))
        self.assertIn(
            "failed_rule_names",
            _metadata_value(result.metadata["goldenshare/next_action"]),
        )
        self.assertEqual(
            _metadata_value(result.metadata["goldenshare/rule_summary"]),
            [
                {"rule_name": "rule_ok", "passed": True},
                {"rule_name": "rule_bad", "passed": False},
            ],
        )

    def test_missing_file_metadata_tells_operator_next_step(self) -> None:
        result = stock_daily_checks._missing_file_result(Path("/tmp/missing.parquet"))

        self.assertFalse(result.passed)
        self.assertIn(
            "输入文件不存在",
            _metadata_value(result.metadata["goldenshare/summary"]),
        )
        self.assertIn(
            "重新运行",
            _metadata_value(result.metadata["goldenshare/next_action"]),
        )
        self.assertEqual(
            _metadata_value(result.metadata["goldenshare/file_path"]),
            "/tmp/missing.parquet",
        )

    def test_silver_coverage_check_is_blocking_readiness_gate(self) -> None:
        self.assertIn(
            "silver_stock_daily_tradable_universe_check",
            readiness.SILVER_STOCK_DAILY_BLOCKING_CHECKS,
        )
        self.assertNotIn(
            "silver_stock_daily_row_count_matches_expected_tradable_count",
            readiness.SILVER_STOCK_DAILY_BLOCKING_CHECKS,
        )

    def test_silver_stock_daily_lifecycle_check_replaces_current_listed_gate(
        self,
    ) -> None:
        self.assertIn(
            "silver_stock_daily_lifecycle_coverage_check",
            readiness.SILVER_STOCK_DAILY_BLOCKING_CHECKS,
        )
        self.assertNotIn(
            "silver_stock_daily_current_listed_only",
            readiness.SILVER_STOCK_DAILY_BLOCKING_CHECKS,
        )
        self.assertIn(
            "silver_stock_daily_lifecycle_coverage_check",
            SILVER_STOCK_DAILY_CHECKS,
        )
        self.assertNotIn(
            "silver_stock_daily_current_listed_only",
            SILVER_STOCK_DAILY_CHECKS,
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
        self.assertIn("通过", metadata["summary"])
        self.assertEqual(
            metadata["tradable_universe_summary"]["expected_count"],
            2,
        )

    def test_raw_universe_excludes_non_cny_stock_basic_codes(self) -> None:
        with TemporaryDirectory() as directory:
            metadata = _raw_universe_metadata(
                Path(directory),
                basic_rows=[
                    _basic_row("000001.SZ"),
                    _basic_row("200011.SZ", curr_type="HKD"),
                    _basic_row("900901.SH", curr_type="USD"),
                ],
                suspend_rows=[],
                raw_rows=[_raw_row("000001.SZ")],
            )

        self.assertEqual(metadata["listed_count"], 1)
        self.assertEqual(metadata["expected_count"], 1)
        self.assertEqual(metadata["daily_count"], 1)
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
        self.assertIn("失败", metadata["summary"])
        self.assertEqual(
            metadata["tradable_universe_summary"]["unexplained_missing_count"],
            1,
        )

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
                lifecycle_rows=[
                    _stock_lifecycle_row("000001.SZ"),
                    _stock_lifecycle_row("000002.SZ"),
                    _stock_lifecycle_row("000003.SZ"),
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
        self.assertIn("通过", metadata["summary"])
        self.assertEqual(
            metadata["tradable_universe_summary"][
                "explained_by_full_day_suspend_count"
            ],
            1,
        )

    def test_silver_universe_excludes_non_cny_stock_basic_codes(self) -> None:
        with TemporaryDirectory() as directory:
            metadata = _silver_universe_metadata(
                Path(directory),
                lifecycle_rows=[
                    _stock_lifecycle_row("000001.SZ"),
                    _stock_lifecycle_row("200011.SZ", curr_type="HKD"),
                    _stock_lifecycle_row("900901.SH", curr_type="USD"),
                ],
                suspend_rows=[],
                silver_rows=[_silver_row("000001.SZ")],
            )

        self.assertEqual(metadata["listed_count"], 1)
        self.assertEqual(metadata["expected_count"], 1)
        self.assertEqual(metadata["daily_count"], 1)
        self.assertEqual(metadata["unexplained_missing_count"], 0)
        self.assertEqual(metadata["unexplained_extra_count"], 0)

    def test_silver_select_excludes_non_cny_stock_basic_rows(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            raw_path = raw_stock_daily_path(lake_root, PARTITION_KEY)
            lifecycle_path = _write_stock_lifecycle(
                lake_root,
                [
                    _stock_lifecycle_row("000001.SZ"),
                    _stock_lifecycle_row("200011.SZ", curr_type="HKD"),
                    _stock_lifecycle_row("900901.SH", curr_type="USD"),
                ],
            )
            _write_rows(
                raw_path,
                column_types=dict(STOCK_DAILY_RAW_COLUMN_TYPES),
                rows=[
                    _full_raw_row("000001.SZ"),
                    _full_raw_row("200011.SZ"),
                    _full_raw_row("900901.SH"),
                ],
                order_by="ts_code, trade_date",
            )
            with DuckDBResource().connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT ts_code
                    FROM ({silver_stock_daily_select(raw_path, lifecycle_path)})
                    ORDER BY ts_code
                    """
                ).fetchall()

        self.assertEqual([row[0] for row in rows], ["000001.SZ"])

    def test_silver_select_keeps_delisted_stock_within_lifecycle(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            raw_path = raw_stock_daily_path(lake_root, PARTITION_KEY)
            lifecycle_path = _write_stock_lifecycle(
                lake_root,
                [
                    _stock_lifecycle_row(
                        "000638.SZ",
                        list_status="D",
                        list_date="1996-11-26",
                        delist_date="2026-06-03",
                    )
                ],
            )
            _write_rows(
                raw_path,
                column_types=dict(STOCK_DAILY_RAW_COLUMN_TYPES),
                rows=[_full_raw_row("000638.SZ")],
                order_by="ts_code, trade_date",
            )
            with DuckDBResource().connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT ts_code
                    FROM ({silver_stock_daily_select(raw_path, lifecycle_path)})
                    ORDER BY ts_code
                    """
                ).fetchall()

        self.assertEqual([row[0] for row in rows], ["000638.SZ"])

    def test_silver_select_excludes_stock_after_lifecycle(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            raw_path = raw_stock_daily_path(lake_root, PARTITION_KEY)
            lifecycle_path = _write_stock_lifecycle(
                lake_root,
                [
                    _stock_lifecycle_row(
                        "000638.SZ",
                        list_status="D",
                        list_date="1996-11-26",
                        delist_date="2026-05-01",
                    )
                ],
            )
            _write_rows(
                raw_path,
                column_types=dict(STOCK_DAILY_RAW_COLUMN_TYPES),
                rows=[_full_raw_row("000638.SZ")],
                order_by="ts_code, trade_date",
            )
            with DuckDBResource().connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT ts_code
                    FROM ({silver_stock_daily_select(raw_path, lifecycle_path)})
                    ORDER BY ts_code
                    """
                ).fetchall()

        self.assertEqual(rows, [])

    def test_silver_lifecycle_check_reports_out_of_lifecycle_rows(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_stock_lifecycle(
                lake_root,
                [
                    _stock_lifecycle_row(
                        "000638.SZ",
                        list_status="D",
                        list_date="1996-11-26",
                        delist_date="2026-05-01",
                    )
                ],
            )
            _write_silver(lake_root, [_silver_row("000638.SZ")])
            result = _check_function(
                stock_daily_checks.silver_stock_daily_stock_lifecycle_covered
            )(
                _PartitionContext(PARTITION_KEY),
                LakeRootResource(root_path=str(lake_root)),
                DuckDBResource(),
            )

        self.assertFalse(result.passed)

    def test_silver_universe_reports_missing_expected_code(self) -> None:
        with TemporaryDirectory() as directory:
            metadata = _silver_universe_metadata(
                Path(directory),
                lifecycle_rows=[
                    _stock_lifecycle_row("000001.SZ"),
                    _stock_lifecycle_row("000002.SZ"),
                ],
                suspend_rows=[],
                silver_rows=[_silver_row("000001.SZ")],
            )

        self.assertEqual(metadata["expected_count"], 2)
        self.assertEqual(metadata["daily_count"], 1)
        self.assertEqual(metadata["unexplained_missing_count"], 1)
        self.assertEqual(metadata["missing_sample_ts_codes"], ["000002.SZ"])
        self.assertIn("失败", metadata["summary"])
        self.assertIn("missing/extra", metadata["next_action"])

    def test_silver_universe_reports_unexpected_extra_code(self) -> None:
        with TemporaryDirectory() as directory:
            metadata = _silver_universe_metadata(
                Path(directory),
                lifecycle_rows=[_stock_lifecycle_row("000001.SZ")],
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
                lifecycle_rows=[
                    _stock_lifecycle_row("000001.SZ"),
                    _stock_lifecycle_row("000002.SZ"),
                ],
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
                lifecycle_rows=[
                    _stock_lifecycle_row("000001.SZ"),
                    _stock_lifecycle_row("000002.SZ"),
                ],
                suspend_rows=[_suspend_row("000002.SZ", suspend_timing="10:00-15:00")],
                silver_rows=[_silver_row("000001.SZ")],
            )

        self.assertEqual(metadata["intraday_suspend_count"], 1)
        self.assertEqual(metadata["unexplained_missing_count"], 1)
        self.assertEqual(metadata["missing_sample_ts_codes"], ["000002.SZ"])


if __name__ == "__main__":
    unittest.main()
