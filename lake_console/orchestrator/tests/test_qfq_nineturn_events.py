from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

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

    def test_report_is_idempotent_and_checks_bind_to_recent_materializations(self) -> None:
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
                any("missing_registered_partitions" in item for item in plan.stop_reasons)
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
