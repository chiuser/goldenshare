from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dagster as dg
import duckdb

from orchestrator.defs.bootstrap.historical_materialization_reconciliation import (
    RECONCILIATION_METHOD,
    ReconciliationCandidate,
    ReconciliationPlan,
    HistoricalMaterializationReconciliationError,
    _hash_payload,
    _physical_candidate_fingerprint,
    apply_historical_materialization_reconciliation,
    load_historical_materialization_reconciliation_plan,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    partition_dataset_readiness_status_from_latest_checks,
)


ASSET_KEY = "raw_index_daily"
PARTITION_KEY = "2024-01-02"


class HistoricalMaterializationReconciliationTests(unittest.TestCase):
    def test_manifest_rejects_candidate_outside_approved_a_to_e_scope(self) -> None:
        with self.assertRaisesRegex(
            HistoricalMaterializationReconciliationError,
            "outside approved A-E scope",
        ):
            ReconciliationCandidate.from_dict(
                {
                    "classification": "safe_candidate",
                    "asset_key": "silver_stock_daily",
                    "partition_key": PARTITION_KEY,
                    "physical_fingerprint": "x",
                    "canonical_uri": "/tmp/x.parquet",
                    "file_count": 1,
                    "required_paths": ["x.parquet"],
                    "files": [],
                }
            )

    def test_load_rejects_manifest_sha_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            manifest_path = root / "candidates.jsonl"
            manifest_path.write_text("{}\n", encoding="utf-8")
            report_path = root / "plan.json"
            report_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "phase": "P0_read_only_inventory",
                        "read_only": True,
                        "should_stop": False,
                        "candidate_manifest_path": str(manifest_path),
                        "candidate_manifest_sha256": "not-a-real-sha",
                        "plan_fingerprint": "unused",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                HistoricalMaterializationReconciliationError, "SHA-256 mismatch"
            ):
                load_historical_materialization_reconciliation_plan(report_path)

    def test_apply_writes_one_materialization_and_no_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lake_root = Path(temporary_dir)
            candidate = _write_candidate(lake_root, PARTITION_KEY)
            instance = dg.DagsterInstance.ephemeral()
            plan = _plan(candidate)
            report = _apply(instance, plan, lake_root)
            records = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey(ASSET_KEY),
                    asset_partitions=[PARTITION_KEY],
                ),
                limit=1,
            ).records

        self.assertEqual(report.reported_event_count, 1)
        self.assertEqual(report.skipped_existing_materialization_count, 0)
        self.assertEqual(len(records), 1)
        metadata = records[0].asset_materialization.metadata
        self.assertEqual(
            metadata["goldenshare/reconciliation_method"].value,
            RECONCILIATION_METHOD,
        )
        self.assertFalse(metadata["goldenshare/check_events_reported"].value)
        readiness = partition_dataset_readiness_status_from_latest_checks(
            instance,
            (AssetReadinessSpec(dg.AssetKey(ASSET_KEY), ("contract",)),),
            partition_key=PARTITION_KEY,
        )
        self.assertFalse(readiness.ready)
        self.assertTrue(readiness.statuses[0].materialized)
        self.assertEqual(readiness.statuses[0].missing_check_names, ("contract",))
        source = Path(
            "src/orchestrator/defs/bootstrap/historical_materialization_reconciliation.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("AssetCheckEvaluation", source)

    def test_apply_skips_existing_materialization_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lake_root = Path(temporary_dir)
            candidate = _write_candidate(lake_root, PARTITION_KEY)
            instance = dg.DagsterInstance.ephemeral()
            plan = _plan(candidate)
            _apply(instance, plan, lake_root)
            report = _apply(instance, plan, lake_root)

        self.assertEqual(report.reported_event_count, 0)
        self.assertEqual(report.skipped_existing_materialization_count, 1)

    def test_apply_rejects_changed_physical_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lake_root = Path(temporary_dir)
            candidate = _write_candidate(lake_root, PARTITION_KEY)
            _write_parquet(lake_root / candidate.required_paths[0], value=2)
            instance = dg.DagsterInstance.ephemeral()

            with self.assertRaisesRegex(
                HistoricalMaterializationReconciliationError, "fingerprint changed"
            ):
                _apply(instance, _plan(candidate), lake_root)

    def test_apply_rejects_existing_check_and_hot_partition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lake_root = Path(temporary_dir)
            candidate = _write_candidate(lake_root, PARTITION_KEY)
            instance = dg.DagsterInstance.ephemeral()
            plan = _plan(candidate)
            with self.assertRaisesRegex(
                HistoricalMaterializationReconciliationError,
                "check state",
            ):
                _apply(
                    instance,
                    plan,
                    lake_root,
                    check_partitions={ASSET_KEY: {PARTITION_KEY}},
                )
            with self.assertRaisesRegex(
                HistoricalMaterializationReconciliationError, "hot window"
            ):
                _apply(
                    instance,
                    plan,
                    lake_root,
                    hot_partition_keys={ASSET_KEY: {PARTITION_KEY}},
                )
            with self.assertRaisesRegex(
                HistoricalMaterializationReconciliationError,
                "no longer registered",
            ):
                _apply(
                    instance,
                    plan,
                    lake_root,
                    registered_partition_keys={ASSET_KEY: set()},
                )

    def test_apply_can_resume_after_a_partial_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lake_root = Path(temporary_dir)
            first = _write_candidate(lake_root, "2024-01-02")
            second = _write_candidate(lake_root, "2024-01-03")
            plan = _plan(first, second)
            instance = dg.DagsterInstance.ephemeral()
            original_report = instance.report_runless_asset_event
            invocation_count = 0

            def fail_on_second(event):
                nonlocal invocation_count
                invocation_count += 1
                if invocation_count == 2:
                    raise RuntimeError("simulated event storage interruption")
                return original_report(event)

            with patch.object(instance, "report_runless_asset_event", side_effect=fail_on_second):
                with self.assertRaisesRegex(RuntimeError, "simulated event storage"):
                    _apply(instance, plan, lake_root)
            resumed = _apply(instance, plan, lake_root)

        self.assertEqual(resumed.reported_event_count, 1)
        self.assertEqual(resumed.skipped_existing_materialization_count, 1)

    def test_source_contains_no_sql_dml_or_active_definition_registration(self) -> None:
        sources = (
            Path(
                "src/orchestrator/defs/bootstrap/historical_materialization_reconciliation.py"
            ).read_text(encoding="utf-8"),
            Path(
                "src/orchestrator/defs/bootstrap/historical_materialization_reconciliation_cli.py"
            ).read_text(encoding="utf-8"),
        )
        combined = "\n".join(sources).lower()
        for forbidden in (
            "assetcheckevaluation",
            "@dg.asset",
            "@dg.asset_check",
            "@dg.sensor",
            "define_asset_job",
            "runrequest",
            "insert into ",
            "update ",
            "delete from ",
            "truncate ",
            "add_dynamic_partitions",
        ):
            self.assertNotIn(forbidden, combined)


def _apply(
    instance: dg.DagsterInstance,
    plan: ReconciliationPlan,
    lake_root: Path,
    *,
    check_partitions: dict[str, set[str]] | None = None,
    hot_partition_keys: dict[str, set[str]] | None = None,
    registered_partition_keys: dict[str, set[str]] | None = None,
):
    with (
        patch(
            "orchestrator.defs.bootstrap.historical_materialization_reconciliation._assert_no_active_runs"
        ),
        patch(
            "orchestrator.defs.bootstrap.historical_materialization_reconciliation._check_partitions_by_asset",
            return_value=check_partitions or {},
        ),
        patch(
            "orchestrator.defs.bootstrap.historical_materialization_reconciliation._registered_partitions_by_asset",
            return_value=registered_partition_keys
            or {ASSET_KEY: {"2024-01-02", "2024-01-03"}},
        ),
        patch(
            "orchestrator.defs.bootstrap.historical_materialization_reconciliation._partitioned_specs_by_asset",
            return_value={},
        ),
        patch(
            "orchestrator.defs.bootstrap.historical_materialization_reconciliation._hot_partition_keys_by_asset",
            return_value=hot_partition_keys or {ASSET_KEY: set()},
        ),
        patch(
            "orchestrator.defs.bootstrap.historical_materialization_reconciliation._control_counts",
            return_value={
                "asset_check_executions": 0,
                "asset_check_event_logs": 0,
                "runs": 0,
                "run_tags": 0,
                "asset_event_tags": 0,
                "dynamic_partitions": 0,
            },
        ),
        tempfile.TemporaryDirectory() as report_dir,
    ):
        return apply_historical_materialization_reconciliation(
            instance=instance,
            plan=plan,
            lake_root=lake_root,
            families=("B",),
            dry_run=False,
            output_dir=Path(report_dir),
        )


def _write_candidate(lake_root: Path, partition_key: str) -> ReconciliationCandidate:
    relative_path = (
        f"raw/index_daily/trade_date={partition_key}/part-000.parquet"
    )
    path = lake_root / relative_path
    _write_parquet(path, value=1)
    return ReconciliationCandidate(
        asset_key=ASSET_KEY,
        partition_key=partition_key,
        physical_fingerprint=_physical_candidate_fingerprint(
            partition_key=partition_key,
            canonical_uri=str(path),
            files=(path,),
            lake_root=lake_root,
        ),
        canonical_uri=str(path),
        file_count=1,
        required_paths=(relative_path,),
        files=(
            {
                "relative_path": relative_path,
                "size_bytes": path.stat().st_size,
                "mtime_ns": path.stat().st_mtime_ns,
            },
        ),
    )


def _write_parquet(path: Path, *, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(
            f"COPY (SELECT {value}::INTEGER AS value) TO '{path}' (FORMAT PARQUET)"
        )


def _plan(*candidates: ReconciliationCandidate) -> ReconciliationPlan:
    return ReconciliationPlan(
        report_path=Path("/private/tmp/plan.json"),
        manifest_path=Path("/private/tmp/candidates.jsonl"),
        plan_fingerprint=_hash_payload(
            {
                "schema_version": 1,
                "safe_candidates": [candidate.to_dict() for candidate in candidates],
                "active_partitioned": [ASSET_KEY],
            }
        ),
        candidates=tuple(candidates),
        report={},
    )
