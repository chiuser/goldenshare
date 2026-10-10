"""Real partitioned jobs and isolated storage; sensors never contact the source."""

import logging
from datetime import datetime
from types import SimpleNamespace

import dagster as dg
import pytest
from dagster._core.storage.tags import RUN_KEY_TAG

import orchestrator.defs.sensors.moneyflow_mkt_dc_sensor as sensors
import orchestrator.defs.sensors.moneyflow_update_selection as selection
from orchestrator.defs.asset_guards.moneyflow_mkt_dc_readiness import (
    batch_market_moneyflow_readiness,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.paths import raw_moneyflow_path, silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE

from . import test_moneyflow_mkt_dc_definitions as support
from .test_moneyflow_mkt_dc_definitions import row, run


@pytest.fixture
def env(tmp_path, monkeypatch):
    factory = logging.getLogRecordFactory()

    def dated_record(*args, **kwargs):
        record = factory(*args, **kwargs)
        # Native job events use logging.Record.created; match the sensor clock.
        record.created = NOW.timestamp()
        record.msecs = 0
        return record

    logging.setLogRecordFactory(dated_record)
    try:
        yield from support.env.__wrapped__(tmp_path, monkeypatch)
    finally:
        logging.setLogRecordFactory(factory)


DAY = "2026-10-09"
NOW = datetime(2026, 10, 9, 22, 1, tzinfo=CN_A_SENSOR_TIMEZONE)


def context(env, dates=(DAY,), cursor=None):
    calendar = silver_trade_calendar_path(env.lake)
    calendar.parent.mkdir(parents=True, exist_ok=True)
    settings = DuckDBConnectionSettings(
        temp_directory=env.staging, memory_limit="512MB", threads=1
    )
    with connect_configured_duckdb(settings, temp_policy="existing_no_spill") as db:
        db.execute(
            "CREATE TABLE calendar(exchange VARCHAR, trade_date DATE, is_open BOOLEAN)"
        )
        for day in dates:
            db.execute("INSERT INTO calendar VALUES ('SSE', ?, true)", [day])
        db.execute("COPY calendar TO ? (FORMAT PARQUET)", [str(calendar)])
    env.instance.add_dynamic_partitions(sensors.PARTITIONS, list(dates))
    return SimpleNamespace(
        instance=env.instance,
        cursor=cursor,
        resources=SimpleNamespace(
            lake_root=env.defs.resources["lake_root"],
            duckdb=SimpleNamespace(
                connect=lambda: connect_configured_duckdb(
                    settings, temp_policy="existing_no_spill"
                )
            ),
        ),
    )


def decision(result):
    return load_sensor_cursor(result.cursor)["details"]["reason_code"]


def publish(env, *, amount="-123.4567", silver=True):
    env.source.responses = iter(
        [[row(amount=amount, day=DAY)], [row(amount=amount, day=DAY)]]
    )
    assert run(env, sensors.RAW_JOB, day=DAY).success
    if silver:
        assert run(env, sensors.SILVER_JOB, day=DAY).success


def test_three_sensors_stopped_and_source_absent():
    for name in (
        "cn_a_moneyflow_mkt_dc_trade_day_sensor",
        sensors.RAW_JOB + "_sensor",
        sensors.SILVER_JOB + "_sensor",
    ):
        sensor = getattr(sensors, name)
        assert sensor.default_status == dg.DefaultSensorStatus.STOPPED
        assert sensor.minimum_interval_seconds == 600
        assert "tushare" not in sensor.required_resource_keys


def test_before_22_reads_nothing():
    ctx = SimpleNamespace(cursor=None)
    for silver in (False, True):
        result = sensors.evaluate_market_moneyflow(
            ctx, NOW.replace(hour=21), silver=silver
        )
        assert decision(result) == "before_window" and not result.run_requests


def test_missing_date_and_historical_cutoff(env):
    ctx = context(env, dates=("2026-09-30", DAY))
    env.instance.delete_dynamic_partition(sensors.PARTITIONS, DAY)
    result = sensors.evaluate_market_moneyflow(ctx, NOW)
    assert decision(result) == "missing_partition"
    assert load_sensor_cursor(result.cursor)["target_date"] == DAY
    assert not env.source.calls


def test_request_replay_does_not_burn_attempt_and_source_never_called(env):
    ctx = context(env)
    first = sensors.evaluate_market_moneyflow(ctx, NOW)
    ctx.cursor = first.cursor
    second = sensors.evaluate_market_moneyflow(ctx, NOW)
    assert first.run_requests[0].run_key == second.run_requests[0].run_key
    assert first.run_requests[0].partition_key == DAY
    assert len(first.run_requests) == 1 and not env.source.calls
    assert len(second.cursor.encode()) < 2048


def test_real_delivery_current_check_file_and_safe_upstream_revision(env):
    ctx = context(env)
    publish(env)
    ready = batch_market_moneyflow_readiness(env.instance, env.lake, [DAY])
    assert ready["raw"][DAY].ready and ready["silver"][DAY].ready
    assert (
        decision(sensors.evaluate_market_moneyflow(ctx, NOW, silver=True))
        == "all_ready"
    )
    publish(env, amount="1.0000", silver=False)
    result = sensors.evaluate_market_moneyflow(ctx, NOW, silver=True)
    assert decision(result) == "request_run"
    assert ready["raw"][DAY].record.storage_id not in [
        result.run_requests[0].run_config
    ]
    assert len(result.run_requests) == 1
    assert (
        batch_market_moneyflow_readiness(env.instance, env.lake, [DAY])["silver"][
            DAY
        ].reason
        == "upstream_revision"
    )
    path = raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    path.write_bytes(path.read_bytes() + b"changed")
    assert decision(sensors.evaluate_market_moneyflow(ctx, NOW)) == "file_changed"


def test_raw_ready_today_no_repeat_and_active_job_blocks(env):
    ctx = context(env)
    publish(env, silver=False)
    record = batch_market_moneyflow_readiness(env.instance, env.lake, [DAY])["raw"][
        DAY
    ].record
    assert (
        datetime.fromtimestamp(record.timestamp, CN_A_SENSOR_TIMEZONE).date()
        == NOW.date()
    )
    assert decision(sensors.evaluate_market_moneyflow(ctx, NOW)) == "all_ready"
    env.instance.create_run_for_job(
        env.defs.resolve_job_def(sensors.SILVER_JOB), tags={"dagster/partition": DAY}
    )
    assert decision(sensors.evaluate_market_moneyflow(ctx, NOW)) == "active_run"


def test_real_transient_failure_metadata_allows_retry_but_fatal_does_not(env):
    ctx = context(env)
    env.source.responses = iter([[], []])
    failed = run(env, sensors.RAW_JOB, day=DAY, raise_on_error=False)
    assert not failed.success
    failure_run = env.instance.get_run_by_id(failed.run_id)
    assert selection.moneyflow_failure_retryable(env.instance, failure_run)
    assert decision(sensors.evaluate_market_moneyflow(ctx, NOW)) == "request_run"
    env.source.responses = iter([[row(amount="0.123456789", day=DAY)]])
    failed = run(env, sensors.RAW_JOB, day=DAY, raise_on_error=False)
    assert not failed.success
    assert not selection.moneyflow_failure_retryable(
        env.instance, env.instance.get_run_by_id(failed.run_id)
    )
    assert (
        decision(sensors.evaluate_market_moneyflow(ctx, NOW)) == "non_retryable_failure"
    )


def test_six_persistent_keys_limit_survives_cursor_loss(env, monkeypatch):
    ctx = context(env)
    monkeypatch.setattr(selection, "moneyflow_failure_retryable", lambda *_: True)
    for attempt in range(1, 7):
        result = sensors.evaluate_market_moneyflow(ctx, NOW)
        request = result.run_requests[0]
        created = env.instance.create_run_for_job(
            env.defs.resolve_job_def(sensors.RAW_JOB),
            tags={"dagster/partition": DAY, RUN_KEY_TAG: request.run_key},
        )
        env.instance.report_run_failed(created)
        ctx.cursor = None  # Prove the cursor is not the retry counter authority.
    assert (
        attempt == 6
        and decision(sensors.evaluate_market_moneyflow(ctx, NOW)) == "attempt_limit"
    )


@pytest.mark.parametrize("cursor", ["broken", "x" * 8193])
def test_invalid_cursor_fails_closed(cursor):
    with pytest.raises(MoneyflowContractError):
        sensors.evaluate_market_moneyflow(SimpleNamespace(cursor=cursor), NOW)


def test_blocking_check_wrong_identity_is_not_green(env):
    ctx = context(env)
    publish(env)
    env.instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key="raw_tushare_moneyflow_mkt_dc",
            partition=DAY,
            metadata={
                "goldenshare/file_sha256": batch_market_moneyflow_readiness(
                    env.instance, env.lake, [DAY]
                )["raw"][DAY].metadata["file_sha256"]
            },
        )
    )
    assert (
        decision(sensors.evaluate_market_moneyflow(ctx, NOW)) == "check_failed_or_stale"
    )
    assert not sensors.evaluate_market_moneyflow(ctx, NOW, silver=True).run_requests


def test_registration_today_first_holiday_and_time_gate(env, monkeypatch):
    import orchestrator.defs.sensors.cn_a_trade_day_sensor as registration

    simple = context(env, dates=("2026-09-28", "2026-10-08", DAY))
    ctx = dg.build_sensor_context(
        instance=env.instance,
        resources={
            "lake_root": simple.resources.lake_root,
            "duckdb": dg.ResourceDefinition.hardcoded_resource(simple.resources.duckdb),
        },
    )
    env.instance.delete_dynamic_partition(sensors.PARTITIONS, "2026-09-28")
    env.instance.delete_dynamic_partition(sensors.PARTITIONS, DAY)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(registration, "datetime", FixedDateTime)
    result = sensors.cn_a_moneyflow_mkt_dc_trade_day_sensor.evaluate_tick(ctx)
    assert result.dynamic_partitions_requests[0].partition_keys == [DAY, "2026-09-28"]
    assert not result.run_requests
    monkeypatch.setattr(
        registration,
        "datetime",
        type(
            "Before",
            (FixedDateTime,),
            {"now": classmethod(lambda cls, tz=None: NOW.replace(hour=21))},
        ),
    )
    before = sensors.cn_a_moneyflow_mkt_dc_trade_day_sensor.evaluate_tick(ctx)
    assert DAY not in before.dynamic_partitions_requests[0].partition_keys
    monkeypatch.setattr(
        registration,
        "datetime",
        type(
            "Holiday",
            (FixedDateTime,),
            {"now": classmethod(lambda cls, tz=None: NOW.replace(day=10))},
        ),
    )
    holiday = sensors.cn_a_moneyflow_mkt_dc_trade_day_sensor.evaluate_tick(ctx)
    assert all(
        "2026-10-10" not in r.partition_keys
        for r in holiday.dynamic_partitions_requests
    )


@pytest.mark.parametrize(
    "response,retryable",
    [(TimeoutError("timeout"), True), (Exception("权限不足"), False), ([], True)],
)
def test_source_policy_failure_classification(response, retryable):
    from orchestrator.defs.source_readiness.moneyflow import collect_market_moneyflow

    clock = support.Clock()
    source = support.Source([response] * 10)
    with pytest.raises(MoneyflowContractError) as caught:
        collect_market_moneyflow(
            tushare=source,
            trade_date=DAY,
            on_first_round=lambda _: None,
            clock=clock,
            sleep_fn=clock.sleep,
        )
    assert caught.value.retryable is retryable


def test_bounded_hash_size_and_query_count_real_evidence(env, monkeypatch):
    import json
    from time import perf_counter

    import orchestrator.defs.asset_guards.moneyflow_delivery_readiness as guard

    ctx = context(env)
    publish(env)
    counts = {"materializations": 0, "checks": 0, "hashes": 0}
    original_mat = env.instance.fetch_materializations
    original_checks = env.instance.event_log_storage.get_asset_check_execution_history
    original_hash = guard.candidate_file_hash

    def mats(*args, **kwargs):
        counts["materializations"] += 1
        assert kwargs["limit"] == 100
        return original_mat(*args, **kwargs)

    def checks(*args, **kwargs):
        counts["checks"] += 1
        assert kwargs["limit"] == 100
        return original_checks(*args, **kwargs)

    def hash_file(path):
        counts["hashes"] += 1
        return original_hash(path)

    monkeypatch.setattr(env.instance, "fetch_materializations", mats)
    monkeypatch.setattr(
        env.instance.event_log_storage, "get_asset_check_execution_history", checks
    )
    monkeypatch.setattr(guard, "candidate_file_hash", hash_file)
    started = perf_counter()
    ready = batch_market_moneyflow_readiness(env.instance, env.lake, [DAY])
    assert ready["raw"][DAY].ready and ready["silver"][DAY].ready
    elapsed = perf_counter() - started
    assert counts == {"materializations": 2, "checks": 2, "hashes": 2}
    proof = {
        "partition": DAY,
        "counts": counts.copy(),
        "elapsed_seconds": elapsed,
        "check_status": "SUCCEEDED",
        "source_calls_during_sensors": 0,
        "cursor_bytes": len(
            sensors.evaluate_market_moneyflow(ctx, NOW, silver=True).cursor.encode()
        ),
    }
    (env.staging / "sensor-readiness-evidence.json").write_text(
        json.dumps(proof, indent=2)
    )
    path = raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    path.write_bytes(b"x" * (64 * 1024 + 1))
    previous = counts["hashes"]
    assert (
        batch_market_moneyflow_readiness(
            env.instance, env.lake, [DAY], layers=("raw",)
        )["raw"][DAY].reason
        == "file_hash_budget"
    )
    assert counts["hashes"] == previous


def test_non_executed_check_does_not_erase_prior_green_proof(env):
    context(env)
    publish(env)
    env.source.responses = iter([[], []])
    assert not run(env, sensors.RAW_JOB, day=DAY, raise_on_error=False).success
    assert batch_market_moneyflow_readiness(env.instance, env.lake, [DAY])["raw"][
        DAY
    ].ready


def test_saturated_history_without_window_coverage_fails_closed():
    instance = SimpleNamespace(
        fetch_materializations=lambda *a, **k: SimpleNamespace(
            records=[SimpleNamespace(partition_key="2026-09-01")] * 100
        ),
        event_log_storage=SimpleNamespace(
            get_asset_check_execution_history=lambda *a, **k: []
        ),
    )
    with pytest.raises(MoneyflowContractError, match="readiness_record_limit"):
        batch_market_moneyflow_readiness(instance, None, [DAY])
