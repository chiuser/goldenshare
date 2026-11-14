"""THS success handoff uses native events and the existing 13-column producer."""

import logging
from datetime import date
from decimal import Decimal
from time import perf_counter
from types import SimpleNamespace
from uuid import uuid4

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationPlanned,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.event_api import PartitionKeyFilter
from dagster._core.remote_origin import (
    RegisteredCodeLocationOrigin,
    RemoteRepositoryOrigin,
)
from dagster._core.storage.tags import RUN_KEY_TAG, SENSOR_NAME_TAG
from dagster._daemon.sensor import _get_or_create_sensor_run, fetch_existing_runs

import orchestrator.defs.sensors.moneyflow_ths_sensor as sensors
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_connection,
)
from orchestrator.defs.paths import raw_moneyflow_path, silver_moneyflow_path

from . import test_moneyflow_ths_definitions as support

env = support.env
pytestmark = pytest.mark.usefixtures("isolated_moneyflow_transport")


def test_silver_sensor_is_native_success_only():
    sensor = sensors.silver_moneyflow_ths_update_job_sensor
    assert isinstance(sensor, dg.RunStatusSensorDefinition)
    assert sensor._run_status == dg.DagsterRunStatus.SUCCESS
    assert [job.name for job in sensor._monitored_jobs] == [sensors.RAW_JOB]
    assert sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert sensor.minimum_interval_seconds == 600
    assert sensor.required_resource_keys == {"lake_root"}


def handoff(env, raw_result):
    with dg.build_run_status_sensor_context(
        sensor_name=sensors.silver_moneyflow_ths_update_job_sensor.name,
        dagster_event=raw_result.get_run_success_event(),
        dagster_instance=env.instance,
        dagster_run=raw_result.dagster_run,
        partition_key=raw_result.dagster_run.tags["dagster/partition"],
        resources={"lake_root": env.defs.resources["lake_root"]},
    ) as context:
        return sensors.silver_moneyflow_ths_update_job_sensor(context)


def test_manual_silver_reads_real_raw_without_raw_materialization(env, tmp_path):
    # The original Raw job creates the real 13-column input. A separate owned
    # instance proves Silver does not require that job's event/check history.
    assert support.run(env, sensors.RAW_JOB).success
    raw = raw_moneyflow_path(env.lake, "moneyflow_ths", support.DAY)
    digest = candidate_file_hash(raw)
    root = tmp_path / "silver-only-instance"
    root.mkdir()
    with dg.DagsterInstance.local_temp(str(root), overrides={"telemetry": {"enabled": False}}) as instance:
        instance.add_dynamic_partitions(sensors.PARTITIONS, [support.DAY])
        result = env.defs.resolve_job_def(sensors.SILVER_JOB).execute_in_process(
            instance=instance, partition_key=support.DAY,
        )
        assert result.success
        event = result.get_asset_materialization_events()[0].event_specific_data.materialization
        assert event.metadata["goldenshare/raw_sha256"].value == digest
        assert not instance.fetch_materializations(support.RAW.key, limit=1).records
    with moneyflow_candidate_connection(env.staging) as connection:
        rows = connection.execute(
            "SELECT trade_date,ts_code,name,net_amount,buy_md_amount FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(silver_moneyflow_path(env.lake, "moneyflow_ths", support.DAY))],
        ).fetchall()
    assert rows == [
        (date(2026, 10, 8), "000001.SZ", None, Decimal("-5.1234"), None),
        (date(2026, 10, 8), "000002.SZ", "同名股票", Decimal("-5.1234"), None),
        (date(2026, 10, 8), "600000.SH", "同名股票", Decimal("-5.1234"), None),
    ]
    assert candidate_file_hash(raw) == digest and len(env.source.calls) == 2


def tick(env, cursor=None):
    with dg.partition_loading_context(dynamic_partitions_store=env.instance), dg.build_sensor_context(
        instance=env.instance, cursor=cursor,
        repository_def=env.defs.get_repository_def(),
        resources={"lake_root": env.defs.resources["lake_root"]},
    ) as context:
        return sensors.silver_moneyflow_ths_update_job_sensor.evaluate_tick(context)


def checked_materialization(env, *, passed=True, wrong_target=False, day=support.DAY):
    mat = env.instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=support.SILVER.key, asset_partitions=[day]), limit=1,
    ).records[0]
    evaluation = AssetCheckEvaluation(
        asset_key=support.SILVER.key, partition=day,
        check_name=sensors.MONEYFLOW_THS_SILVER_CHECK, passed=passed, blocking=True,
        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
            storage_id=mat.storage_id + int(wrong_target),
            run_id=mat.run_id, timestamp=mat.timestamp,
        ),
    )
    env.instance.report_dagster_event(
        dg.DagsterEvent(
            event_type_value="ASSET_CHECK_EVALUATION", job_name=sensors.SILVER_JOB,
            event_specific_data=evaluation,
        ), run_id=str(uuid4()),
    )


def test_native_tick_handoff_merged_raw_and_silver_roundtrip(env, record_property):
    assert support.run(env, sensors.RAW_JOB).success
    initial = tick(env)
    assert not initial.run_requests and initial.cursor
    support.set_rows(env, support.sample(amount="12.3400")[1:])
    raw_result = support.run(env, sensors.RAW_JOB)
    raw_event = raw_result.get_asset_materialization_events()[0].event_specific_data.materialization
    assert raw_event.metadata["dagster/row_count"].value == 3
    assert raw_event.metadata["goldenshare/missing_record_codes"].value == []
    assert raw_event.metadata["goldenshare/null_value_codes"].value == ["000001.SZ", "000002.SZ", "600000.SH"]
    calls = len(env.source.calls)
    started = perf_counter()
    requested = tick(env, initial.cursor)
    seconds = perf_counter() - started
    assert len(requested.run_requests) == 1
    request = requested.run_requests[0]
    digest = raw_event.metadata["goldenshare/file_sha256"].value
    assert request.partition_key == support.DAY
    assert request.run_key == f"silver_moneyflow_ths:2026-10-08:{digest}"
    assert request.run_config == {} and request.partition_key in env.instance.get_dynamic_partitions(sensors.PARTITIONS)
    silver_result = support.run(env, sensors.SILVER_JOB, day=request.partition_key)
    assert silver_result.success and len(env.source.calls) == calls == 4
    assert not tick(env, requested.cursor).run_requests
    assert isinstance(handoff(env, raw_result), dg.SkipReason)
    with moneyflow_candidate_connection(env.staging) as connection:
        values = connection.execute(
            "SELECT ts_code,net_amount FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(silver_moneyflow_path(env.lake, "moneyflow_ths", support.DAY))],
        ).fetchall()
    assert values == [("000001.SZ", Decimal("-5.1234")), ("000002.SZ", Decimal("12.3400")), ("600000.SH", Decimal("12.3400"))]
    record_property("ths_stage4_native_handoff", {"seconds": seconds, "source_rows": 2, "final_rows": 3, "source_requests_during_handoff": 0})


@pytest.mark.parametrize("day", [support.DAY, "2026-09-29"])
def test_handoff_uses_raw_partition_without_calendar_or_current_time(env, monkeypatch, day):
    support.set_rows(env, support.sample(day=day))
    result = support.run(env, sensors.RAW_JOB, day=day)

    def forbidden(*args, **kwargs):
        raise AssertionError("success handoff must not enter calendar or old selection")

    monkeypatch.setattr(sensors, "evaluate_moneyflow_update", forbidden)
    monkeypatch.setattr(env.instance, "get_dynamic_partitions", forbidden)
    # An unrelated newer date-level event must not replace this run's digest.
    env.instance.report_runless_asset_event(dg.AssetMaterialization(
        asset_key=support.RAW.key, partition=day,
        metadata={"goldenshare/file_sha256": "0" * 64},
    ))
    request = handoff(env, result)
    assert isinstance(request, dg.RunRequest) and request.partition_key == day
    assert request.run_key == "silver_moneyflow_ths:" + day + ":" + candidate_file_hash(raw_moneyflow_path(env.lake, "moneyflow_ths", day))
    assert len(env.source.calls) == 2


@pytest.mark.parametrize("existing", [False, True])
def test_callback_queries_only_one_date_and_at_most_three_records(env, monkeypatch, existing):
    raw_result = support.run(env, sensors.RAW_JOB)
    if existing:
        assert support.run(env, sensors.SILVER_JOB).success
    # Independent unrelated partitions exercise storage-side filtering.
    for day in ("2026-09-29", "2026-09-30", "2026-10-09"):
        env.instance.report_runless_asset_event(dg.AssetMaterialization(
            asset_key=support.SILVER.key, partition=day,
            metadata={"goldenshare/raw_sha256": "f" * 64},
        ))
    counts = {"raw": 0, "silver": 0, "checks": 0, "returned": 0, "hashes": 0}
    log = env.instance.event_log_storage
    raw_get, silver_get, check_get = log.get_records_for_run, env.instance.fetch_materializations, log.get_asset_check_execution_history
    hashing = sensors.candidate_file_hash

    def raw(*args, **kwargs):
        assert args == (raw_result.run_id,) and kwargs == {"of_type": dg.DagsterEventType.ASSET_MATERIALIZATION, "limit": 1, "ascending": False}
        result = raw_get(*args, **kwargs)
        counts["raw"] += 1
        counts["returned"] += len(result.records)
        return result

    def silver(query, *, limit):
        assert query.asset_key == support.SILVER.key and query.asset_partitions == [support.DAY] and limit == 1
        result = silver_get(query, limit=limit)
        counts["silver"] += 1
        counts["returned"] += len(result.records)
        return result

    def checks(key, **kwargs):
        assert key == dg.AssetCheckKey(support.SILVER.key, sensors.MONEYFLOW_THS_SILVER_CHECK)
        assert kwargs["limit"] == 1 and kwargs["partition_filter"] == PartitionKeyFilter(key=support.DAY)
        assert {s.value for s in kwargs["status"]} == {"SUCCEEDED", "FAILED"}
        result = check_get(key, **kwargs)
        counts["checks"] += 1
        counts["returned"] += len(result)
        return result

    def hashed(path):
        assert path == silver_moneyflow_path(env.lake, "moneyflow_ths", support.DAY)
        counts["hashes"] += 1
        return hashing(path)

    monkeypatch.setattr(log, "get_records_for_run", raw)
    monkeypatch.setattr(env.instance, "fetch_materializations", silver)
    monkeypatch.setattr(log, "get_asset_check_execution_history", checks)
    monkeypatch.setattr(sensors, "candidate_file_hash", hashed)
    result = handoff(env, raw_result)
    assert counts == {"raw": 1, "silver": 1, "checks": int(existing), "returned": 3 if existing else 1, "hashes": int(existing)}
    assert isinstance(result, dg.SkipReason if existing else dg.RunRequest)


@pytest.mark.parametrize("condition", ["failed_check", "wrong_target", "file_changed", "file_missing", "oversize", "missing_hash"])
def test_same_content_bad_silver_requires_manual_recovery(env, condition):
    raw_result = support.run(env, sensors.RAW_JOB)
    assert support.run(env, sensors.SILVER_JOB).success
    path = silver_moneyflow_path(env.lake, "moneyflow_ths", support.DAY)
    if condition in {"failed_check", "wrong_target"}:
        checked_materialization(env, passed=condition != "failed_check", wrong_target=condition == "wrong_target")
    elif condition == "file_changed":
        path.write_bytes(path.read_bytes() + b"changed")
    elif condition == "file_missing":
        path.unlink()
    elif condition == "oversize":
        path.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    else:
        mat = env.instance.fetch_materializations(dg.AssetRecordsFilter(asset_key=support.SILVER.key, asset_partitions=[support.DAY]), limit=1).records[0]
        md = {k: v for k, v in mat.asset_materialization.metadata.items() if k != "goldenshare/file_sha256"}
        env.instance.report_runless_asset_event(dg.AssetMaterialization(asset_key=support.SILVER.key, partition=support.DAY, metadata=md))
        checked_materialization(env)
    result = handoff(env, raw_result)
    assert isinstance(result, dg.SkipReason) and "人工" in result.skip_message
    assert len(env.source.calls) == 2


def test_new_raw_content_can_handoff_after_old_silver_check_failed(env):
    first = support.run(env, sensors.RAW_JOB)
    assert support.run(env, sensors.SILVER_JOB).success
    checked_materialization(env, passed=False)
    assert isinstance(handoff(env, first), dg.SkipReason)
    support.set_rows(env, support.sample(amount="0"))
    changed = support.run(env, sensors.RAW_JOB)
    request = handoff(env, changed)
    assert isinstance(request, dg.RunRequest)
    assert support.run(env, sensors.SILVER_JOB, day=request.partition_key).success
    assert len(env.source.calls) == 4


def test_failed_raw_with_materialization_does_not_trigger_native_sensor(env, monkeypatch):
    import orchestrator.defs.checks.moneyflow_ths as check
    from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError

    initial = tick(env)

    def rejected(*args, **kwargs):
        raise MoneyflowContractError("test_file_contract_failure")

    monkeypatch.setattr(check, "audit_file", rejected)
    result = support.run(env, sensors.RAW_JOB, raise_on_error=False)
    assert not result.success and result.get_asset_materialization_events()
    assert not tick(env, initial.cursor).run_requests


def test_sensor_initialization_does_not_backfill_and_other_job_success_is_ignored(env):
    assert support.run(env, sensors.RAW_JOB).success
    initial = tick(env)
    assert not initial.run_requests
    assert support.run(env, sensors.SILVER_JOB).success
    assert not tick(env, initial.cursor).run_requests


def test_raw_canceled_does_not_trigger_native_sensor(env):
    initial = tick(env)
    run = env.instance.create_run_for_job(
        env.defs.resolve_job_def(sensors.RAW_JOB), tags={"dagster/partition": support.DAY},
    )
    env.instance.report_run_canceled(run)
    assert not tick(env, initial.cursor).run_requests


def test_planned_check_does_not_hide_previous_completed_result(env):
    result = support.run(env, sensors.RAW_JOB)
    assert support.run(env, sensors.SILVER_JOB).success
    plan = AssetCheckEvaluationPlanned(
        asset_key=support.SILVER.key, check_name=sensors.MONEYFLOW_THS_SILVER_CHECK,
        partitions_subset=support.SILVER.partitions_def.subset_with_partition_keys([support.DAY]),
    )
    env.instance.report_dagster_event(dg.DagsterEvent(
        event_type_value="ASSET_CHECK_EVALUATION_PLANNED", job_name=sensors.SILVER_JOB,
        event_specific_data=plan,
    ), run_id=str(uuid4()))
    outcome = handoff(env, result)
    assert isinstance(outcome, dg.SkipReason) and "已成功" in outcome.skip_message
    checked_materialization(env, passed=False)
    outcome = handoff(env, result)
    assert isinstance(outcome, dg.SkipReason) and "人工" in outcome.skip_message


def test_legacy_silver_without_consumed_digest_is_not_claimed_complete(env):
    result = support.run(env, sensors.RAW_JOB)
    env.instance.report_runless_asset_event(dg.AssetMaterialization(
        asset_key=support.SILVER.key, partition=support.DAY,
    ))
    assert isinstance(handoff(env, result), dg.RunRequest)


@pytest.mark.parametrize("status", [
    dg.DagsterRunStatus.SUCCESS, dg.DagsterRunStatus.FAILURE, dg.DagsterRunStatus.CANCELED,
    dg.DagsterRunStatus.QUEUED, dg.DagsterRunStatus.STARTED, dg.DagsterRunStatus.NOT_STARTED,
])
def test_native_submission_reuses_original_key_and_legacy_sensor_records(env, status):
    # A descriptor substitutes the remote code server; native storage and both
    # installed Dagster deduplication functions are real. No run is launched.
    origin = RemoteRepositoryOrigin(RegisteredCodeLocationOrigin("isolated-ths"), "repo")
    name = sensors.silver_moneyflow_ths_update_job_sensor.name
    key = "silver_moneyflow_ths:2026-10-08:" + "a" * 64
    request = dg.RunRequest(run_key=key, partition_key=support.DAY)

    @dg.sensor(name=name, job=env.defs.resolve_job_def(sensors.SILVER_JOB))
    def old_sensor():
        return dg.SkipReason("original polling definition")

    saved = env.instance.create_run_for_job(
        env.defs.resolve_job_def(sensors.SILVER_JOB), status=status,
        tags={RUN_KEY_TAG: key, SENSOR_NAME_TAG: old_sensor.name, "dagster/partition": support.DAY},
        remote_job_origin=origin.get_job_origin(sensors.SILVER_JOB),
    )
    remote = SimpleNamespace(name=name, get_remote_origin=lambda: origin.get_instigator_origin(name))
    count = len(env.instance.get_runs())
    matched = fetch_existing_runs(env.instance, remote, [request])
    assert matched[key].run_id == saved.run_id
    result = _get_or_create_sensor_run(
        logger=logging.getLogger(__name__), instance=env.instance, code_location=None,
        remote_sensor=remote, remote_job=None, run_id=str(uuid4()),
        run_request=request, target_data=None, existing_runs_by_key=matched,
    )
    actual = result if status == dg.DagsterRunStatus.NOT_STARTED else result.existing_run
    assert actual.run_id == saved.run_id and len(env.instance.get_runs()) == count
    other = SimpleNamespace(name="other_sensor", get_remote_origin=remote.get_remote_origin)
    assert fetch_existing_runs(env.instance, other, [request]) == {}
    other_origin = RemoteRepositoryOrigin(RegisteredCodeLocationOrigin("other-location"), "repo")
    other = SimpleNamespace(name=name, get_remote_origin=lambda: other_origin.get_instigator_origin(name))
    assert fetch_existing_runs(env.instance, other, [request]) == {}
    assert fetch_existing_runs(env.instance, remote, [dg.RunRequest(run_key=key.replace("a" * 64, "b" * 64))]) == {}
    assert fetch_existing_runs(env.instance, remote, [dg.RunRequest(run_key=key.replace("2026-10-08", "2026-09-29"))]) == {}


def test_new_raw_run_with_same_content_cannot_restart_failed_silver(env):
    first = support.run(env, sensors.RAW_JOB)
    requested = handoff(env, first)
    name = sensors.silver_moneyflow_ths_update_job_sensor.name
    saved = env.instance.create_run_for_job(
        env.defs.resolve_job_def(sensors.SILVER_JOB), status=dg.DagsterRunStatus.FAILURE,
        tags={RUN_KEY_TAG: requested.run_key, SENSOR_NAME_TAG: name, "dagster/partition": support.DAY},
    )
    support.set_rows(env, support.sample())
    second = support.run(env, sensors.RAW_JOB)
    assert second.run_id != first.run_id
    replay = handoff(env, second)
    assert replay.run_key == requested.run_key
    remote = SimpleNamespace(name=name)
    matches = fetch_existing_runs(env.instance, remote, [replay])
    assert matches[replay.run_key].run_id == saved.run_id
    before = len(env.instance.get_runs())
    outcome = _get_or_create_sensor_run(
        logger=logging.getLogger(__name__), instance=env.instance, code_location=None,
        remote_sensor=remote, remote_job=None, run_id=str(uuid4()), run_request=replay,
        target_data=None, existing_runs_by_key=matches,
    )
    assert outcome.existing_run.run_id == saved.run_id
    assert len(env.instance.get_runs()) == before and len(env.source.calls) == 4


def test_same_content_materialization_without_check_requires_manual_recovery(env):
    from orchestrator.defs.io.moneyflow_ths_silver_update import (
        update_moneyflow_ths_silver,
    )

    raw_result = support.run(env, sensors.RAW_JOB)
    output = update_moneyflow_ths_silver(
        lake_root=env.lake, staging_root=env.staging, operation_id="file-only", trade_date=support.DAY,
    )
    env.instance.report_runless_asset_event(dg.AssetMaterialization(
        asset_key=support.SILVER.key, partition=support.DAY,
        metadata={"goldenshare/raw_sha256": output["raw_sha256"], "goldenshare/file_sha256": output["file_sha256"]},
    ))
    result = handoff(env, raw_result)
    assert isinstance(result, dg.SkipReason) and "缺少检查" in result.skip_message
