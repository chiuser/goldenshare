import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import dagster as dg

from orchestrator.defs.bootstrap.stk_nineturn_events import (
    RAW_STK_NINETURN_ASSET_KEY,
    SILVER_STOCK_NINETURN_DAILY_ASSET_KEY,
    plan_stk_nineturn_runless_events,
    report_stk_nineturn_runless_events,
)
from orchestrator.defs.bootstrap.stk_nineturn_history import (
    StkNineturnProdExportManifest,
)
from orchestrator.defs.catalog.lake_assets import (
    RAW_STK_NINETURN_CHECKS,
    SILVER_STOCK_NINETURN_DAILY_CHECKS,
)
from orchestrator.defs.partitions import cn_a_stk_nineturn_trade_days
from orchestrator.defs.paths import (
    raw_stk_nineturn_path,
    silver_stock_identity_map_path,
    silver_stock_nineturn_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.stk_nineturn_contract import (
    write_silver_stock_nineturn_daily_partition,
)


class StkNineturnRunlessEventTests(unittest.TestCase):
    def test_dry_run_is_bounded_and_does_not_write_events(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dates = _prepare_lake(root, count=3)
            instance = _instance_with_partitions(dates)
            report = report_stk_nineturn_runless_events(
                instance=instance,
                manifest=_manifest(dates),
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                dry_run=True,
            )
            raw_materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=RAW_STK_NINETURN_ASSET_KEY,
                    asset_partitions=list(dates),
                ),
                limit=10,
            ).records

        self.assertTrue(report.dry_run)
        self.assertEqual(report.reported_event_count, 0)
        self.assertEqual(report.plan.planned_materialization_event_count, 6)
        self.assertEqual(report.plan.planned_check_event_count, 12)
        self.assertEqual(len(report.plan.raw_check_partition_keys), 3)
        self.assertEqual(raw_materializations, [])

    def test_apply_targets_each_check_to_the_same_partition_materialization(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dates = _prepare_lake(root, count=3)
            instance = _instance_with_partitions(dates)
            report = report_stk_nineturn_runless_events(
                instance=instance,
                manifest=_manifest(dates),
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                dry_run=False,
                confirm_write=True,
                history_audit_report_path="/private/tmp/stk_nineturn_audit.json",
            )
            rerun_plan = plan_stk_nineturn_runless_events(
                instance=instance,
                manifest=_manifest(dates),
                lake_root=root,
                duckdb_resource=DuckDBResource(),
            )
            for asset_key, check_names in (
                (RAW_STK_NINETURN_ASSET_KEY, RAW_STK_NINETURN_CHECKS),
                (
                    SILVER_STOCK_NINETURN_DAILY_ASSET_KEY,
                    SILVER_STOCK_NINETURN_DAILY_CHECKS,
                ),
            ):
                materializations = instance.fetch_materializations(
                    dg.AssetRecordsFilter(
                        asset_key=asset_key,
                        asset_partitions=list(dates),
                    ),
                    limit=10,
                ).records
                materialization_ids = {
                    record.partition_key: record.storage_id
                    for record in materializations
                }
                for check_name in check_names:
                    records = instance.event_log_storage.get_asset_check_execution_history(
                        dg.AssetCheckKey(asset_key, check_name),
                        limit=10,
                    )
                    self.assertEqual(
                        {
                            record.partition
                            for record in records
                            if record.status.value == "SUCCEEDED"
                        },
                        set(dates),
                    )
                    for record in records:
                        evaluation = record.event.dagster_event.event_specific_data
                        self.assertEqual(
                            evaluation.target_materialization_data.storage_id,
                            materialization_ids[record.partition],
                        )

        self.assertEqual(report.reported_event_count, 18)
        self.assertEqual(rerun_plan.planned_materialization_event_count, 0)
        self.assertEqual(rerun_plan.planned_check_event_count, 0)
        self.assertEqual(
            set(rerun_plan.existing_raw_ready_check_partition_keys),
            set(dates),
        )
        self.assertEqual(
            set(rerun_plan.existing_silver_ready_check_partition_keys),
            set(dates),
        )

    def test_apply_requires_explicit_confirmation_and_blocks_failed_lake_audit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dates = _prepare_lake(root, count=1)
            silver_stock_nineturn_daily_path(root, dates[0]).unlink()
            instance = _instance_with_partitions(dates)
            with self.assertRaisesRegex(ValueError, "confirm_write"):
                report_stk_nineturn_runless_events(
                    instance=instance,
                    manifest=_manifest(dates),
                    lake_root=root,
                    duckdb_resource=DuckDBResource(),
                    dry_run=False,
                )
            with self.assertRaisesRegex(ValueError, "audit failed"):
                report_stk_nineturn_runless_events(
                    instance=instance,
                    manifest=_manifest(dates),
                    lake_root=root,
                    duckdb_resource=DuckDBResource(),
                    dry_run=False,
                    confirm_write=True,
                    history_audit_report_path="/private/tmp/stk_nineturn_audit.json",
                )
            materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=RAW_STK_NINETURN_ASSET_KEY),
                limit=10,
            ).records

        self.assertEqual(materializations, [])

    def test_check_scope_is_limited_to_recent_twenty_and_subset_is_validated(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dates = _prepare_lake(root, count=21)
            instance = _instance_with_partitions(dates)
            plan = plan_stk_nineturn_runless_events(
                instance=instance,
                manifest=_manifest(dates),
                lake_root=root,
                duckdb_resource=DuckDBResource(),
            )
            with self.assertRaisesRegex(ValueError, "subset"):
                plan_stk_nineturn_runless_events(
                    instance=instance,
                    manifest=_manifest(dates),
                    lake_root=root,
                    duckdb_resource=DuckDBResource(),
                    materialization_partition_keys=(dates[-1],),
                    check_partition_keys=(dates[-2],),
                )

        self.assertEqual(len(plan.raw_check_partition_keys), 20)
        self.assertEqual(len(plan.silver_check_partition_keys), 20)

    def test_no_active_dagster_definitions_are_added_by_event_helper(self) -> None:
        for relative_path in (
            "src/orchestrator/defs/bootstrap/stk_nineturn_events.py",
            "src/orchestrator/defs/bootstrap/stk_nineturn_events_cli.py",
        ):
            source = Path(relative_path).read_text(encoding="utf-8")
            for token in ("@dg.asset", "@dg.asset_check", "@dg.sensor", "define_asset_job", "RunRequest"):
                self.assertNotIn(token, source)


def _manifest(dates: tuple[str, ...]) -> StkNineturnProdExportManifest:
    return StkNineturnProdExportManifest(
        run_id="test-nineturn-run",
        dataset_id="stk_nineturn",
        source_method="prod-raw-db",
        mode="range_rebuild",
        start_date=dates[0],
        end_date=dates[-1],
        partition_keys=dates,
        source_row_count=len(dates),
        written_row_count=len(dates),
        skipped_partition_keys=(),
        output_paths=(),
    )


def _instance_with_partitions(dates: tuple[str, ...]) -> dg.DagsterInstance:
    instance = dg.DagsterInstance.ephemeral()
    instance.add_dynamic_partitions(cn_a_stk_nineturn_trade_days.name, list(dates))
    return instance


def _prepare_lake(root: Path, *, count: int) -> tuple[str, ...]:
    dates = tuple(
        (date(2026, 6, 1) + timedelta(days=index)).isoformat()
        for index in range(count)
    )
    (root / "raw").mkdir(parents=True)
    (root / "silver").mkdir(parents=True)
    identity_path = silver_stock_identity_map_path(root)
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                CAST('920001.BJ' AS VARCHAR) AS latest_ts_code,
                CAST('920001.BJ' AS VARCHAR) AS source_ts_code,
                DATE '2021-11-15' AS valid_from,
                CAST(NULL AS DATE) AS valid_to
            ) TO {duckdb_string(identity_path)} (FORMAT PARQUET)
            """,
        )
    for partition_key in dates:
        _write_raw_partition(root, partition_key)
        write_silver_stock_nineturn_daily_partition(
            lake_root=root,
            duckdb=DuckDBResource(),
            partition_key=partition_key,
        )
    return dates


def _write_raw_partition(root: Path, partition_key: str) -> None:
    path = raw_stk_nineturn_path(root, partition_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                CAST('920001.BJ' AS VARCHAR) AS ts_code,
                DATE '{partition_key}' AS trade_date,
                CAST('daily' AS VARCHAR) AS freq,
                10.0::DOUBLE AS open,
                11.0::DOUBLE AS high,
                9.0::DOUBLE AS low,
                10.5::DOUBLE AS close,
                100.0::DOUBLE AS vol,
                1000.0::DOUBLE AS amount,
                0.0::DOUBLE AS up_count,
                3.0::DOUBLE AS down_count,
                CAST(NULL AS VARCHAR) AS nine_up_turn,
                CAST(NULL AS VARCHAR) AS nine_down_turn
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """,
        )


if __name__ == "__main__":
    unittest.main()
