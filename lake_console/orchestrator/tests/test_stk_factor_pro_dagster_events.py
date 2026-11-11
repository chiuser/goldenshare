"""Exercise the LLD's event sequence in a real, isolated Dagster event store.

These test-only definitions stand in for file processing, not for Dagster.  No
formal definitions, Lake resource, source credential or production instance is
loaded.  File digests are deliberate literals: this verifies event APIs and
binding. Actual complete-day admission is tested in test_stk_factor_pro_complete_day;
the retired partial-day simulation has been removed.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.event_api import PartitionKeyFilter

TARGET_DAY = "2026-10-21"
HISTORY_DAYS = ("2026-10-19", "2026-10-20")
RAW_KEY = dg.AssetKey("raw_tushare_stk_factor_pro")
SILVER_KEY = dg.AssetKey("silver_stock_factor_pro")
CHECK_NAMES = {
    RAW_KEY: "raw_tushare_stk_factor_pro_file_contract_check",
    SILVER_KEY: "silver_stock_factor_pro_file_contract_check",
}
ASSET_KEYS = (RAW_KEY, SILVER_KEY)
FILE_SHA256 = "a" * 64
CONTRACT_SHA256 = "b" * 64
EXPECTED_CHECK_KEYS = {
    dg.AssetCheckKey(asset_key, CHECK_NAMES[asset_key]) for asset_key in ASSET_KEYS
}


@contextmanager
def _isolated_instance(tmp_path):
    """Use the LLD's test-only unified event store, including when reopening."""
    instance_root = tmp_path / "instance"
    instance_root.mkdir(exist_ok=True)
    overrides = {
        "telemetry": {"enabled": False},
        "event_log_storage": {
            "module": "dagster._core.storage.event_log",
            "class": "ConsolidatedSqliteEventLogStorage",
            "config": {"base_dir": str(tmp_path / "event_log")},
        },
    }
    with dg.DagsterInstance.local_temp(
        str(instance_root), overrides=overrides
    ) as instance:
        storage = instance.event_log_storage
        assert type(storage).__name__ == "ConsolidatedSqliteEventLogStorage"
        assert Path(storage.get_db_path()).is_relative_to(tmp_path)
        assert Path(instance.root_directory).is_relative_to(tmp_path)
        yield instance


def _metadata(asset_key: dg.AssetKey) -> dict[str, object]:
    metadata: dict[str, object] = {
        "goldenshare/file_sha256": FILE_SHA256,
        "goldenshare/contract_content_digest": CONTRACT_SHA256,
        "goldenshare/processing_version": "1",
    }
    if asset_key == SILVER_KEY:
        metadata["goldenshare/raw_sha256"] = FILE_SHA256
    return metadata


def _event_test_definition(
    behavior: str, batch_reads: list[int], calls: list[str], tmp_path
):
    """Follow LLD sections 2.1/4; keep all source/file substitutes explicit."""
    partitions = dg.DynamicPartitionsDefinition(name="cn_a_stock_factor_pro_trade_days")

    @dg.multi_asset(
        name="stk_factor_pro",
        specs=[
            dg.AssetSpec(RAW_KEY, skippable=True),
            dg.AssetSpec(SILVER_KEY, deps=[RAW_KEY], skippable=True),
        ],
        can_subset=True,
        partitions_def=partitions,
        check_specs=[
            dg.AssetCheckSpec(
                name=CHECK_NAMES[asset_key],
                asset=asset_key,
                blocking=True,
                partitions_def=partitions,
            )
            for asset_key in ASSET_KEYS
        ],
        # An explicit business Failure must override even a hypothetical op retry.
        retry_policy=dg.RetryPolicy(max_retries=1),
    )
    def stk_factor_pro(context: dg.AssetExecutionContext) -> Iterator[object]:
        if (
            context.selected_asset_keys != set(ASSET_KEYS)
            or context.selected_asset_check_keys != EXPECTED_CHECK_KEYS
        ):
            raise dg.Failure(
                "必须完整选择两资产及两项检查",
                metadata={
                    "goldenshare/failure_phase": "precheck",
                    "goldenshare/retryable": False,
                    "goldenshare/source_error_code": None,
                },
                allow_retries=False,
            )
        yield dg.AssetObservation(
            asset_key=RAW_KEY,
            partition=context.partition_key,
            metadata={
                "goldenshare/stage": "PRECHECK_NO_DOWNLOAD"
                if behavior == "precheck"
                else "PRECHECK_PASSED"
            },
        )
        # A generator's next step can see the preceding yielded observation.
        observations = context.instance.get_records_for_run(
            context.run.run_id,
            of_type=dg.DagsterEventType.ASSET_OBSERVATION,
            limit=1,
            ascending=False,
        ).records
        assert len(observations) == 1
        assert observations[0].event_log_entry.run_id == context.run.run_id
        assert observations[0].asset_key == RAW_KEY
        assert observations[0].partition_key == TARGET_DAY

        if behavior == "precheck":
            return

        calls.append("download")
        yield dg.AssetObservation(
            asset_key=RAW_KEY,
            partition=TARGET_DAY,
            metadata={"goldenshare/download_started": True},
        )
        for asset_key in ASSET_KEYS:
            calls.append("publish:" + asset_key.to_user_string())
            yield dg.MaterializeResult(
                asset_key=asset_key, metadata=_metadata(asset_key)
            )
            passed = not (behavior == "raw_check_failure" and asset_key == RAW_KEY)
            yield dg.AssetCheckResult(
                asset_key=asset_key,
                check_name=CHECK_NAMES[asset_key],
                passed=passed,
                severity=dg.AssetCheckSeverity.ERROR,
                metadata=_metadata(asset_key),
            )
            if not passed:
                # blocking alone does not halt the remainder of this generator.
                raise dg.Failure("Raw检查失败，停止Silver及历史", allow_retries=False)

        if behavior == "history_failure":
            raise dg.Failure("历史下载失败，日事件保留", allow_retries=False)

        calls.append("history")

        expected_targets = {
            (asset_key, day) for day in HISTORY_DAYS for asset_key in ASSET_KEYS
        }
        for day in HISTORY_DAYS:
            for asset_key in ASSET_KEYS:
                yield dg.AssetMaterialization(
                    asset_key=asset_key,
                    partition=day,
                    metadata=_metadata(asset_key),
                )

        # Exactly the current historical batch, not an unbounded event scan.
        batch_reads.append(len(expected_targets))
        records = context.instance.get_records_for_run(
            context.run.run_id,
            of_type=dg.DagsterEventType.ASSET_MATERIALIZATION,
            limit=len(expected_targets),
            ascending=False,
        ).records
        assert len(records) == len(expected_targets)
        assert {
            (record.asset_key, record.partition_key) for record in records
        } == expected_targets
        for record in records:
            assert record.event_log_entry.run_id == context.run.run_id
            materialization = record.asset_materialization
            assert (
                materialization.metadata["goldenshare/file_sha256"].value == FILE_SHA256
            )
            yield AssetCheckEvaluation(
                asset_key=record.asset_key,
                check_name=CHECK_NAMES[record.asset_key],
                passed=True,
                metadata=_metadata(record.asset_key),
                target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                    storage_id=record.storage_id,
                    run_id=record.event_log_entry.run_id,
                    timestamp=record.timestamp,
                ),
                severity=dg.AssetCheckSeverity.ERROR,
                blocking=True,
                partition=record.partition_key,
            )

    return stk_factor_pro, partitions


def _execute(
    instance, behavior: str, tmp_path, selection=None, *, partition_key=TARGET_DAY
):
    batch_reads: list[int] = []
    calls: list[str] = []
    asset, partitions = _event_test_definition(behavior, batch_reads, calls, tmp_path)
    instance.add_dynamic_partitions(partitions.name, [*HISTORY_DAYS, TARGET_DAY])
    job = dg.define_asset_job(
        "stk_factor_pro_event_test_job",
        selection=selection if selection is not None else dg.AssetSelection.all(),
    )
    definitions = dg.Definitions(assets=[asset], jobs=[job])
    result = definitions.resolve_job_def(job.name).execute_in_process(
        instance=instance,
        partition_key=partition_key,
        raise_on_error=False,
    )
    return result, batch_reads, calls


def _records(instance, run_id: str, event_type):
    return instance.get_records_for_run(
        run_id, of_type=event_type, limit=10, ascending=True
    ).records


def _assert_checks_bound(instance, run_id: str, expected_targets) -> None:
    materializations = _records(
        instance, run_id, dg.DagsterEventType.ASSET_MATERIALIZATION
    )
    by_target = {
        (record.asset_key, record.partition_key): record for record in materializations
    }
    assert set(by_target) == expected_targets
    assert len(materializations) == len(expected_targets)
    checks = _records(instance, run_id, dg.DagsterEventType.ASSET_CHECK_EVALUATION)
    evaluations = [
        record.event_log_entry.dagster_event.event_specific_data for record in checks
    ]
    assert len(evaluations) == len(expected_targets)
    assert {
        (evaluation.asset_key, evaluation.partition) for evaluation in evaluations
    } == expected_targets
    for evaluation in evaluations:
        record = by_target[evaluation.asset_key, evaluation.partition]
        assert evaluation.passed is True
        assert evaluation.blocking is True
        assert evaluation.severity == dg.AssetCheckSeverity.ERROR
        assert evaluation.check_name == CHECK_NAMES[evaluation.asset_key]
        assert (
            evaluation.target_materialization_data
            == AssetCheckEvaluationTargetMaterializationData(
                storage_id=record.storage_id,
                run_id=run_id,
                timestamp=record.timestamp,
            )
        )
        executions = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(evaluation.asset_key, evaluation.check_name),
            limit=1,
            partition_filter=PartitionKeyFilter(key=evaluation.partition),
        )
        assert len(executions) == 1
        assert executions[0].run_id == run_id
        assert executions[0].partition == evaluation.partition
        assert executions[0].status.value == "SUCCEEDED"


def test_day_and_two_history_dates_have_persistent_correctly_bound_checks(
    tmp_path: Path,
):
    with _isolated_instance(tmp_path) as instance:
        result, batch_reads, calls = _execute(instance, "complete", tmp_path)
        assert result.success is True
        assert batch_reads == [4]
        assert calls == [
            "download",
            "publish:raw_tushare_stk_factor_pro",
            "publish:silver_stock_factor_pro",
            "history",
        ]
        run_id = result.run_id
        expected = {
            (asset_key, day)
            for day in (*HISTORY_DAYS, TARGET_DAY)
            for asset_key in ASSET_KEYS
        }
        _assert_checks_bound(instance, run_id, expected)

    # Reopen the same test SQLite store; these are persisted native records.
    with _isolated_instance(tmp_path) as reopened:
        assert reopened.get_run_by_id(run_id).status == dg.DagsterRunStatus.SUCCESS
        _assert_checks_bound(reopened, run_id, expected)


def test_precheck_persists_observation_without_download_or_fake_green_events(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        result, batch_reads, calls = _execute(instance, "precheck", tmp_path)
        assert result.success is True
        assert batch_reads == []
        assert calls == []
        observations = _records(
            instance, result.run_id, dg.DagsterEventType.ASSET_OBSERVATION
        )
        assert len(observations) == 1
        assert observations[0].partition_key == TARGET_DAY
        assert (
            observations[0].asset_observation.metadata["goldenshare/stage"].value
            == "PRECHECK_NO_DOWNLOAD"
        )
        assert (
            _records(instance, result.run_id, dg.DagsterEventType.ASSET_MATERIALIZATION)
            == []
        )
        assert (
            _records(
                instance, result.run_id, dg.DagsterEventType.ASSET_CHECK_EVALUATION
            )
            == []
        )


def test_history_failure_keeps_day_materializations_and_passed_checks(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        result, batch_reads, _calls = _execute(instance, "history_failure", tmp_path)
        assert result.success is False
        assert (
            instance.get_run_by_id(result.run_id).status == dg.DagsterRunStatus.FAILURE
        )
        assert batch_reads == []
        _assert_checks_bound(
            instance,
            result.run_id,
            {(asset_key, TARGET_DAY) for asset_key in ASSET_KEYS},
        )
        run_id = result.run_id
    with _isolated_instance(tmp_path) as reopened:
        assert reopened.get_run_by_id(run_id).status == dg.DagsterRunStatus.FAILURE
        _assert_checks_bound(
            reopened, run_id, {(asset_key, TARGET_DAY) for asset_key in ASSET_KEYS}
        )


def test_failed_raw_check_explicitly_stops_silver_and_history(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        result, batch_reads, calls = _execute(instance, "raw_check_failure", tmp_path)
        assert result.success is False
        assert batch_reads == []
        assert calls == ["download", "publish:raw_tushare_stk_factor_pro"]
        materializations = _records(
            instance, result.run_id, dg.DagsterEventType.ASSET_MATERIALIZATION
        )
        assert [
            (record.asset_key, record.partition_key) for record in materializations
        ] == [(RAW_KEY, TARGET_DAY)]
        checks = _records(
            instance, result.run_id, dg.DagsterEventType.ASSET_CHECK_EVALUATION
        )
        assert len(checks) == 1
        evaluation = checks[0].event_log_entry.dagster_event.event_specific_data
        assert evaluation.asset_key == RAW_KEY
        assert evaluation.partition == TARGET_DAY
        assert evaluation.passed is False
        assert evaluation.blocking is True
        assert (
            evaluation.target_materialization_data.storage_id
            == materializations[0].storage_id
        )


@pytest.mark.parametrize(
    "selection_name",
    ["raw", "silver", "check_only", "missing_raw_check", "missing_silver_check"],
)
def test_partial_selection_rejected_before_download_and_publication(
    tmp_path, selection_name
):
    asset_selection = dg.AssetSelection.assets(*ASSET_KEYS).without_checks()
    raw_check = dg.AssetSelection.checks(
        dg.AssetCheckKey(RAW_KEY, CHECK_NAMES[RAW_KEY])
    )
    silver_check = dg.AssetSelection.checks(
        dg.AssetCheckKey(SILVER_KEY, CHECK_NAMES[SILVER_KEY])
    )
    selections = {
        "raw": dg.AssetSelection.assets(RAW_KEY),
        "silver": dg.AssetSelection.assets(SILVER_KEY),
        "check_only": raw_check,
        "missing_raw_check": asset_selection | silver_check,
        "missing_silver_check": asset_selection | raw_check,
    }
    with _isolated_instance(tmp_path) as instance:
        result, batch_reads, calls = _execute(
            instance,
            "complete",
            tmp_path,
            selections[selection_name],
            # A check-only invocation has no selected asset from which Dagster
            # can infer a shared partition definition. The entrance guard must
            # reject it before trying to read a business partition key.
            partition_key=None if selection_name == "check_only" else TARGET_DAY,
        )
        assert result.success is False
        assert batch_reads == []
        assert calls == []
        assert (
            _records(instance, result.run_id, dg.DagsterEventType.ASSET_MATERIALIZATION)
            == []
        )
        assert (
            _records(
                instance, result.run_id, dg.DagsterEventType.ASSET_CHECK_EVALUATION
            )
            == []
        )
        failure = result.failure_data_for_node("stk_factor_pro")
        assert (
            failure.user_failure_data.metadata["goldenshare/failure_phase"].value
            == "precheck"
        )
        assert (
            failure.user_failure_data.metadata["goldenshare/retryable"].value is False
        )
