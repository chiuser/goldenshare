import tempfile
import unittest
from pathlib import Path

import dagster as dg

from orchestrator.defs.assets import stk_mins
from orchestrator.defs.bootstrap.stk_mins_silver_bootstrap_events import (
    SILVER_STK_MINS_ASSET_KEYS,
    SILVER_STK_MINS_CHECKS,
    audit_stk_mins_silver_bootstrap_partition,
    report_stk_mins_silver_bootstrap_events,
)
from orchestrator.defs.bootstrap.stk_mins_silver_history import (
    generate_stk_mins_silver_history,
    plan_stk_mins_silver_history,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.partitions import cn_a_stock_mins_trade_days
from orchestrator.defs.paths import (
    raw_stk_mins_path,
    silver_namechange_path,
    silver_stk_mins_path,
    silver_stock_basic_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)


PARTITION_KEY = "2014-06-03"


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


def _raw_row(freq: int) -> dict[str, object]:
    return {
        "ts_code": "600000.SH",
        "freq": freq,
        "trade_time": f"{PARTITION_KEY} 09:30:00",
        "open": 10.0,
        "close": 10.0,
        "high": 10.0,
        "low": 10.0,
        "vol": 100,
        "amount": 1000.0,
        "exchange": "XSHG",
        "vwap": 10.0,
    }


def _write_raw_inputs(lake_root: Path, partition_key: str = PARTITION_KEY) -> None:
    for freq in STK_MINS_FREQS:
        row = _raw_row(freq)
        row["trade_time"] = f"{partition_key} 09:30:00"
        _write_rows(
            raw_stk_mins_path(lake_root, freq, partition_key),
            column_types=stk_mins.STK_MINS_RAW_COLUMN_TYPES,
            rows=[row],
            order_by="ts_code, trade_time",
        )


def _write_common_inputs(lake_root: Path, partition_key: str = PARTITION_KEY) -> None:
    _write_rows(
        silver_stock_identity_map_path(lake_root),
        column_types={
            "latest_ts_code": "VARCHAR",
            "source_ts_code": "VARCHAR",
            "valid_from": "DATE",
            "valid_to": "DATE",
            "effective_list_date": "DATE",
            "effective_delist_date": "DATE",
            "identity_source": "VARCHAR",
            "confidence": "VARCHAR",
            "reason": "VARCHAR",
            "created_at": "TIMESTAMP WITH TIME ZONE",
        },
        rows=[
            {
                "latest_ts_code": "600000.SH",
                "source_ts_code": "600000.SH",
                "valid_from": "2000-01-01",
                "valid_to": None,
                "effective_list_date": "2000-01-01",
                "effective_delist_date": None,
                "identity_source": "current_code",
                "confidence": "high",
                "reason": "test",
                "created_at": "2026-05-31 00:00:00+08",
            }
        ],
    )
    _write_rows(
        silver_stock_daily_path(lake_root, partition_key),
        column_types={"ts_code": "VARCHAR", "trade_date": "DATE"},
        rows=[{"ts_code": "600000.SH", "trade_date": partition_key}],
        order_by="ts_code",
    )
    _write_rows(
        silver_stock_suspend_daily_path(lake_root, partition_key),
        column_types={
            "ts_code": "VARCHAR",
            "trade_date": "DATE",
            "suspend_type": "VARCHAR",
            "suspend_timing": "VARCHAR",
        },
        rows=[],
        order_by="ts_code",
    )
    _write_rows(
        silver_stock_basic_path(lake_root),
        column_types={"ts_code": "VARCHAR", "name": "VARCHAR"},
        rows=[{"ts_code": "600000.SH", "name": "浦发银行"}],
        order_by="ts_code",
    )
    _write_rows(
        silver_namechange_path(lake_root),
        column_types={
            "ts_code": "VARCHAR",
            "name": "VARCHAR",
            "start_date": "DATE",
            "end_date": "DATE",
        },
        rows=[
            {
                "ts_code": "600000.SH",
                "name": "浦发银行",
                "start_date": "2000-01-01",
                "end_date": None,
            }
        ],
        order_by="ts_code, start_date",
    )


def _write_valid_silver_history(lake_root: Path) -> None:
    _write_raw_inputs(lake_root)
    _write_common_inputs(lake_root)
    generate_stk_mins_silver_history(
        lake_root=lake_root,
        duckdb=DuckDBResource(),
        partition_keys=[PARTITION_KEY],
    )


class StkMinsSilverM6HistoryTests(unittest.TestCase):
    def test_m6_helpers_do_not_define_active_dagster_components(self) -> None:
        helper_paths = (
            Path("src/orchestrator/defs/bootstrap/stk_mins_silver_history.py"),
            Path("src/orchestrator/defs/bootstrap/stk_mins_silver_bootstrap_events.py"),
        )
        forbidden_tokens = (
            "@dg.asset",
            "@dg.asset_check",
            "@dg.sensor",
            "define_asset_job",
        )
        for helper_path in helper_paths:
            text = helper_path.read_text()
            for token in forbidden_tokens:
                self.assertNotIn(token, text)

    def test_plan_reports_history_scope_and_missing_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_raw_inputs(lake_root)

            plan = plan_stk_mins_silver_history(lake_root=lake_root)

        self.assertEqual(plan.selected_partition_keys, (PARTITION_KEY,))
        self.assertEqual(
            dict(plan.raw_partition_counts),
            {freq: 1 for freq in STK_MINS_FREQS},
        )
        self.assertEqual(plan.planned_write_count, len(STK_MINS_FREQS))
        self.assertEqual(plan.planned_event_count, len(STK_MINS_FREQS) * 11)
        self.assertGreater(plan.missing_input_count, 0)
        self.assertEqual(plan.sample_partition_keys, (PARTITION_KEY,))

    def test_generates_silver_history_and_skips_existing_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_raw_inputs(lake_root)
            _write_common_inputs(lake_root)

            first = generate_stk_mins_silver_history(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                partition_keys=[PARTITION_KEY],
            )
            second = generate_stk_mins_silver_history(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                partition_keys=[PARTITION_KEY],
                skip_existing=True,
            )

            self.assertEqual(len(first.written_asset_partitions), len(STK_MINS_FREQS))
            self.assertEqual(first.skipped_existing_asset_partitions, ())
            self.assertEqual(second.written_asset_partitions, ())
            self.assertEqual(
                len(second.skipped_existing_asset_partitions),
                len(STK_MINS_FREQS),
            )
            for freq in STK_MINS_FREQS:
                self.assertTrue(
                    silver_stk_mins_path(lake_root, freq, PARTITION_KEY).exists()
                )

    def test_event_dry_run_audits_without_writing_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_silver_history(lake_root)
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_trade_days.name,
                [PARTITION_KEY],
            )

            report = report_stk_mins_silver_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                partition_keys=[PARTITION_KEY],
                dry_run=True,
            )
            materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=SILVER_STK_MINS_ASSET_KEYS[1],
                    asset_partitions=[PARTITION_KEY],
                ),
                limit=1,
            ).records

        self.assertTrue(report.dry_run)
        self.assertEqual(report.plan.failed_partition_count, 0)
        self.assertEqual(report.plan.planned_event_count, len(STK_MINS_FREQS) * 11)
        self.assertEqual(report.reported_event_count, 0)
        self.assertEqual(materializations, [])

    def test_reports_silver_events_and_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_silver_history(lake_root)
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_trade_days.name,
                [PARTITION_KEY],
            )

            report = report_stk_mins_silver_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                partition_keys=[PARTITION_KEY],
                dry_run=False,
            )
            readiness = asset_readiness_status(
                instance,
                AssetReadinessSpec(SILVER_STK_MINS_ASSET_KEYS[1], SILVER_STK_MINS_CHECKS),
                partition_key=PARTITION_KEY,
            )
            second = report_stk_mins_silver_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                partition_keys=[PARTITION_KEY],
                dry_run=False,
                skip_existing_materialized=True,
            )

        self.assertEqual(report.reported_event_count, len(STK_MINS_FREQS) * 11)
        self.assertTrue(readiness.ready)
        self.assertEqual(second.reported_event_count, 0)
        self.assertEqual(
            len(second.skipped_materialized_asset_partitions),
            len(STK_MINS_FREQS),
        )

    def test_failed_silver_audit_blocks_event_reporting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_silver_history(lake_root)
            bad_path = silver_stk_mins_path(lake_root, 1, PARTITION_KEY)
            _write_rows(
                bad_path,
                column_types=stk_mins.STK_MINS_SILVER_COLUMN_TYPES,
                rows=[
                    {
                        "ts_code": "600000.SH",
                        "freq": 1,
                        "trade_date": PARTITION_KEY,
                        "trade_time": f"{PARTITION_KEY} 09:30:00",
                        "open": 0.0,
                        "high": 10.0,
                        "low": 10.0,
                        "close": 10.0,
                        "vol": 100.0,
                        "amount": 1000.0,
                        "exchange": "SSE",
                    }
                ],
                order_by="ts_code, trade_time",
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_trade_days.name,
                [PARTITION_KEY],
            )

            audit = audit_stk_mins_silver_bootstrap_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                freq=1,
                partition_key=PARTITION_KEY,
            )
            with self.assertRaisesRegex(ValueError, "silver bootstrap audit failed"):
                report_stk_mins_silver_bootstrap_events(
                    instance=instance,
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    partition_keys=[PARTITION_KEY],
                    dry_run=True,
                )

        self.assertIn("silver_stk_mins_price_sanity", audit.failed_check_names)


if __name__ == "__main__":
    unittest.main()
