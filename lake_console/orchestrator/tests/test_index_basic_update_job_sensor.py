import json
import logging
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import dagster as dg
import pytest
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)
from dagster._core.storage.tags import RUN_KEY_TAG, SENSOR_NAME_TAG

from orchestrator.definitions import defs
from orchestrator.defs.io.index_basic_publication import (
    INDEX_BASIC_COVERAGE_METADATA_KEY,
)
from orchestrator.defs.run_contracts.metadata import READY_FOR_TRADE_DATE_METADATA_KEY
from orchestrator.defs.sensors import index_basic_update_job_sensor as daily

_DATE = "2026-11-20"
_RUN_KEY = "index_basic_update_job:2026-11-20"


def _run(
    status=dg.DagsterRunStatus.SUCCESS,
    *,
    run_id="batch",
    root=None,
    job="index_basic_update_job",
    end=103,
):
    return SimpleNamespace(
        dagster_run=SimpleNamespace(
            status=status, run_id=run_id, root_run_id=root, job_name=job
        ),
        end_time=end,
    )


@pytest.fixture
def sensor(monkeypatch):
    monkeypatch.setattr(daily, "_lake_available", lambda: True)
    event_log = Mock()
    instance = Mock(spec=dg.DagsterInstance, event_log_storage=event_log)
    instance.has_dynamic_partition.return_value = True
    context = SimpleNamespace(instance=instance, log=logging.getLogger(__name__))
    raw = {
        "passed": True,
        "batch_id": "batch",
        "sha256": "raw-digest",
        "fetched_at": f"{_DATE}T18:01:00+08:00",
    }
    silver = {"passed": True, "batch_id": "batch", "raw_sha256": "raw-digest"}
    layers = {}
    for offset, (asset, coverage) in enumerate(
        ((daily._RAW, raw), (daily._SILVER, silver))
    ):
        metadata = {INDEX_BASIC_COVERAGE_METADATA_KEY: dg.MetadataValue.json(coverage)}
        if asset == daily._SILVER:
            metadata[READY_FOR_TRADE_DATE_METADATA_KEY] = dg.MetadataValue.text(_DATE)
        layers[asset] = SimpleNamespace(
            asset_materialization=SimpleNamespace(metadata=metadata),
            run_id="batch",
            storage_id=1000 + offset,
            timestamp=100 + offset,
        )
    instance.get_asset_records.return_value = [
        SimpleNamespace(
            asset_entry=SimpleNamespace(
                asset_key=asset, last_materialization_record=record
            )
        )
        for asset, record in layers.items()
    ]
    checks = {}
    for key in daily._CHECK_KEYS:
        output = layers[key.asset_key]
        coverage = {
            "passed": True,
            "batch_id": "batch",
            "materialization_id": output.storage_id,
        }
        checks[key] = SimpleNamespace(
            status=AssetCheckExecutionRecordStatus.SUCCEEDED,
            run_id="batch",
            evaluation=SimpleNamespace(
                passed=True,
                blocking=True,
                asset_key=key.asset_key,
                check_name=key.name,
                partition=None,
                target_materialization_data=SimpleNamespace(
                    storage_id=output.storage_id, run_id="batch"
                ),
                metadata={
                    INDEX_BASIC_COVERAGE_METADATA_KEY: dg.MetadataValue.json(coverage)
                },
            ),
        )
    event_log.get_latest_asset_check_execution_by_key.return_value = checks
    instance.get_run_records.side_effect = [[], [], [_run()]]
    return context, instance, layers, checks


def _evaluate(context, at="18:05:00+08:00"):
    return daily.evaluate_index_basic_update(
        context, datetime.fromisoformat(f"{_DATE}T{at}")
    )


def _reason(result):
    return json.loads(result.cursor)["details"]["reason_code"]


@pytest.mark.parametrize("at", ["17:59:59+08:00", "00:00:00+08:00"])
def test_outside_window_reads_no_records(sensor, at):
    context, instance, _, _ = sensor
    result = _evaluate(context, at)
    assert _reason(result) == "outside_window"
    assert not result.run_requests
    assert not instance.method_calls


def test_unmounted_lake_reads_no_records(sensor, monkeypatch):
    context, instance, _, _ = sensor
    monkeypatch.setattr(daily, "_lake_available", lambda: False)
    assert _reason(_evaluate(context)) == "lake_unavailable"
    assert not instance.method_calls


def test_unregistered_day_skips_without_looking_for_previous_days(sensor):
    context, instance, _, _ = sensor
    instance.has_dynamic_partition.return_value = False
    assert _reason(_evaluate(context, "18:00:00+08:00")) == "date_not_registered"
    instance.has_dynamic_partition.assert_called_once_with(
        "cn_a_index_trade_days", _DATE
    )
    instance.get_run_records.assert_not_called()


@pytest.mark.parametrize(
    "status",
    [
        dg.DagsterRunStatus.QUEUED,
        dg.DagsterRunStatus.SUCCESS,
        dg.DagsterRunStatus.FAILURE,
        dg.DagsterRunStatus.CANCELED,
    ],
)
def test_one_automatic_request_per_day_even_after_failure(sensor, status):
    context, instance, _, _ = sensor
    instance.get_run_records.side_effect = [[_run(status)]]
    result = _evaluate(context)
    assert _reason(result) == (
        "attempt_failed"
        if status in (dg.DagsterRunStatus.FAILURE, dg.DagsterRunStatus.CANCELED)
        else "already_submitted"
    )
    assert not result.run_requests
    instance.get_run_records.assert_called_once()
    query = instance.get_run_records.call_args.kwargs
    assert query["limit"] == 1
    assert query["filters"].job_name == "index_basic_update_job"
    assert query["filters"].tags == {
        SENSOR_NAME_TAG: "index_basic_update_job_sensor",
        RUN_KEY_TAG: _RUN_KEY,
    }
    instance.get_asset_records.assert_not_called()


def test_waits_for_active_manual_job(sensor):
    context, instance, _, _ = sensor
    instance.get_run_records.side_effect = [[], [_run(dg.DagsterRunStatus.QUEUED)]]
    assert _reason(_evaluate(context)) == "job_active"
    assert (
        dg.DagsterRunStatus.QUEUED
        in instance.get_run_records.call_args.kwargs["filters"].statuses
    )
    instance.get_asset_records.assert_not_called()


def test_verified_1710_first_refresh_does_not_satisfy_evening_window(sensor):
    context, instance, layers, _ = sensor
    raw = (
        layers[daily._RAW]
        .asset_materialization.metadata[INDEX_BASIC_COVERAGE_METADATA_KEY]
        .value
    )
    raw["fetched_at"] = "2026-11-20T17:10:04.781710+08:00"
    result = _evaluate(context, "10:00:00+00:00")
    assert _reason(result) == "request_run"
    (request,) = result.run_requests
    assert request.run_key == _RUN_KEY and request.partition_key is None
    assert request.run_config == {
        "ops": {"raw_tushare_index_basic": {"config": {"scheduled_trade_date": _DATE}}}
    }
    instance.has_dynamic_partition.assert_called_once_with(
        "cn_a_index_trade_days", _DATE
    )
    instance.event_log_storage.get_latest_asset_check_execution_by_key.assert_not_called()


def test_evening_manual_delivery_reuses_six_checks_with_six_queries(sensor):
    context, instance, _, _ = sensor
    result = _evaluate(context)
    assert _reason(result) == "already_delivered"
    assert not result.run_requests
    instance.has_dynamic_partition.assert_called_once()
    instance.get_asset_records.assert_called_once_with((daily._RAW, daily._SILVER))
    instance.event_log_storage.get_latest_asset_check_execution_by_key.assert_called_once_with(
        daily._CHECK_KEYS
    )
    assert len(daily._CHECK_KEYS) == 6
    assert instance.get_run_records.call_count == 3
    assert instance.get_run_records.call_args.kwargs["limit"] == 1
    assert instance.get_run_records.call_args.kwargs["filters"].run_ids == ["batch"]


def test_successful_reexecution_can_complete_the_same_batch(sensor):
    context, instance, layers, checks = sensor
    layers[daily._SILVER].run_id = "retry"
    for key, check in checks.items():
        if key.asset_key == daily._SILVER:
            check.run_id = "retry"
            check.evaluation.target_materialization_data.run_id = "retry"
    instance.get_run_records.side_effect = [
        [],
        [],
        [
            _run(dg.DagsterRunStatus.FAILURE),
            _run(run_id="retry", root="batch"),
        ],
    ]
    assert _reason(_evaluate(context)) == "already_delivered"
    assert instance.get_run_records.call_args.kwargs["limit"] == 2


def test_reexecution_queries_at_most_eight_runs_by_id(sensor):
    context, instance, layers, checks = sensor
    layers[daily._SILVER].run_id = "silver_retry"
    runs = [
        _run(dg.DagsterRunStatus.FAILURE),
        _run(run_id="silver_retry", root="batch"),
    ]
    for offset, (key, check) in enumerate(checks.items()):
        check.run_id = f"check_retry_{offset}"
        check.evaluation.target_materialization_data.run_id = layers[
            key.asset_key
        ].run_id
        runs.append(_run(run_id=check.run_id, root="batch"))
    instance.get_run_records.side_effect = [[], [], runs]
    assert _reason(_evaluate(context)) == "already_delivered"
    query = instance.get_run_records.call_args.kwargs
    assert query["limit"] == 8
    assert set(query["filters"].run_ids) == {row.dagster_run.run_id for row in runs}


@pytest.mark.parametrize(
    "problem",
    [
        "raw_only",
        "wrong_batch",
        "wrong_digest",
        "wrong_day",
        "wrong_check_target",
        "missing_coverage",
        "failed_job",
        "wrong_root",
        "other_job",
        "success_before_silver",
    ],
)
def test_incomplete_or_unrelated_evidence_cannot_prove_delivery(sensor, problem):
    context, instance, layers, checks = sensor
    silver = layers[daily._SILVER].asset_materialization.metadata
    if problem == "raw_only":
        instance.get_asset_records.return_value.pop()
    if problem in {"wrong_batch", "wrong_digest"}:
        key = "batch_id" if problem == "wrong_batch" else "raw_sha256"
        silver[INDEX_BASIC_COVERAGE_METADATA_KEY].value[key] = "other"
    if problem == "wrong_day":
        silver[READY_FOR_TRADE_DATE_METADATA_KEY] = dg.MetadataValue.text("2026-11-19")
    if problem == "wrong_check_target":
        checks[
            daily._CHECK_KEYS[0]
        ].evaluation.target_materialization_data.storage_id += 1
    if problem == "missing_coverage":
        key = next(iter(daily._COVERAGE_CHECK_KEYS))
        checks[key].evaluation.metadata = {}
    if problem == "failed_job":
        instance.get_run_records.side_effect = [
            [],
            [],
            [_run(dg.DagsterRunStatus.FAILURE)],
        ]
    if problem == "wrong_root":
        instance.get_run_records.side_effect = [[], [], [_run(root="other")]]
    if problem == "other_job":
        instance.get_run_records.side_effect = [[], [], [_run(job="__ASSET_JOB")]]
    if problem == "success_before_silver":
        instance.get_run_records.side_effect = [[], [], [_run(end=100)]]
    assert _reason(_evaluate(context)) == "request_run"


def test_dagster_query_error_or_oversized_result_cannot_submit(sensor):
    context, instance, _, _ = sensor
    instance.get_run_records.side_effect = [[_run(), _run()]]
    assert _reason(_evaluate(context)) == "query_budget_exceeded"
    instance.get_run_records.side_effect = OSError("storage unavailable")
    assert _reason(_evaluate(context)) == "evidence_unavailable"


def test_definition_is_stopped_and_tagged_for_both_layers():
    definition = (
        defs().get_repository_def().get_sensor_def("index_basic_update_job_sensor")
    )
    assert definition.job_name == "index_basic_update_job"
    assert definition.default_status == dg.DefaultSensorStatus.STOPPED
    assert definition.minimum_interval_seconds == 600
    assert definition.tags == {
        "goldenshare/sensor_domain": "index_topic",
        "goldenshare/sensor_target_layer": "raw_silver",
        "goldenshare/sensor_role": "asset_update",
    }
