from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.qfq_nineturn_events import (
    QfqNineturnEventError,
    plan_qfq_nineturn_runless_events,
    report_qfq_nineturn_runless_events,
)
from orchestrator.defs.bootstrap.qfq_nineturn_history import (
    build_qfq_nineturn_history,
    plan_qfq_nineturn_history,
)
from orchestrator.defs.partitions import (
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_trade_days,
)
from orchestrator.defs.resources import DuckDBResource
from tests.qfq_nineturn_history_fixture import (
    build_qfq_nineturn_history_fixture,
)


class QfqNineturnEventTests(unittest.TestCase):
    def test_forced_refresh_can_be_scoped_to_minute_assets_only(self) -> None:
        with TemporaryDirectory() as directory, dg.instance_for_test() as instance:
            root = Path(directory)
            dates, history_plan, audit_path = _built_history(root)
            _register_dates(instance, dates)
            initial_plan = plan_qfq_nineturn_runless_events(
                instance=instance,
                history_plan_path=history_plan.report_path,
                history_audit_report_path=audit_path,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )
            report_qfq_nineturn_runless_events(
                instance=instance,
                plan=initial_plan,
                expected_plan_fingerprint=initial_plan.plan_fingerprint,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )
            daily_key = dg.AssetKey("gold_stock_daily_qfq_nineturn")
            daily_before = instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=daily_key),
                limit=len(dates),
            ).records
            minute_asset_keys = tuple(
                f"gold_stk_mins_qfq_nineturn_{freq}m" for freq in (30, 60, 90, 120)
            )

            refresh_plan = plan_qfq_nineturn_runless_events(
                instance=instance,
                history_plan_path=history_plan.report_path,
                history_audit_report_path=audit_path,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
                force_materialization_refresh=True,
                event_revision="minute-no-price-v2-test",
                asset_keys=minute_asset_keys,
            )

            self.assertFalse(refresh_plan.should_stop)
            self.assertEqual(refresh_plan.report["asset_keys"], list(minute_asset_keys))
            self.assertEqual(
                refresh_plan.planned_materialization_event_count,
                len(dates) * 4,
            )
            self.assertEqual(refresh_plan.planned_check_event_count, 20 * 4)
            self.assertNotIn(
                "gold_stock_daily_qfq_nineturn",
                {candidate.asset_key for candidate in refresh_plan.candidates},
            )
            refresh = report_qfq_nineturn_runless_events(
                instance=instance,
                plan=refresh_plan,
                expected_plan_fingerprint=refresh_plan.plan_fingerprint,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )
            self.assertEqual(refresh.materialization_event_count, len(dates) * 4)
            self.assertEqual(refresh.check_event_count, 20 * 4)
            daily_after = instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=daily_key),
                limit=len(dates),
            ).records
            self.assertEqual(
                [record.storage_id for record in daily_after],
                [record.storage_id for record in daily_before],
            )

    def test_event_asset_selection_rejects_unknown_and_duplicate_assets(self) -> None:
        with TemporaryDirectory() as directory, dg.instance_for_test() as instance:
            root = Path(directory)
            dates, history_plan, audit_path = _built_history(root)
            _register_dates(instance, dates)
            selections = (
                ("unknown",),
                ("gold_stk_mins_qfq_nineturn_30m",) * 2,
            )
            for asset_keys in selections:
                with (
                    self.subTest(asset_keys=asset_keys),
                    self.assertRaises(QfqNineturnEventError),
                ):
                    plan_qfq_nineturn_runless_events(
                        instance=instance,
                        history_plan_path=history_plan.report_path,
                        history_audit_report_path=audit_path,
                        lake_root=root,
                        duckdb_resource=DuckDBResource(),
                        output_dir=root / "reports",
                        asset_keys=asset_keys,
                    )

    def test_plan_writes_no_events_and_limits_checks_to_recent_twenty(self) -> None:
        with TemporaryDirectory() as directory, dg.instance_for_test() as instance:
            root = Path(directory)
            dates, history_plan, audit_path = _built_history(root)
            _register_dates(instance, dates)

            plan = plan_qfq_nineturn_runless_events(
                instance=instance,
                history_plan_path=history_plan.report_path,
                history_audit_report_path=audit_path,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )

            self.assertFalse(plan.should_stop)
            self.assertEqual(plan.planned_materialization_event_count, len(dates) * 5)
            self.assertEqual(plan.planned_check_event_count, 20 * 5)
            self.assertEqual(instance.get_runs_count(), 0)
            self.assertFalse(
                instance.get_materialized_partitions(
                    dg.AssetKey("gold_stock_daily_qfq_nineturn")
                )
            )

    def test_report_is_idempotent_and_checks_bind_to_recent_materializations(
        self,
    ) -> None:
        with TemporaryDirectory() as directory, dg.instance_for_test() as instance:
            root = Path(directory)
            dates, history_plan, audit_path = _built_history(root)
            _register_dates(instance, dates)
            plan = plan_qfq_nineturn_runless_events(
                instance=instance,
                history_plan_path=history_plan.report_path,
                history_audit_report_path=audit_path,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )

            report = report_qfq_nineturn_runless_events(
                instance=instance,
                plan=plan,
                expected_plan_fingerprint=plan.plan_fingerprint,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )

            self.assertEqual(report.materialization_event_count, len(dates) * 5)
            self.assertEqual(report.check_event_count, 20 * 5)
            self.assertEqual(report.post_plan_event_count, 0)
            self.assertEqual(instance.get_runs_count(), 0)
            second_plan = plan_qfq_nineturn_runless_events(
                instance=instance,
                history_plan_path=history_plan.report_path,
                history_audit_report_path=audit_path,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )
            self.assertFalse(second_plan.candidates)

            daily_checks = instance.event_log_storage.get_asset_check_execution_history(
                dg.AssetCheckKey(
                    dg.AssetKey("gold_stock_daily_qfq_nineturn"),
                    "gold_stock_daily_qfq_nineturn_integrity_check",
                ),
                limit=100,
            )
            self.assertEqual(len(daily_checks), 20)
            self.assertEqual(
                {record.partition for record in daily_checks},
                set(dates[-20:]),
            )

    def test_forced_refresh_appends_new_materializations_and_latest_checks(
        self,
    ) -> None:
        with TemporaryDirectory() as directory, dg.instance_for_test() as instance:
            root = Path(directory)
            dates, history_plan, audit_path = _built_history(root)
            _register_dates(instance, dates)
            initial_plan = plan_qfq_nineturn_runless_events(
                instance=instance,
                history_plan_path=history_plan.report_path,
                history_audit_report_path=audit_path,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )
            report_qfq_nineturn_runless_events(
                instance=instance,
                plan=initial_plan,
                expected_plan_fingerprint=initial_plan.plan_fingerprint,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )

            refresh_plan = plan_qfq_nineturn_runless_events(
                instance=instance,
                history_plan_path=history_plan.report_path,
                history_audit_report_path=audit_path,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
                force_materialization_refresh=True,
                event_revision="canonical-bars-p12-test",
            )
            self.assertFalse(refresh_plan.should_stop)
            self.assertEqual(
                refresh_plan.planned_materialization_event_count,
                len(dates) * 5,
            )
            self.assertEqual(refresh_plan.planned_check_event_count, 20 * 5)
            refresh = report_qfq_nineturn_runless_events(
                instance=instance,
                plan=refresh_plan,
                expected_plan_fingerprint=refresh_plan.plan_fingerprint,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )
            self.assertEqual(refresh.materialization_event_count, len(dates) * 5)
            self.assertEqual(refresh.check_event_count, 20 * 5)
            self.assertEqual(refresh.post_plan_event_count, 0)

    def test_state_change_makes_reviewed_plan_stale(self) -> None:
        with TemporaryDirectory() as directory, dg.instance_for_test() as instance:
            root = Path(directory)
            dates, history_plan, audit_path = _built_history(root)
            _register_dates(instance, dates)
            plan = plan_qfq_nineturn_runless_events(
                instance=instance,
                history_plan_path=history_plan.report_path,
                history_audit_report_path=audit_path,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=dg.AssetKey("gold_stock_daily_qfq_nineturn"),
                    partition=dates[0],
                )
            )

            with self.assertRaisesRegex(QfqNineturnEventError, "stale"):
                report_qfq_nineturn_runless_events(
                    instance=instance,
                    plan=plan,
                    expected_plan_fingerprint=plan.plan_fingerprint,
                    lake_root=root,
                    duckdb_resource=DuckDBResource(),
                    output_dir=root / "reports",
                )

    def test_missing_registered_partition_stops_plan(self) -> None:
        with TemporaryDirectory() as directory, dg.instance_for_test() as instance:
            root = Path(directory)
            dates, history_plan, audit_path = _built_history(root)
            _register_dates(instance, dates[:-1])

            plan = plan_qfq_nineturn_runless_events(
                instance=instance,
                history_plan_path=history_plan.report_path,
                history_audit_report_path=audit_path,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )
            self.assertTrue(plan.should_stop)
            self.assertTrue(
                any(
                    "missing_registered_partitions" in item
                    for item in plan.stop_reasons
                )
            )

    def test_existing_failed_check_bound_to_current_materialization_stops(self) -> None:
        with TemporaryDirectory() as directory, dg.instance_for_test() as instance:
            root = Path(directory)
            dates, history_plan, audit_path = _built_history(root)
            _register_dates(instance, dates)
            partition_key = dates[-1]
            asset_key = dg.AssetKey("gold_stock_daily_qfq_nineturn")
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=asset_key,
                    partition=partition_key,
                )
            )
            materialization = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=asset_key,
                    asset_partitions=[partition_key],
                ),
                limit=1,
            ).records[0]
            instance.report_runless_asset_event(
                dg.AssetCheckEvaluation(
                    asset_key=asset_key,
                    check_name="gold_stock_daily_qfq_nineturn_integrity_check",
                    passed=False,
                    blocking=True,
                    partition=partition_key,
                    target_materialization_data=(
                        AssetCheckEvaluationTargetMaterializationData(
                            storage_id=materialization.storage_id,
                            run_id=materialization.run_id,
                            timestamp=materialization.timestamp,
                        )
                    ),
                )
            )

            plan = plan_qfq_nineturn_runless_events(
                instance=instance,
                history_plan_path=history_plan.report_path,
                history_audit_report_path=audit_path,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )
            self.assertTrue(plan.should_stop)
            self.assertIn(
                (
                    "gold_stock_daily_qfq_nineturn:"
                    f"{partition_key}:existing_failed_check"
                ),
                plan.stop_reasons,
            )


def _built_history(root: Path):
    dates = build_qfq_nineturn_history_fixture(root)
    resource = DuckDBResource()
    plan = plan_qfq_nineturn_history(
        lake_root=root,
        duckdb_resource=resource,
        output_dir=root / "reports",
    )
    report = build_qfq_nineturn_history(
        plan=plan,
        expected_plan_fingerprint=plan.plan_fingerprint,
        duckdb_resource=resource,
        staging_root=root / "staging",
        output_dir=root / "reports",
    )
    return dates, plan, report.final_audit_report_path


def _register_dates(instance: dg.DagsterInstance, dates: tuple[str, ...]) -> None:
    instance.add_dynamic_partitions(cn_a_stock_trade_days.name, list(dates))
    instance.add_dynamic_partitions(
        cn_a_stock_mins_silver_trade_days.name,
        list(dates),
    )


if __name__ == "__main__":
    unittest.main()
