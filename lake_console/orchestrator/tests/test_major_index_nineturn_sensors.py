from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
)
from orchestrator.defs.run_contracts.cursors import (
    TYPICAL_SENSOR_CURSOR_BYTES,
    load_sensor_cursor,
)
from orchestrator.defs.sensors import major_index_nineturn_sensor as gold_sensor
from orchestrator.defs.sensors.index_daily_nineturn_prod_core_sensor import (
    prod_core_index_daily_nineturn_sync_job_sensor,
)

PREVIOUS_TRADE_DATE = "2026-08-13"
TARGET_TRADE_DATE = "2026-08-14"
EXPECTED_TRADE_DATES = (PREVIOUS_TRADE_DATE, TARGET_TRADE_DATE)


class _FakeInstance:
    def __init__(self, registered_trade_dates: tuple[str, ...]) -> None:
        self.registered_trade_dates = registered_trade_dates

    def get_dynamic_partitions(self, _partition_set_name: str) -> list[str]:
        return list(self.registered_trade_dates)

    def get_event_records(self, *_args, **_kwargs):
        raise AssertionError("major-index nine-turn sensors must not scan event history")


class _FakeDuckDB:
    def __init__(self) -> None:
        self.connection_count = 0

    @contextmanager
    def connect(self):
        self.connection_count += 1
        yield object()


def _gold_sensor_context(
    tmp_path: Path,
    *,
    registered_trade_dates: tuple[str, ...] = EXPECTED_TRADE_DATES,
) -> SimpleNamespace:
    duckdb_resource = _FakeDuckDB()
    return SimpleNamespace(
        instance=_FakeInstance(registered_trade_dates),
        resources=SimpleNamespace(
            lake_root=SimpleNamespace(
                ensure_available_for_run=lambda: None,
                root=lambda: tmp_path,
            ),
            duckdb=duckdb_resource,
        ),
        duckdb_resource=duckdb_resource,
    )


def _expected_window() -> ContinuityExpectedDateWindow:
    return ContinuityExpectedDateWindow(
        expected_trade_dates=EXPECTED_TRADE_DATES,
        min_trade_date=None,
        max_trade_date=TARGET_TRADE_DATE,
        evaluated_at=datetime(2026, 8, 15, 19, 39, tzinfo=gold_sensor.CN_A_SENSOR_TIMEZONE),
        window_limit=10,
    )


def _ready(trade_date: str) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=True,
        materialized=True,
        checks_passed=True,
        reason="ready",
    )


def _missing(trade_date: str) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason="target_files_missing",
    )


def _failed(trade_date: str) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=True,
        checks_passed=False,
        reason="target_integrity_failed",
        failed_check_names=("gold_major_index_nineturn_integrity_check",),
    )


def _batch(*statuses: ContinuityDateReadiness) -> ContinuityBatchReadiness:
    return ContinuityBatchReadiness(
        expected_trade_dates=tuple(status.trade_date for status in statuses),
        statuses_by_trade_date={status.trade_date: status for status in statuses},
        elapsed_ms=1,
        scanned_file_count=sum(status.materialized for status in statuses),
    )


def _evaluate_gold_sensor(*, minute: bool, context: SimpleNamespace) -> dg.SensorResult:
    definition = (
        gold_sensor.gold_major_index_mins_nineturn_update_job_sensor
        if minute
        else gold_sensor.gold_major_index_daily_nineturn_update_job_sensor
    )
    return definition._raw_fn(context)


def _install_gold_sensor_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_batch: ContinuityBatchReadiness,
    previous_batch: ContinuityBatchReadiness | None = None,
    upstream_ready: bool = True,
) -> list[tuple[str, ...]]:
    readiness_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        gold_sensor,
        "load_expected_trade_date_window",
        lambda *_args, **_kwargs: _expected_window(),
    )

    def _readiness(**kwargs) -> ContinuityBatchReadiness:
        trade_dates = tuple(kwargs["expected_trade_dates"])
        readiness_calls.append(trade_dates)
        if trade_dates == (PREVIOUS_TRADE_DATE,) and previous_batch is not None:
            return previous_batch
        return target_batch

    monkeypatch.setattr(
        gold_sensor,
        "batch_gold_major_index_nineturn_readiness",
        _readiness,
    )
    upstream_status = SimpleNamespace(ready=upstream_ready, reason="test readiness")
    monkeypatch.setattr(
        gold_sensor,
        "gold_market_major_indices_daily_ready_for_trade_date",
        lambda *_args, **_kwargs: upstream_status,
    )
    monkeypatch.setattr(
        gold_sensor,
        "partition_dataset_readiness_status_from_latest_checks",
        lambda *_args, **_kwargs: upstream_status,
    )
    return readiness_calls


def _assert_cursor(result: dg.SensorResult, reason_code: str) -> dict[str, object]:
    assert result.cursor is not None
    assert len(result.cursor.encode("utf-8")) <= TYPICAL_SENSOR_CURSOR_BYTES
    payload = load_sensor_cursor(result.cursor)
    assert payload["details"]["reason_code"] == reason_code
    return payload


@pytest.mark.parametrize("minute", [False, True])
def test_gold_sensor_stops_at_missing_registration_before_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    minute: bool,
) -> None:
    context = _gold_sensor_context(
        tmp_path,
        registered_trade_dates=(PREVIOUS_TRADE_DATE,),
    )
    monkeypatch.setattr(
        gold_sensor,
        "load_expected_trade_date_window",
        lambda *_args, **_kwargs: _expected_window(),
    )

    def _unexpected_readiness(**_kwargs):
        raise AssertionError("readiness must not run before the registration gate")

    monkeypatch.setattr(
        gold_sensor,
        "batch_gold_major_index_nineturn_readiness",
        _unexpected_readiness,
    )

    result = _evaluate_gold_sensor(minute=minute, context=context)

    assert not result.run_requests
    payload = _assert_cursor(result, "missing_registered_partition")
    assert payload["target_date"] == TARGET_TRADE_DATE
    assert context.duckdb_resource.connection_count == 1


@pytest.mark.parametrize("minute", [False, True])
def test_gold_sensor_skips_when_entire_window_is_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    minute: bool,
) -> None:
    context = _gold_sensor_context(tmp_path)
    calls = _install_gold_sensor_fakes(
        monkeypatch,
        target_batch=_batch(_ready(PREVIOUS_TRADE_DATE), _ready(TARGET_TRADE_DATE)),
    )

    result = _evaluate_gold_sensor(minute=minute, context=context)

    assert not result.run_requests
    payload = _assert_cursor(result, "all_ready")
    assert payload["target_date"] is None
    assert calls == [EXPECTED_TRADE_DATES]


@pytest.mark.parametrize("minute", [False, True])
def test_gold_sensor_refuses_to_overwrite_failed_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    minute: bool,
) -> None:
    context = _gold_sensor_context(tmp_path)
    calls = _install_gold_sensor_fakes(
        monkeypatch,
        target_batch=_batch(_ready(PREVIOUS_TRADE_DATE), _failed(TARGET_TRADE_DATE)),
    )

    result = _evaluate_gold_sensor(minute=minute, context=context)

    assert not result.run_requests
    payload = _assert_cursor(result, "target_integrity_failed")
    assert payload["target_date"] == TARGET_TRADE_DATE
    assert calls == [EXPECTED_TRADE_DATES]


@pytest.mark.parametrize("minute", [False, True])
def test_gold_sensor_waits_for_same_partition_upstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    minute: bool,
) -> None:
    context = _gold_sensor_context(tmp_path)
    calls = _install_gold_sensor_fakes(
        monkeypatch,
        target_batch=_batch(_ready(PREVIOUS_TRADE_DATE), _missing(TARGET_TRADE_DATE)),
        upstream_ready=False,
    )

    result = _evaluate_gold_sensor(minute=minute, context=context)

    assert not result.run_requests
    payload = _assert_cursor(result, "upstream_not_ready")
    assert payload["target_date"] == TARGET_TRADE_DATE
    assert calls == [EXPECTED_TRADE_DATES]


@pytest.mark.parametrize("minute", [False, True])
def test_gold_sensor_refuses_to_break_previous_partition_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    minute: bool,
) -> None:
    context = _gold_sensor_context(tmp_path)
    calls = _install_gold_sensor_fakes(
        monkeypatch,
        target_batch=_batch(_ready(PREVIOUS_TRADE_DATE), _missing(TARGET_TRADE_DATE)),
        previous_batch=_batch(_failed(PREVIOUS_TRADE_DATE)),
    )

    result = _evaluate_gold_sensor(minute=minute, context=context)

    assert not result.run_requests
    payload = _assert_cursor(result, "previous_partition_not_ready")
    assert payload["target_date"] == TARGET_TRADE_DATE
    assert calls == [EXPECTED_TRADE_DATES, (PREVIOUS_TRADE_DATE,)]


@pytest.mark.parametrize("minute", [False, True])
def test_gold_sensor_fails_closed_on_unexpected_error(
    tmp_path: Path,
    minute: bool,
) -> None:
    context = _gold_sensor_context(tmp_path)

    def _raise() -> None:
        raise RuntimeError("isolated failure")

    context.resources.lake_root.ensure_available_for_run = _raise

    result = _evaluate_gold_sensor(minute=minute, context=context)

    assert not result.run_requests
    payload = _assert_cursor(result, "sensor_error_runtimeerror")
    assert payload["target_date"] is None


@pytest.mark.parametrize(
    ("minute", "expected_run_key"),
    [
        (False, "gold_major_index_daily_nineturn_update:2026-08-14"),
        (True, "gold_major_index_mins_nineturn_update:2026-08-14"),
    ],
)
def test_gold_sensor_requests_exactly_one_partition_with_stable_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    minute: bool,
    expected_run_key: str,
) -> None:
    context = _gold_sensor_context(tmp_path)
    calls = _install_gold_sensor_fakes(
        monkeypatch,
        target_batch=_batch(_ready(PREVIOUS_TRADE_DATE), _missing(TARGET_TRADE_DATE)),
        previous_batch=_batch(_ready(PREVIOUS_TRADE_DATE)),
    )

    result = _evaluate_gold_sensor(minute=minute, context=context)

    assert len(result.run_requests) == 1
    request = result.run_requests[0]
    assert request.partition_key == TARGET_TRADE_DATE
    assert request.run_key == expected_run_key
    payload = _assert_cursor(result, "request_run")
    assert payload["decision"] == "request_runs"
    assert payload["selected_count"] == 1
    assert calls == [EXPECTED_TRADE_DATES, (PREVIOUS_TRADE_DATE,)]


def _serving_context(*, partition_key: str, producer_run_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        instance=object(),
        dagster_run=SimpleNamespace(
            run_id=producer_run_id,
            tags={"dagster/partition": partition_key},
        ),
    )


def test_serving_sensor_rejects_invalid_partition_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected_readiness(*_args, **_kwargs):
        raise AssertionError("readiness must not run for an invalid partition")

    monkeypatch.setattr(
        "orchestrator.defs.sensors.index_daily_nineturn_prod_core_sensor."
        "partition_dataset_readiness_status_from_latest_checks",
        _unexpected_readiness,
    )

    result = prod_core_index_daily_nineturn_sync_job_sensor._run_status_sensor_fn(
        _serving_context(partition_key="not-a-date", producer_run_id="producer-a")
    )

    assert isinstance(result, dg.SkipReason)
    assert result.skip_message == "upstream run has no valid partition"


def test_serving_sensor_waits_for_gold_blocking_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "orchestrator.defs.sensors.index_daily_nineturn_prod_core_sensor."
        "partition_dataset_readiness_status_from_latest_checks",
        lambda *_args, **_kwargs: SimpleNamespace(
            ready=False,
            reason="missing blocking check",
        ),
    )

    result = prod_core_index_daily_nineturn_sync_job_sensor._run_status_sensor_fn(
        _serving_context(
            partition_key=TARGET_TRADE_DATE,
            producer_run_id="producer-a",
        )
    )

    assert isinstance(result, dg.SkipReason)
    assert result.skip_message == "gold_not_ready: missing blocking check"


def test_serving_sensor_run_key_is_idempotent_per_producer_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "orchestrator.defs.sensors.index_daily_nineturn_prod_core_sensor."
        "partition_dataset_readiness_status_from_latest_checks",
        lambda *_args, **_kwargs: SimpleNamespace(ready=True, reason="ready"),
    )

    first = prod_core_index_daily_nineturn_sync_job_sensor._run_status_sensor_fn(
        _serving_context(
            partition_key=TARGET_TRADE_DATE,
            producer_run_id="producer-a",
        )
    )
    duplicate = prod_core_index_daily_nineturn_sync_job_sensor._run_status_sensor_fn(
        _serving_context(
            partition_key=TARGET_TRADE_DATE,
            producer_run_id="producer-a",
        )
    )
    rerun = prod_core_index_daily_nineturn_sync_job_sensor._run_status_sensor_fn(
        _serving_context(
            partition_key=TARGET_TRADE_DATE,
            producer_run_id="producer-b",
        )
    )

    assert isinstance(first, dg.RunRequest)
    assert isinstance(duplicate, dg.RunRequest)
    assert isinstance(rerun, dg.RunRequest)
    assert first.partition_key == TARGET_TRADE_DATE
    assert first.run_key == duplicate.run_key
    assert first.run_key != rerun.run_key


@dg.op
def _historical_success_op() -> None:
    pass


@dg.job(name="gold_major_index_daily_nineturn_update_job")
def _historical_success_job() -> None:
    _historical_success_op()


def test_serving_sensor_first_tick_initializes_cursor_without_history_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness_calls: list[str] = []

    def _ready(*_args, **kwargs):
        readiness_calls.append(str(kwargs["partition_key"]))
        return SimpleNamespace(ready=True, reason="ready")

    monkeypatch.setattr(
        "orchestrator.defs.sensors.index_daily_nineturn_prod_core_sensor."
        "partition_dataset_readiness_status_from_latest_checks",
        _ready,
    )
    with dg.DagsterInstance.ephemeral() as instance:
        historical_result = _historical_success_job.execute_in_process(
            instance=instance,
            tags={"dagster/partition": TARGET_TRADE_DATE},
        )
        assert historical_result.success is True

        first_tick = prod_core_index_daily_nineturn_sync_job_sensor.evaluate_tick(
            dg.build_sensor_context(instance=instance)
        )
        assert not first_tick.run_requests
        assert first_tick.skip_message is not None
        assert first_tick.skip_message.startswith(
            "Initiating prod_core_index_daily_nineturn_sync_job_sensor"
        )
        assert first_tick.cursor is not None
        first_cursor = json.loads(first_tick.cursor)
        assert first_cursor["record_id"] > 0

        second_tick = prod_core_index_daily_nineturn_sync_job_sensor.evaluate_tick(
            dg.build_sensor_context(instance=instance, cursor=first_tick.cursor)
        )
        assert not second_tick.run_requests
        assert second_tick.skip_message == "Sensor function returned an empty result"
        assert second_tick.cursor == first_tick.cursor
        assert readiness_calls == []
