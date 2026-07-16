from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import dagster as dg

from orchestrator.defs.bootstrap import stk_mins_stock_year_materialization_reconciliation as subject
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    partition_dataset_readiness_status_from_latest_checks,
)


class _FakeInstance:
    def __init__(self, *, partitions: set[str], materialized: dict[str, set[str]]) -> None:
        self.partitions = partitions
        self.materialized = materialized
        self.reported_events: list[dg.AssetMaterialization] = []

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return sorted(self.partitions)

    def get_materialized_partitions(self, asset_key: dg.AssetKey) -> set[str]:
        return set(self.materialized.get(asset_key.to_user_string(), set()))

    def report_runless_asset_event(self, event: dg.AssetMaterialization) -> None:
        self.reported_events.append(event)
        self.materialized.setdefault(event.asset_key.to_user_string(), set()).add(str(event.partition))


class StockYearMaterializationReconciliationTests(unittest.TestCase):
    def _instance(self) -> _FakeInstance:
        start = date(2014, 1, 2)
        return _FakeInstance(
            partitions={
                (start + timedelta(days=offset)).isoformat()
                for offset in range(25)
            },
            materialized={asset_key: set() for asset_key in subject.TARGET_ASSET_KEYS},
        )

    def _patch_control_plane(
        self,
        *,
        protected_checks: dict[str, set[str]] | None = None,
        unbound_repair_completion_markers: dict[str, set[str]] | None = None,
        active: dict[str, int] | None = None,
    ):
        protected = protected_checks or {}
        markers = unbound_repair_completion_markers or {}
        return patch.multiple(
            subject,
            _check_partition_sets=lambda asset_keys: (
                {asset_key: set(protected.get(asset_key, set())) for asset_key in asset_keys},
                {asset_key: set(markers.get(asset_key, set())) for asset_key in asset_keys},
            ),
            _active_run_statuses=lambda: dict(active or {}),
            _control_counts=lambda: {
                "asset_check_executions": 10,
                "asset_check_event_logs": 11,
                "runs": 12,
                "run_tags": 13,
                "asset_event_tags": 14,
                "dynamic_partitions": 15,
            },
            _protected_check_candidate_pairs=lambda candidates: {
                (candidate.asset_key, candidate.partition_key)
                for candidate in candidates
                if candidate.partition_key in protected.get(candidate.asset_key, set())
            },
        )

    def test_plan_uses_registered_control_plane_and_excludes_hot_window(self) -> None:
        instance = self._instance()
        with tempfile.TemporaryDirectory() as temporary_dir, self._patch_control_plane():
            plan = subject.build_stock_year_materialization_plan(
                instance=instance,
                output_dir=Path(temporary_dir),
            )
        self.assertFalse(plan.report["should_stop"])
        self.assertEqual(plan.report["planned_materialization_event_count"], 70)
        self.assertEqual(
            {candidate.partition_key for candidate in plan.candidates},
            {"2014-01-02", "2014-01-03", "2014-01-04", "2014-01-05", "2014-01-06"},
        )
        self.assertNotIn("2014-01-07", {candidate.partition_key for candidate in plan.candidates})

    def test_plan_excludes_existing_check_without_materialization(self) -> None:
        instance = self._instance()
        checks = {subject.TARGET_ASSET_KEYS[0]: {"2014-01-02"}}
        with tempfile.TemporaryDirectory() as temporary_dir, self._patch_control_plane(
            protected_checks=checks
        ):
            plan = subject.build_stock_year_materialization_plan(
                instance=instance,
                output_dir=Path(temporary_dir),
        )
        first_asset = [candidate for candidate in plan.candidates if candidate.asset_key == subject.TARGET_ASSET_KEYS[0]]
        self.assertNotIn("2014-01-02", {candidate.partition_key for candidate in first_asset})
        report = plan.report["asset_reports"][subject.TARGET_ASSET_KEYS[0]]
        self.assertEqual(report["check_without_materialization"]["count"], 1)

    def test_plan_recovers_unbound_repair_completion_marker_only_partition(self) -> None:
        instance = self._instance()
        asset_key = subject.GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_NAMES[0]
        with tempfile.TemporaryDirectory() as temporary_dir, self._patch_control_plane(
            unbound_repair_completion_markers={asset_key: {"2014-01-02"}}
        ):
            plan = subject.build_stock_year_materialization_plan(
                instance=instance,
                output_dir=Path(temporary_dir),
            )
        asset_candidates = {
            candidate.partition_key for candidate in plan.candidates if candidate.asset_key == asset_key
        }
        self.assertIn("2014-01-02", asset_candidates)
        report = plan.report["asset_reports"][asset_key]
        self.assertEqual(report["check_without_materialization"]["count"], 0)
        self.assertEqual(report["unbound_repair_completion_marker_only"]["count"], 1)

    def test_only_unbound_repair_completion_marker_is_recoverable(self) -> None:
        asset_key = subject.GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_NAMES[0]
        encoded_asset_key = f'["{asset_key}"]'
        with patch.object(
            subject,
            "_psql_rows",
            return_value=[
                (
                    encoded_asset_key,
                    "2014-01-02",
                    subject.GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
                    "SUCCEEDED",
                    None,
                )
            ],
        ):
            protected, markers = subject._check_partition_sets((asset_key,))
        self.assertEqual(protected[asset_key], set())
        self.assertEqual(markers[asset_key], {"2014-01-02"})

        with patch.object(
            subject,
            "_psql_rows",
            return_value=[
                (
                    encoded_asset_key,
                    "2014-01-02",
                    subject.GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
                    "SUCCEEDED",
                    None,
                ),
                (encoded_asset_key, "2014-01-02", "contract", "SUCCEEDED", None),
            ],
        ):
            protected, markers = subject._check_partition_sets((asset_key,))
        self.assertEqual(protected[asset_key], {"2014-01-02"})
        self.assertEqual(markers[asset_key], set())

    def test_empty_psql_field_means_unbound_completion_marker(self) -> None:
        asset_key = subject.GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_NAMES[0]
        encoded_asset_key = f'["{asset_key}"]'
        with patch.object(
            subject,
            "_psql_rows",
            return_value=[
                (
                    encoded_asset_key,
                    "2014-01-02",
                    subject.GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
                    "SUCCEEDED",
                    "",
                )
            ],
        ):
            protected, markers = subject._check_partition_sets((asset_key,))
        self.assertEqual(protected[asset_key], set())
        self.assertEqual(markers[asset_key], {"2014-01-02"})

    def test_apply_recheck_allows_only_unbound_repair_completion_marker(self) -> None:
        asset_key = subject.GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_NAMES[0]
        candidate = subject.StockYearMaterializationCandidate(
            asset_key=asset_key,
            partition_key="2014-01-02",
        )
        encoded_asset_key = f'["{asset_key}"]'
        with patch.object(
            subject,
            "_psql_rows",
            return_value=[
                (
                    encoded_asset_key,
                    "2014-01-02",
                    subject.GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
                    "SUCCEEDED",
                    None,
                )
            ],
        ):
            self.assertEqual(subject._protected_check_candidate_pairs((candidate,)), set())

    def test_failed_repair_completion_marker_remains_protected(self) -> None:
        asset_key = subject.GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_NAMES[0]
        encoded_asset_key = f'["{asset_key}"]'
        with patch.object(
            subject,
            "_psql_rows",
            return_value=[
                (
                    encoded_asset_key,
                    "2014-01-02",
                    subject.GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
                    "FAILED",
                    None,
                )
            ],
        ):
            protected, markers = subject._check_partition_sets((asset_key,))
        self.assertEqual(protected[asset_key], {"2014-01-02"})
        self.assertEqual(markers[asset_key], set())

    def test_plan_stops_for_active_run_or_invalid_partition(self) -> None:
        instance = self._instance()
        instance.partitions.add("not-a-date")
        with tempfile.TemporaryDirectory() as temporary_dir, self._patch_control_plane(active={"STARTED": 1}):
            plan = subject.build_stock_year_materialization_plan(
                instance=instance,
                output_dir=Path(temporary_dir),
            )
        self.assertTrue(plan.report["should_stop"])
        self.assertEqual(
            plan.report["stop_reasons"],
            ["invalid_registered_partition_keys", "active_dagster_runs"],
        )

    def test_apply_reports_only_materializations_and_requires_backup(self) -> None:
        instance = self._instance()
        with tempfile.TemporaryDirectory() as temporary_dir, self._patch_control_plane():
            root = Path(temporary_dir)
            plan = subject.build_stock_year_materialization_plan(instance=instance, output_dir=root)
            backup_manifest = root / "backup-manifest.json"
            backup_manifest.write_text("{}\n", encoding="utf-8")
            report = subject.apply_stock_year_materialization_plan(
                instance=instance,
                plan=plan,
                backup_manifest_path=backup_manifest,
                output_dir=root,
            )
        self.assertEqual(report.reported_event_count, 70)
        self.assertEqual(len(instance.reported_events), 70)
        self.assertTrue(all(isinstance(event, dg.AssetMaterialization) for event in instance.reported_events))
        self.assertTrue(
            all(
                event.metadata["goldenshare/check_events_reported"].value is False
                for event in instance.reported_events
            )
        )

    def test_apply_rejects_stale_plan(self) -> None:
        instance = self._instance()
        with tempfile.TemporaryDirectory() as temporary_dir, self._patch_control_plane():
            root = Path(temporary_dir)
            plan = subject.build_stock_year_materialization_plan(instance=instance, output_dir=root)
            instance.materialized[subject.TARGET_ASSET_KEYS[0]].add("2014-01-02")
            backup_manifest = root / "backup-manifest.json"
            backup_manifest.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(subject.StockYearMaterializationReconciliationError, "stale"):
                subject.apply_stock_year_materialization_plan(
                    instance=instance,
                    plan=plan,
                    backup_manifest_path=backup_manifest,
                    output_dir=root,
                )

    def test_materialization_only_remains_not_ready(self) -> None:
        instance = dg.DagsterInstance.ephemeral()
        asset_key = dg.AssetKey("gold_stk_mins_qfq_1m")
        instance.report_runless_asset_event(
            dg.AssetMaterialization(asset_key=asset_key, partition="2014-01-02")
        )
        status = partition_dataset_readiness_status_from_latest_checks(
            instance,
            (AssetReadinessSpec(asset_key=asset_key, blocking_check_names=("contract",)),),
            partition_key="2014-01-02",
        )
        self.assertFalse(status.ready)
        self.assertTrue(status.statuses[0].materialized)
        self.assertFalse(status.statuses[0].checks_passed)

    def test_source_has_no_lake_or_check_write_dependencies(self) -> None:
        source = Path(subject.__file__).read_text(encoding="utf-8").lower()
        for forbidden in (
            "import duckdb",
            "read_parquet(",
            "lake_root",
            "assetcheckevaluation(",
            "add_dynamic_partitions(",
            "materialize(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
