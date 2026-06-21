import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import dagster as dg

from orchestrator.defs.asset_guards.stock_daily import (
    assert_silver_stock_basic_fresh_for_stock_daily,
)
from orchestrator.defs.assets.stock_daily import (
    raw_tushare_stock_daily,
    silver_stock_daily,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import (
    raw_stock_daily_path,
    silver_stock_basic_path,
    silver_stock_daily_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors.readiness import AssetReadinessStatus


PARTITION_KEY = "2026-05-29"


class _FakeLakeRoot:
    def __init__(self, root: Path) -> None:
        self._root = root

    def ensure_available_for_run(self) -> None:
        return None

    def root(self) -> Path:
        return self._root


class _FakeContext:
    def __init__(self, *, instance: object, partition_key: str = PARTITION_KEY) -> None:
        self.instance = instance
        self.partition_key = partition_key


def _status(
    *,
    ready: bool,
    materialized: bool = True,
    checks_passed: bool = True,
    freshness_passed: bool = True,
    materialization_date: str | None = PARTITION_KEY,
    missing_check_names: tuple[str, ...] = (),
    failed_check_names: tuple[str, ...] = (),
    reason: str = "ready",
) -> AssetReadinessStatus:
    return AssetReadinessStatus(
        asset_key="silver_stock_basic",
        partition_key=None,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        freshness_passed=freshness_passed,
        materialization_storage_id=1 if materialized else None,
        materialization_date=materialization_date,
        missing_check_names=missing_check_names,
        failed_check_names=failed_check_names,
        reason=reason,
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


def _write_raw(lake_root: Path, ts_code: str = "000001.SZ") -> None:
    _write_rows(
        raw_stock_daily_path(lake_root, PARTITION_KEY),
        column_types={
            "ts_code": "VARCHAR",
            "trade_date": "VARCHAR",
            "open": "DOUBLE",
            "high": "DOUBLE",
            "low": "DOUBLE",
            "close": "DOUBLE",
            "pre_close": "DOUBLE",
            "change": "DOUBLE",
            "pct_chg": "DOUBLE",
            "vol": "DOUBLE",
            "amount": "DOUBLE",
        },
        rows=[
            {
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
        ],
        order_by="ts_code, trade_date",
    )


def _write_basic(lake_root: Path, ts_code: str = "000001.SZ") -> None:
    _write_rows(
        silver_stock_basic_path(lake_root),
        column_types={
            "ts_code": "VARCHAR",
            "curr_type": "VARCHAR",
            "list_status": "VARCHAR",
            "list_date": "DATE",
        },
        rows=[
            {
                "ts_code": ts_code,
                "curr_type": "CNY",
                "list_status": "L",
                "list_date": "2020-01-01",
            }
        ],
        order_by="ts_code",
    )


def _write_stock_lifecycle(lake_root: Path, ts_code: str = "000001.SZ") -> None:
    _write_rows(
        silver_stock_lifecycle_path(lake_root),
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
        rows=[
            {
                "ts_code": ts_code,
                "symbol": ts_code.split(".")[0],
                "name": ts_code,
                "exchange": ts_code.split(".")[1] if "." in ts_code else "",
                "market": "主板",
                "curr_type": "CNY",
                "is_cny_stock": True,
                "list_status": "L",
                "list_date": "2020-01-01",
                "delist_date": None,
            }
        ],
        order_by="ts_code",
    )


def _write_suspend(lake_root: Path) -> None:
    _write_rows(
        silver_stock_suspend_daily_path(lake_root, PARTITION_KEY),
        column_types={
            "ts_code": "VARCHAR",
            "trade_date": "DATE",
            "suspend_type": "VARCHAR",
            "suspend_timing": "VARCHAR",
        },
        rows=[],
        order_by="ts_code",
    )


def _write_existing_silver_target(lake_root: Path) -> None:
    _write_rows(
        silver_stock_daily_path(lake_root, PARTITION_KEY),
        column_types={
            "ts_code": "VARCHAR",
            "trade_date": "DATE",
            "open": "DOUBLE",
            "high": "DOUBLE",
            "low": "DOUBLE",
            "close": "DOUBLE",
            "pre_close": "DOUBLE",
            "change_amount": "DOUBLE",
            "pct_chg": "DOUBLE",
            "vol": "DOUBLE",
            "amount": "DOUBLE",
        },
        rows=[
            {
                "ts_code": "999999.SZ",
                "trade_date": PARTITION_KEY,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "pre_close": 1.0,
                "change_amount": 0.0,
                "pct_chg": 0.0,
                "vol": 1.0,
                "amount": 1.0,
            }
        ],
        order_by="ts_code, trade_date",
    )


def _target_ts_codes(path: Path) -> list[str]:
    with DuckDBResource().connect() as connection:
        rows = connection.execute(
            f"SELECT ts_code FROM {read_parquet(path)} ORDER BY ts_code"
        ).fetchall()
    return [row[0] for row in rows]


def _call_silver_asset(lake_root: Path, *, instance: object) -> dg.MaterializeResult:
    return silver_stock_daily.op.compute_fn.decorated_fn(
        _FakeContext(instance=instance),
        _FakeLakeRoot(lake_root),
        DuckDBResource(),
    )


class StockDailyFreshnessGuardTests(unittest.TestCase):
    def test_guard_fails_closed_for_not_ready_stock_basic_statuses(self) -> None:
        cases = (
            _status(
                ready=False,
                materialized=False,
                checks_passed=False,
                freshness_passed=False,
                materialization_date=None,
                reason="silver_stock_basic has no materialization",
            ),
            _status(
                ready=False,
                checks_passed=False,
                missing_check_names=("silver_stock_basic_unique_ts_code",),
                reason="silver_stock_basic missing blocking checks",
            ),
            _status(
                ready=False,
                checks_passed=False,
                failed_check_names=("silver_stock_basic_current_listed_only",),
                reason="silver_stock_basic failed blocking checks",
            ),
            _status(
                ready=False,
                freshness_passed=False,
                materialization_date="2026-05-28",
                reason=(
                    "silver_stock_basic materialized at 2026-05-28, "
                    "before required date 2026-05-29"
                ),
            ),
        )

        for status in cases:
            with self.subTest(reason=status.reason):
                with patch(
                    "orchestrator.defs.asset_guards.stock_daily."
                    "silver_stock_basic_ready_for_trade_date",
                    return_value=status,
                ):
                    with self.assertRaisesRegex(
                        dg.Failure,
                        "silver_stock_daily cannot be produced",
                    ):
                        assert_silver_stock_basic_fresh_for_stock_daily(
                            object(),
                            PARTITION_KEY,
                        )

    def test_raw_asset_does_not_reference_stock_basic_freshness_guard(self) -> None:
        raw_source = raw_tushare_stock_daily.op.compute_fn.decorated_fn.__code__.co_names
        forbidden_names = {
            "assert_silver_stock_basic_fresh_for_stock_daily",
            "silver_stock_basic_ready_for_trade_date",
            "stock_basic_ready_for_trade_date",
        }

        self.assertEqual(forbidden_names.intersection(raw_source), set())

    def test_silver_asset_stale_stock_basic_fails_before_creating_target(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_raw(lake_root)
            _write_stock_lifecycle(lake_root)
            _write_basic(lake_root)
            _write_suspend(lake_root)
            target_path = silver_stock_daily_path(lake_root, PARTITION_KEY)

            with patch(
                "orchestrator.defs.asset_guards.stock_daily."
                "silver_stock_basic_ready_for_trade_date",
                return_value=_status(
                    ready=False,
                    freshness_passed=False,
                    materialization_date="2026-05-28",
                    reason="silver_stock_basic stale",
                ),
            ):
                with self.assertRaises(dg.Failure):
                    _call_silver_asset(lake_root, instance=object())

            self.assertFalse(target_path.exists())

    def test_silver_asset_stale_stock_basic_does_not_overwrite_existing_target(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_raw(lake_root)
            _write_stock_lifecycle(lake_root)
            _write_basic(lake_root)
            _write_suspend(lake_root)
            _write_existing_silver_target(lake_root)
            target_path = silver_stock_daily_path(lake_root, PARTITION_KEY)

            with patch(
                "orchestrator.defs.asset_guards.stock_daily."
                "silver_stock_basic_ready_for_trade_date",
                return_value=_status(
                    ready=False,
                    freshness_passed=False,
                    materialization_date="2026-05-28",
                    reason="silver_stock_basic stale",
                ),
            ):
                with self.assertRaises(dg.Failure):
                    _call_silver_asset(lake_root, instance=object())

            self.assertEqual(_target_ts_codes(target_path), ["999999.SZ"])

    def test_silver_asset_ready_stock_basic_writes_silver_partition(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_raw(lake_root)
            _write_stock_lifecycle(lake_root)
            _write_basic(lake_root)
            _write_suspend(lake_root)
            target_path = silver_stock_daily_path(lake_root, PARTITION_KEY)

            with patch(
                "orchestrator.defs.asset_guards.stock_daily."
                "silver_stock_basic_ready_for_trade_date",
                return_value=_status(ready=True),
            ):
                result = _call_silver_asset(lake_root, instance=object())

            self.assertIsInstance(result, dg.MaterializeResult)
            self.assertEqual(_target_ts_codes(target_path), ["000001.SZ"])


if __name__ == "__main__":
    unittest.main()
