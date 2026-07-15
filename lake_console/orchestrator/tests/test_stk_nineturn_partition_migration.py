import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import dagster as dg

from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)
from orchestrator.defs.bootstrap.stk_nineturn_events import (
    RAW_STK_NINETURN_ASSET_KEY,
    SILVER_STOCK_NINETURN_DAILY_ASSET_KEY,
)
from orchestrator.defs.bootstrap.stk_nineturn_partition_migration import (
    STK_NINETURN_PARTITION_AUDIT_BATCH_SIZE,
    apply_stk_nineturn_partition_migration,
    audit_stk_nineturn_event_compatibility,
    plan_stk_nineturn_partition_migration,
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
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)
from orchestrator.defs.stk_nineturn_contract import (
    RAW_STK_NINETURN_COLUMNS,
    RAW_STK_NINETURN_COLUMN_TYPES,
    write_silver_stock_nineturn_daily_partition,
)


TRADE_DATES = ("2026-07-07", "2026-07-08", "2026-07-09")


class StkNineturnPartitionMigrationTests(unittest.TestCase):
    def test_plan_freezes_complete_candidate_and_lake_readiness(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake(root)
            plan = plan_stk_nineturn_partition_migration(
                instance=dg.DagsterInstance.ephemeral(),
                lake_root=root,
                duckdb_resource=DuckDBResource(),
            )

        self.assertEqual(plan.candidate_partition_keys, TRADE_DATES)
        self.assertEqual(plan.candidate_partition_hash, _hash(TRADE_DATES))
        self.assertEqual(plan.historical_cutoff_date, TRADE_DATES[-1])
        self.assertEqual(plan.planned_partition_keys, TRADE_DATES)
        self.assertEqual(plan.readiness_batch_size, STK_NINETURN_PARTITION_AUDIT_BATCH_SIZE)
        self.assertEqual(plan.readiness_batch_count, 1)
        self.assertEqual(
            plan.readiness_scanned_file_count,
            len(TRADE_DATES) * 3 + 1,
        )
        self.assertFalse(plan.should_stop, plan.to_dict())

    def test_plan_excludes_future_calendar_dates_after_file_frontier(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake(root)
            plan = plan_stk_nineturn_partition_migration(
                instance=dg.DagsterInstance.ephemeral(),
                lake_root=root,
                duckdb_resource=DuckDBResource(),
            )

        self.assertEqual(plan.candidate_partition_keys, TRADE_DATES)
        self.assertEqual(plan.historical_cutoff_date, "2026-07-09")
        self.assertNotIn("2026-12-31", plan.candidate_partition_keys)
        self.assertFalse(plan.should_stop, plan.to_dict())

    def test_plan_rejects_raw_silver_tail_asymmetry(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake(root)
            silver_stock_nineturn_daily_path(root, TRADE_DATES[-1]).unlink()
            plan = plan_stk_nineturn_partition_migration(
                instance=dg.DagsterInstance.ephemeral(),
                lake_root=root,
                duckdb_resource=DuckDBResource(),
            )

        self.assertEqual(plan.historical_cutoff_date, TRADE_DATES[-2])
        self.assertEqual(plan.raw_outside_candidate_keys, (TRADE_DATES[-1],))
        self.assertIn("raw_files_outside_candidate", plan.stop_reasons)

    def test_plan_rejects_lake_partition_set_or_contract_mismatch(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake(root)
            raw_stk_nineturn_path(root, TRADE_DATES[0]).unlink()
            plan = plan_stk_nineturn_partition_migration(
                instance=dg.DagsterInstance.ephemeral(),
                lake_root=root,
                duckdb_resource=DuckDBResource(),
            )

        self.assertIn(TRADE_DATES[0], plan.candidate_missing_raw_keys)
        self.assertIn(TRADE_DATES[0], plan.raw_readiness_failed_keys)
        self.assertIn("candidate_missing_raw_files", plan.stop_reasons)
        self.assertIn("raw_readiness_failed", plan.stop_reasons)

    def test_plan_rejects_existing_new_partition_outside_candidate(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake(root)
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stk_nineturn_trade_days.name,
                ["2022-12-30"],
            )
            plan = plan_stk_nineturn_partition_migration(
                instance=instance,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
            )

        self.assertEqual(
            plan.existing_new_partition_keys_outside_candidate,
            ("2022-12-30",),
        )
        self.assertIn("existing_new_partition_outside_candidate", plan.stop_reasons)

    def test_apply_requires_confirmation_and_is_idempotent(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake(root)
            instance = dg.DagsterInstance.ephemeral()
            with self.assertRaisesRegex(ValueError, "confirm_apply"):
                apply_stk_nineturn_partition_migration(
                    instance=instance,
                    lake_root=root,
                    duckdb_resource=DuckDBResource(),
                )
            first = apply_stk_nineturn_partition_migration(
                instance=instance,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                confirm_apply=True,
                expected_candidate_hash=_hash(TRADE_DATES),
                expected_candidate_count=len(TRADE_DATES),
            )
            second = apply_stk_nineturn_partition_migration(
                instance=instance,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                confirm_apply=True,
                expected_candidate_hash=_hash(TRADE_DATES),
                expected_candidate_count=len(TRADE_DATES),
            )

        self.assertEqual(first.registered_partition_keys, TRADE_DATES)
        self.assertEqual(first.final_partition_keys, TRADE_DATES)
        self.assertEqual(second.registered_partition_keys, ())
        self.assertEqual(second.final_partition_keys, TRADE_DATES)

    def test_apply_rejects_a_changed_approved_candidate_before_write(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake(root)
            instance = dg.DagsterInstance.ephemeral()
            with self.assertRaisesRegex(ValueError, "hash changed after approval"):
                apply_stk_nineturn_partition_migration(
                    instance=instance,
                    lake_root=root,
                    duckdb_resource=DuckDBResource(),
                    confirm_apply=True,
                    expected_candidate_hash="not-the-approved-hash",
                    expected_candidate_count=len(TRADE_DATES),
                )

            registered = instance.get_dynamic_partitions(
                cn_a_stk_nineturn_trade_days.name
            )

        self.assertEqual(registered, [])

    def test_ephemeral_events_remain_ready_with_the_new_partition_identity(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake(root)
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stk_nineturn_trade_days.name,
                list(TRADE_DATES),
            )
            _report_ready_events(
                instance,
                RAW_STK_NINETURN_ASSET_KEY,
                RAW_STK_NINETURN_CHECKS,
                TRADE_DATES[0],
            )
            _report_ready_events(
                instance,
                SILVER_STOCK_NINETURN_DAILY_ASSET_KEY,
                SILVER_STOCK_NINETURN_DAILY_CHECKS,
                TRADE_DATES[0],
            )
            raw_status = asset_readiness_status(
                instance,
                AssetReadinessSpec(
                    RAW_STK_NINETURN_ASSET_KEY,
                    RAW_STK_NINETURN_CHECKS,
                ),
                partition_key=TRADE_DATES[0],
            )
            silver_status = asset_readiness_status(
                instance,
                AssetReadinessSpec(
                    SILVER_STOCK_NINETURN_DAILY_ASSET_KEY,
                    SILVER_STOCK_NINETURN_DAILY_CHECKS,
                ),
                partition_key=TRADE_DATES[0],
            )
            compatibility = audit_stk_nineturn_event_compatibility(
                instance=instance,
                candidate_partition_keys=TRADE_DATES,
            )

        self.assertTrue(raw_status.ready)
        self.assertTrue(silver_status.ready)
        self.assertEqual(compatibility.stop_reasons, ())

    def test_event_preflight_rejects_partition_outside_candidate(self) -> None:
        instance = dg.DagsterInstance.ephemeral()
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=RAW_STK_NINETURN_ASSET_KEY,
                partition="2022-12-30",
            )
        )

        compatibility = audit_stk_nineturn_event_compatibility(
            instance=instance,
            candidate_partition_keys=TRADE_DATES,
        )

        self.assertEqual(
            compatibility.materialized_partition_keys_outside_candidate,
            ("2022-12-30",),
        )
        self.assertIn(
            "materialized_partition_outside_candidate",
            compatibility.stop_reasons,
        )


def _prepare_lake(root: Path) -> None:
    _write_calendar(root)
    _write_identity(root)
    for trade_date in TRADE_DATES:
        _write_raw(root, trade_date)
        write_silver_stock_nineturn_daily_partition(
            lake_root=root,
            duckdb=DuckDBResource(),
            partition_key=trade_date,
        )


def _write_calendar(root: Path) -> None:
    path = silver_trade_calendar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            """
            COPY (
              SELECT * FROM (VALUES
                ('SSE', false, DATE '2023-01-02'),
                ('SSE', true, DATE '2026-07-07'),
                ('SSE', true, DATE '2026-07-08'),
                ('SSE', true, DATE '2026-07-09'),
                ('SSE', true, DATE '2026-12-31')
              ) AS rows(exchange, is_open, trade_date)
            ) TO ? (FORMAT PARQUET)
            """,
            [str(path)],
        )


def _write_identity(root: Path) -> None:
    path = silver_stock_identity_map_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            """
            COPY (
              SELECT
                '600030.SH'::VARCHAR AS latest_ts_code,
                '600030.SH'::VARCHAR AS source_ts_code,
                DATE '1990-01-01' AS valid_from,
                NULL::DATE AS valid_to
            ) TO ? (FORMAT PARQUET)
            """,
            [str(path)],
        )


def _write_raw(root: Path, trade_date: str) -> None:
    path = raw_stk_nineturn_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        column_defs = ", ".join(
            f'"{column}" {RAW_STK_NINETURN_COLUMN_TYPES[column]}'
            for column in RAW_STK_NINETURN_COLUMNS
        )
        connection.execute(f"CREATE TEMP TABLE rows_to_write ({column_defs})")
        connection.execute(
            f"""
            INSERT INTO rows_to_write VALUES (
              '600030.SH', DATE '{trade_date}', 'daily', 10.0, 11.0, 9.0, 10.5,
              100.0, 1000.0, 0.0, 3.0, NULL, NULL
            )
            """
        )
        connection.execute(
            f"""
            COPY (
              SELECT {', '.join(RAW_STK_NINETURN_COLUMNS)}
              FROM rows_to_write
            ) TO ? (FORMAT PARQUET)
            """,
            [str(path)],
        )


def _report_ready_events(
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    check_names: tuple[str, ...],
    partition_key: str,
) -> None:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(asset_key=asset_key, partition=partition_key)
    )
    materialization = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=asset_key, asset_partitions=[partition_key]),
        limit=1,
    ).records[0]
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    for check_name in check_names:
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=asset_key,
                check_name=check_name,
                passed=True,
                blocking=True,
                partition=partition_key,
                target_materialization_data=target,
            )
        )


def _hash(values: tuple[str, ...]) -> str:
    from hashlib import sha256

    return sha256("\n".join(values).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    unittest.main()
