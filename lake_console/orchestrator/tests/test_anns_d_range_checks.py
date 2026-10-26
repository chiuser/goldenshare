"""Native check event regressions; only the file evaluator is replaced here.

The two real check definitions and Dagster 1.13.26 event storage remain active.
Real producer/file-boundary cases live in test_anns_d_check_recovery.py.
"""

import dagster as dg
import pytest
from dagster._core.storage.tags import (
    ASSET_PARTITION_RANGE_END_TAG,
    ASSET_PARTITION_RANGE_START_TAG,
    PARTITION_NAME_TAG,
)

from orchestrator.defs.anns_d_contract import ANNOUNCEMENT_ASSET, ANNOUNCEMENT_CHECKS
from orchestrator.defs.anns_d_partitions import anns_d_natural_days
from orchestrator.defs.checks import anns_d_checks as checks_module
from orchestrator.defs.resources import LakeRootResource

DAYS = (
    "2023-06-01",
    "2023-06-02",
    "2023-06-03",
    "2023-06-04",
    "2023-06-05",
    "2023-06-06",
    "2023-06-07",
    "2023-06-08",
    "2023-06-09",
)


def _definitions(tmp_path, monkeypatch, evaluator):
    root, staging = tmp_path / "lake", tmp_path / "staging"
    root.mkdir()
    staging.mkdir()
    monkeypatch.setattr(checks_module, "DEFAULT_LAKE_ROOT", str(root))
    monkeypatch.setattr(checks_module, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    monkeypatch.setattr(checks_module, "evaluate_announcement_check", evaluator)

    @dg.asset(name=ANNOUNCEMENT_ASSET, partitions_def=anns_d_natural_days)
    def producer(context):
        # This independent literal metadata proves the wrapper binds each date's
        # materialization, rather than reusing the last date or an unpartitioned one.
        for day in context.partition_keys:
            context.add_asset_metadata({"fixture_day": day}, partition_key=day)
        return dg.MaterializeResult()

    checks = [
        checks_module.raw_tushare_anns_d_file_contract_check,
        checks_module.raw_tushare_anns_d_delivery_reconciliation_check,
    ]
    return dg.Definitions(
        assets=[producer],
        asset_checks=checks,
        jobs=[
            dg.define_asset_job("anns_range_fixture"),
            dg.define_asset_job(
                "anns_one_check_fixture",
                selection=dg.AssetSelection.checks(
                    dg.AssetCheckKey(producer.key, ANNOUNCEMENT_CHECKS[0])
                ),
            ),
        ],
        resources={"lake_root": LakeRootResource(root_path=str(root))},
    )


@pytest.mark.parametrize("first_delivery_fails", [False, True])
def test_range_checks_emit_and_persist_all_daily_targets(
    tmp_path, monkeypatch, first_delivery_fails
):
    seen = []

    def evaluator(context, lake_root, *, day, reconciliation, **kwargs):
        seen.append((day, reconciliation))
        return dg.AssetCheckResult(
            passed=not (first_delivery_fails and reconciliation and day == DAYS[0]),
            metadata={"evaluated_day": day},
        )

    defs = _definitions(tmp_path, monkeypatch, evaluator)
    with dg.DagsterInstance.ephemeral() as instance:
        result = defs.resolve_job_def("anns_range_fixture").execute_in_process(
            instance=instance,
            tags={
                ASSET_PARTITION_RANGE_START_TAG: DAYS[0],
                ASSET_PARTITION_RANGE_END_TAG: DAYS[-1],
            },
            raise_on_error=False,
        )
        assert result.success is (not first_delivery_fails)
        assert len(seen) == 18
        assert sorted(day for day, reconciliation in seen if reconciliation) == list(
            DAYS
        )
        evaluations = result.get_asset_check_evaluations()
        assert len(evaluations) == 18
        assert not any(event.is_step_skipped for event in result.all_events)
        for name in ANNOUNCEMENT_CHECKS:
            records = instance.event_log_storage.get_asset_check_execution_history(
                dg.AssetCheckKey(dg.AssetKey(ANNOUNCEMENT_ASSET), name), limit=30
            )
            assert len(records) == 9
            assert sorted(record.partition for record in records) == list(DAYS)
            for record in records:
                day = record.partition
                mat = instance.fetch_materializations(
                    dg.AssetRecordsFilter(
                        asset_key=dg.AssetKey(ANNOUNCEMENT_ASSET),
                        asset_partitions=[day],
                    ),
                    limit=1,
                ).records[0]
                evaluation = record.evaluation
                assert evaluation.partition == day
                assert (
                    evaluation.target_materialization_data.storage_id == mat.storage_id
                )
                assert evaluation.target_materialization_data.run_id == result.run_id
                assert mat.asset_materialization.metadata["fixture_day"].value == day


def test_single_check_only_uses_latest_daily_target_without_materializing(
    tmp_path, monkeypatch
):
    def evaluator(context, lake_root, *, day, reconciliation, **kwargs):
        return dg.AssetCheckResult(passed=True)

    defs = _definitions(tmp_path, monkeypatch, evaluator)
    with dg.DagsterInstance.ephemeral() as instance:
        original = defs.resolve_job_def("anns_range_fixture").execute_in_process(
            instance=instance,
            tags={
                ASSET_PARTITION_RANGE_START_TAG: DAYS[0],
                ASSET_PARTITION_RANGE_END_TAG: DAYS[-1],
            },
        )
        result = defs.resolve_job_def("anns_one_check_fixture").execute_in_process(
            instance=instance, tags={PARTITION_NAME_TAG: DAYS[0]}, raise_on_error=False
        )
        assert result.success
        assert not result.get_asset_materialization_events()
        evaluations = result.get_asset_check_evaluations()
        assert len(evaluations) == 1
        assert evaluations[0].partition == DAYS[0]
        assert evaluations[0].check_name == ANNOUNCEMENT_CHECKS[0]
        assert evaluations[0].target_materialization_data.run_id == original.run_id
