from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
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
        self.partition_sets_read: list[str] = []
        self.write_attempts: list[str] = []

    def get_dynamic_partitions(self, partition_set_name: str) -> list[str]:
        self.partition_sets_read.append(partition_set_name)
        return list(self.registered_trade_dates)

    def get_event_records(self, *_args, **_kwargs):
        raise AssertionError("major-index nine-turn sensors must not scan event history")

    def __getattr__(self, name):
        if name in {
            "add_dynamic_partitions", "delete_dynamic_partition", "create_run",
            "create_run_for_job", "submit_run", "report_runless_asset_event",
            "store_event", "update_instigator_state", "add_instigator_state",
        }:
            self.write_attempts.append(name)
            raise AssertionError(f"sensor must not write instance state: {name}")
        raise AttributeError(name)


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


def _expected_window(
    *,
    trade_dates: tuple[str, ...] = EXPECTED_TRADE_DATES,
    window_limit: int = 10,
) -> ContinuityExpectedDateWindow:
    return ContinuityExpectedDateWindow(
        expected_trade_dates=trade_dates,
        min_trade_date=None,
        max_trade_date=trade_dates[-1] if trade_dates else None,
        evaluated_at=datetime(2026, 8, 15, 19, 39, tzinfo=gold_sensor.CN_A_SENSOR_TIMEZONE),
        window_limit=window_limit,
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
        lambda *_args, **kwargs: _expected_window(window_limit=kwargs["window_limit"]),
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
        registered_trade_dates=(PREVIOUS_TRADE_DATE, "2026-08-17"),
    )
    monkeypatch.setattr(
        gold_sensor,
        "load_expected_trade_date_window",
        lambda *_args, **kwargs: _expected_window(
            trade_dates=(PREVIOUS_TRADE_DATE, TARGET_TRADE_DATE, "2026-08-17"),
            window_limit=kwargs["window_limit"],
        ),
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


@pytest.mark.parametrize("minute", [False, True])
def test_gold_sensor_recovers_registered_old_date_before_unregistered_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    minute: bool,
) -> None:
    """Literal dates reproduce the Oct 30 tick and its already registered Oct 29.

    Readiness substitutes only the existing target/upstream/previous checks;
    the registration classifier and earliest-date selector remain real.
    """
    previous_date = "2026-10-28"
    target_date = "2026-10-29"
    expected_dates = (previous_date, target_date, "2026-10-30")
    actionable_dates = (previous_date, target_date)
    context = _gold_sensor_context(
        tmp_path, registered_trade_dates=actionable_dates
    )
    monkeypatch.setattr(
        gold_sensor,
        "load_expected_trade_date_window",
        lambda *_args, **_kwargs: ContinuityExpectedDateWindow(
            expected_trade_dates=expected_dates,
            min_trade_date=None,
            max_trade_date="2026-10-30",
            evaluated_at=datetime(
                2026, 10, 30, 9, 30, tzinfo=gold_sensor.CN_A_SENSOR_TIMEZONE
            ),
            window_limit=5 if minute else 10,
        ),
    )
    readiness_calls: list[tuple[str, ...]] = []

    def _readiness(**kwargs):
        dates = tuple(kwargs["expected_trade_dates"])
        readiness_calls.append(dates)
        assert kwargs["minute"] is minute
        if dates == (previous_date,):
            return _batch(_ready(previous_date))
        assert dates == actionable_dates
        return _batch(_ready(previous_date), _missing(target_date))

    monkeypatch.setattr(
        gold_sensor, "batch_gold_major_index_nineturn_readiness", _readiness
    )
    upstream_calls: list[str] = []

    def _daily_upstream(_instance, trade_date):
        assert minute is False
        upstream_calls.append(trade_date)
        return SimpleNamespace(ready=True)

    def _minute_upstream(_instance, specs, *, partition_key):
        assert minute is True
        assert specs is gold_sensor._MINUTE_UPSTREAM_SPECS
        upstream_calls.append(partition_key)
        return SimpleNamespace(ready=True)

    monkeypatch.setattr(
        gold_sensor,
        "gold_market_major_indices_daily_ready_for_trade_date",
        _daily_upstream,
    )
    monkeypatch.setattr(
        gold_sensor,
        "partition_dataset_readiness_status_from_latest_checks",
        _minute_upstream,
    )
    selector_calls: list[tuple[str, ...]] = []
    real_selector = gold_sensor.select_first_not_ready_trade_date

    def _selector(**kwargs):
        selector_calls.append(tuple(kwargs["expected_trade_dates"]))
        return real_selector(**kwargs)

    monkeypatch.setattr(gold_sensor, "select_first_not_ready_trade_date", _selector)

    result = _evaluate_gold_sensor(minute=minute, context=context)

    assert len(result.run_requests) == 1
    request = result.run_requests[0]
    assert request.partition_key == "2026-10-29"
    assert request.run_key == (
        "gold_major_index_mins_nineturn_update:2026-10-29"
        if minute
        else "gold_major_index_daily_nineturn_update:2026-10-29"
    )
    assert readiness_calls == [actionable_dates, (previous_date,)]
    assert selector_calls == [actionable_dates]
    assert upstream_calls == [target_date]
    payload = _assert_cursor(result, "request_run")
    assert payload["target_date"] == target_date


def _scenario_spies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    minute: bool,
    expected_dates: tuple[str, ...],
    statuses: tuple[ContinuityDateReadiness, ...],
    previous_date: str | None = None,
    previous_ready: bool = True,
    upstream_ready: bool = True,
    real_calendar: bool = False,
    target_batch_override: ContinuityBatchReadiness | None = None,
) -> SimpleNamespace:
    """Replace only downstream status reads; classifier/selector remain real.

    Status objects follow ContinuityDateReadiness's existing contract. Literal
    expected requests in each test are independent of the classifier/selector.
    """
    calls = SimpleNamespace(loader=[], readiness=[], selector=[], upstream=[])
    real_loader = gold_sensor.load_expected_trade_date_window
    real_selector = gold_sensor.select_first_not_ready_trade_date
    by_date = {status.trade_date: status for status in statuses}

    def _loader(connection, calendar_path, **kwargs):
        calls.loader.append((calendar_path, kwargs))
        assert kwargs["window_limit"] == (5 if minute else 10)
        assert kwargs["same_day_register_start"] is None
        if real_calendar:
            return real_loader(connection, calendar_path, **kwargs)
        return _expected_window(
            trade_dates=expected_dates, window_limit=kwargs["window_limit"]
        )

    def _readiness(**kwargs):
        dates = tuple(kwargs["expected_trade_dates"])
        calls.readiness.append(dates)
        assert kwargs["minute"] is minute
        if previous_date is not None and dates == (previous_date,):
            return _batch(
                _ready(previous_date) if previous_ready else _failed(previous_date)
            )
        if target_batch_override is not None:
            return target_batch_override
        return _batch(*(by_date[day] for day in dates))

    def _daily_upstream(_instance, target):
        assert minute is False, "minute sensor called daily upstream"
        calls.upstream.append(("daily", target))
        return SimpleNamespace(ready=upstream_ready)

    def _minute_upstream(_instance, specs, *, partition_key):
        assert minute is True, "daily sensor called minute upstream"
        assert tuple(spec.asset_key.to_user_string() for spec in specs) == (
            "gold_major_index_mins_5m", "gold_major_index_mins_15m",
            "gold_major_index_mins_30m", "gold_major_index_mins_60m",
            "gold_major_index_mins_90m", "gold_major_index_mins_120m",
        )
        calls.upstream.append(("minute", partition_key))
        return SimpleNamespace(ready=upstream_ready)

    def _selector(**kwargs):
        calls.selector.append(tuple(kwargs["expected_trade_dates"]))
        return real_selector(**kwargs)

    monkeypatch.setattr(gold_sensor, "load_expected_trade_date_window", _loader)
    monkeypatch.setattr(gold_sensor, "batch_gold_major_index_nineturn_readiness", _readiness)
    monkeypatch.setattr(gold_sensor, "select_first_not_ready_trade_date", _selector)
    monkeypatch.setattr(
        gold_sensor, "gold_market_major_indices_daily_ready_for_trade_date", _daily_upstream
    )
    monkeypatch.setattr(
        gold_sensor, "partition_dataset_readiness_status_from_latest_checks", _minute_upstream
    )
    return calls


def _assert_read_only_context(context: SimpleNamespace, *, minute: bool) -> None:
    assert context.instance.write_attempts == []
    assert context.instance.partition_sets_read == [
        "cn_major_index_mins_trade_days" if minute else "cn_a_index_trade_days"
    ]
    assert context.duckdb_resource.connection_count <= 2


@pytest.mark.parametrize("minute", [False, True])
@pytest.mark.parametrize(
    ("expected_dates", "registered", "expected_reason", "target", "gap_class"),
    [
        ((), (), "all_ready", None, "none"),
        (("2026-10-28", "2026-10-29", "2026-10-30"), (),
         "missing_registered_partition", "2026-10-28", "empty"),
        (("2026-10-28", "2026-10-29", "2026-10-30"),
         ("2026-10-28", "2026-10-30"),
         "missing_registered_partition", "2026-10-29", "internal"),
        (("2026-10-28", "2026-10-29", "2026-10-30"),
         ("2026-10-29", "2026-10-30"),
         "missing_registered_partition", "2026-10-28", "internal"),
    ],
    ids=["empty-window", "all-unregistered", "internal-gap", "leading-gap"],
)
def test_registration_cases_stop_before_target_or_upstream_reads(
    tmp_path, monkeypatch, minute, expected_dates, registered,
    expected_reason, target, gap_class,
):
    context = _gold_sensor_context(tmp_path, registered_trade_dates=registered)
    calls = _scenario_spies(
        monkeypatch, minute=minute, expected_dates=expected_dates, statuses=()
    )

    result = _evaluate_gold_sensor(minute=minute, context=context)

    assert not result.run_requests
    payload = _assert_cursor(result, expected_reason)
    assert payload["target_date"] == target
    assert payload["sample_keys"] == ([] if target is None else [target])
    assert payload["selected_count"] == 0
    assert payload["details"]["evidence"]["registration_gap_class"] == gap_class
    assert calls.readiness == calls.selector == calls.upstream == []
    assert len(calls.loader) == 1
    assert context.duckdb_resource.connection_count == 1
    _assert_read_only_context(context, minute=minute)


@pytest.mark.parametrize("minute", [False, True])
@pytest.mark.parametrize("several_tail_dates", [False, True])
def test_completed_registered_prefix_waits_for_first_tail_without_claiming_all_ready(
    tmp_path, monkeypatch, minute, several_tail_dates,
):
    dates = ("2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30")
    registered = ("2026-10-27", "2026-10-28") if several_tail_dates else dates[:3]
    context = _gold_sensor_context(tmp_path, registered_trade_dates=registered)
    calls = _scenario_spies(
        monkeypatch, minute=minute, expected_dates=dates,
        statuses=tuple(_ready(day) for day in registered),
    )

    result = _evaluate_gold_sensor(minute=minute, context=context)

    assert not result.run_requests
    payload = _assert_cursor(result, "missing_registered_partition")
    assert payload["target_date"] == (
        "2026-10-29" if several_tail_dates else "2026-10-30"
    )
    assert payload["details"]["evidence"]["registration_gap_class"] == "trailing"
    assert payload["details"]["evidence"]["actionable_registered_count"] == len(registered)
    assert calls.readiness == calls.selector == [registered]
    assert calls.upstream == []
    _assert_read_only_context(context, minute=minute)


@pytest.mark.parametrize("minute", [False, True])
@pytest.mark.parametrize(
    ("failure", "reason", "expected_target"),
    [
        ("upstream", "upstream_not_ready", "2026-10-29"),
        ("previous", "previous_partition_not_ready", "2026-10-29"),
        ("bad-target", "target_integrity_failed", "2026-10-29"),
        ("earlier-bad-target", "target_integrity_failed", "2026-10-28"),
    ],
)
def test_unregistered_tail_does_not_weaken_existing_quality_or_continuity_gates(
    tmp_path, monkeypatch, minute, failure, reason, expected_target,
):
    registered = ("2026-10-28", "2026-10-29")
    context = _gold_sensor_context(tmp_path, registered_trade_dates=registered)
    statuses = (
        _failed("2026-10-28") if failure == "earlier-bad-target" else _ready("2026-10-28"),
        _failed("2026-10-29") if failure == "bad-target" else _missing("2026-10-29"),
    )
    calls = _scenario_spies(
        monkeypatch, minute=minute, expected_dates=(*registered, "2026-10-30"),
        statuses=statuses, previous_date="2026-10-28",
        previous_ready=failure != "previous", upstream_ready=failure != "upstream",
    )

    result = _evaluate_gold_sensor(minute=minute, context=context)

    assert not result.run_requests
    payload = _assert_cursor(result, reason)
    assert payload["target_date"] == expected_target
    assert calls.selector == [registered]
    assert calls.readiness == (
        [registered, ("2026-10-28",)] if failure == "previous" else [registered]
    )
    assert calls.upstream == (
        [] if "bad-target" in failure
        else [("minute" if minute else "daily", "2026-10-29")]
    )
    _assert_read_only_context(context, minute=minute)


@pytest.mark.parametrize("minute", [False, True])
@pytest.mark.parametrize("previous_ready", [False, True])
def test_window_first_date_still_checks_registered_previous_outside_window(
    tmp_path, monkeypatch, minute, previous_ready,
):
    context = _gold_sensor_context(
        tmp_path, registered_trade_dates=("2026-10-27", "2026-10-28", "2026-10-29")
    )
    calls = _scenario_spies(
        monkeypatch, minute=minute,
        expected_dates=("2026-10-28", "2026-10-29", "2026-10-30"),
        statuses=(_missing("2026-10-28"), _missing("2026-10-29")),
        previous_date="2026-10-27", previous_ready=previous_ready,
    )

    result = _evaluate_gold_sensor(minute=minute, context=context)

    payload = _assert_cursor(
        result, "request_run" if previous_ready else "previous_partition_not_ready"
    )
    assert payload["target_date"] == "2026-10-28"
    assert len(result.run_requests) == (1 if previous_ready else 0)
    assert calls.readiness == [
        ("2026-10-28", "2026-10-29"), ("2026-10-27",)
    ]
    assert calls.upstream == [("minute" if minute else "daily", "2026-10-28")]
    _assert_read_only_context(context, minute=minute)


@pytest.mark.parametrize("minute", [False, True])
@pytest.mark.parametrize("wrong_dates", [False, True])
def test_incomplete_or_mismatched_readiness_stops_instead_of_claiming_all_ready(
    tmp_path, monkeypatch, minute, wrong_dates,
):
    registered = ("2026-10-28", "2026-10-29")
    context = _gold_sensor_context(tmp_path, registered_trade_dates=registered)
    incomplete = ContinuityBatchReadiness(
        expected_trade_dates=("2026-10-28",) if wrong_dates else registered,
        statuses_by_trade_date={"2026-10-28": _ready("2026-10-28")},
        elapsed_ms=1, scanned_file_count=1,
    )
    calls = _scenario_spies(
        monkeypatch, minute=minute, expected_dates=(*registered, "2026-10-30"),
        statuses=(), target_batch_override=incomplete,
    )

    result = _evaluate_gold_sensor(minute=minute, context=context)

    assert not result.run_requests
    payload = _assert_cursor(result, "sensor_error_runtimeerror")
    assert payload["target_date"] is None
    assert calls.readiness == [registered]
    assert calls.selector == ([] if wrong_dates else [registered])
    assert calls.upstream == []
    _assert_read_only_context(context, minute=minute)


@pytest.mark.parametrize("minute", [False, True])
def test_multiple_unregistered_tail_dates_preserve_earliest_request_and_run_key(
    tmp_path, monkeypatch, minute,
):
    registered = ("2026-10-27", "2026-10-28")
    context = _gold_sensor_context(tmp_path, registered_trade_dates=registered)
    calls = _scenario_spies(
        monkeypatch, minute=minute,
        expected_dates=("2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"),
        statuses=(_ready("2026-10-27"), _missing("2026-10-28")),
        previous_date="2026-10-27",
    )

    first = _evaluate_gold_sensor(minute=minute, context=context)
    repeated = _evaluate_gold_sensor(minute=minute, context=context)

    expected_key = (
        "gold_major_index_mins_nineturn_update:2026-10-28"
        if minute else "gold_major_index_daily_nineturn_update:2026-10-28"
    )
    for result in (first, repeated):
        assert len(result.run_requests) == 1
        assert result.run_requests[0].partition_key == "2026-10-28"
        assert result.run_requests[0].run_key == expected_key
        payload = _assert_cursor(result, "request_run")
        assert payload["target_date"] == "2026-10-28"
        assert payload["sample_keys"] == ["2026-10-28"]
        assert payload["details"]["evidence"]["first_trailing_unregistered_date"] == "2026-10-29"
    assert calls.readiness == [registered, ("2026-10-27",)] * 2
    assert calls.selector == [registered, registered]
    assert context.instance.write_attempts == []
    assert context.instance.partition_sets_read == [
        "cn_major_index_mins_trade_days" if minute else "cn_a_index_trade_days"
    ] * 2


class _CalendarDuckDB:
    def __init__(self, connection):
        self.connection = connection
        self.connection_count = 0

    @contextmanager
    def connect(self):
        self.connection_count += 1
        yield self.connection


@contextmanager
def _calendar_context(tmp_path, *, registered, calendar_rows):
    """Real four-column Silver contract; no formal Lake or managed Resource.

    Contract: SILVER_TRADE_CALENDAR_SCHEMA; producer assets/calendar.py's
    silver_trade_calendar uses duckdb_sql.silver_trade_calendar_select. The
    literal open/closed dates and prior dates below are independent fixtures.
    """
    calendar_path = gold_sensor.silver_trade_calendar_path(tmp_path)
    calendar_path.parent.mkdir(parents=True)
    with duckdb.connect(":memory:", config={
        "temp_directory": str(tmp_path / "duckdb_tmp"),
        "max_temp_directory_size": "0B", "memory_limit": "128MB", "threads": "1",
        "autoinstall_known_extensions": "false", "autoload_known_extensions": "false",
    }) as connection:
        connection.execute(
            "CREATE TABLE fixture_calendar (exchange VARCHAR, trade_date DATE, "
            "is_open BOOLEAN, pretrade_date DATE)"
        )
        assert len(calendar_rows) <= 20
        connection.executemany("INSERT INTO fixture_calendar VALUES (?, ?, ?, ?)", calendar_rows)
        quoted_path = str(calendar_path).replace("'", "''")
        connection.execute(f"COPY fixture_calendar TO '{quoted_path}' (FORMAT PARQUET)")
        assert [tuple(row[:2]) for row in connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{quoted_path}')"
        ).fetchall()] == [
            ("exchange", "VARCHAR"), ("trade_date", "DATE"),
            ("is_open", "BOOLEAN"), ("pretrade_date", "DATE"),
        ]
        context = _gold_sensor_context(tmp_path, registered_trade_dates=registered)
        context.duckdb_resource = _CalendarDuckDB(connection)
        context.resources.duckdb = context.duckdb_resource
        yield context


def _freeze_sensor_clock(monkeypatch, evaluated_at):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return evaluated_at.astimezone(tz) if tz else evaluated_at.replace(tzinfo=None)

    monkeypatch.setattr(gold_sensor, "datetime", FrozenDatetime)


OCTOBER_CALENDAR_ROWS = (
    ("SSE", "2026-10-12", True, "2026-10-09"),
    ("SSE", "2026-10-13", True, "2026-10-12"),
    ("SSE", "2026-10-14", True, "2026-10-13"),
    ("SSE", "2026-10-15", True, "2026-10-14"),
    ("SSE", "2026-10-16", True, "2026-10-15"),
    ("SSE", "2026-10-19", True, "2026-10-16"),
    ("SSE", "2026-10-20", True, "2026-10-19"),
    ("SSE", "2026-10-21", True, "2026-10-20"),
    ("SSE", "2026-10-22", True, "2026-10-21"),
    ("SSE", "2026-10-23", True, "2026-10-22"),
    ("SSE", "2026-10-24", False, "2026-10-23"),
    ("SSE", "2026-10-25", False, "2026-10-23"),
    ("SSE", "2026-10-26", True, "2026-10-23"),
    ("SSE", "2026-10-27", True, "2026-10-26"),
    ("SSE", "2026-10-28", True, "2026-10-27"),
    ("SSE", "2026-10-29", True, "2026-10-28"),
    ("SSE", "2026-10-30", True, "2026-10-29"),
    ("SSE", "2026-10-31", False, "2026-10-30"),
    ("SSE", "2026-11-01", False, "2026-10-30"),
)


@pytest.mark.parametrize("minute", [False, True])
@pytest.mark.parametrize(
    ("hour", "today_registered"), [(9, False), (16, False), (17, False), (17, True)]
)
def test_real_silver_calendar_preserves_window_and_registration_before_and_after_1600(
    tmp_path, monkeypatch, minute, hour, today_registered,
):
    evaluated_at = datetime(2026, 10, 30, hour, 0, tzinfo=gold_sensor.CN_A_SENSOR_TIMEZONE)
    _freeze_sensor_clock(monkeypatch, evaluated_at)
    expected_window = (
        ("2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30")
        if minute else (
            "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23",
            "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30",
        )
    )
    registered = (
        "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16",
        "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23",
        "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29",
    )
    if today_registered:
        registered = (*registered, "2026-10-30")
    actionable = expected_window if today_registered else expected_window[:-1]
    target = "2026-10-30" if today_registered else "2026-10-29"
    previous = "2026-10-29" if today_registered else "2026-10-28"
    statuses = tuple(_missing(day) if day == target else _ready(day) for day in expected_window)
    calls = _scenario_spies(
        monkeypatch, minute=minute, expected_dates=expected_window,
        statuses=statuses, previous_date=previous, real_calendar=True,
    )
    with _calendar_context(
        tmp_path, registered=registered, calendar_rows=OCTOBER_CALENDAR_ROWS
    ) as context:
        result = _evaluate_gold_sensor(minute=minute, context=context)

        assert len(result.run_requests) == 1
        assert result.run_requests[0].partition_key == target
        assert result.run_requests[0].run_key == (
            f"gold_major_index_mins_nineturn_update:{target}"
            if minute else f"gold_major_index_daily_nineturn_update:{target}"
        )
        payload = _assert_cursor(result, "request_run")
        assert payload["target_date"] == target
        assert calls.readiness == [actionable, (previous,)]
        assert calls.selector == [actionable]
        assert len(calls.loader) == 1
        assert calls.loader[0][0] == gold_sensor.silver_trade_calendar_path(tmp_path)
        assert calls.loader[0][1]["evaluated_at"] == evaluated_at
        _assert_read_only_context(context, minute=minute)


@pytest.mark.parametrize("minute", [False, True])
@pytest.mark.parametrize("on_closed_day", [False, True])
def test_real_calendar_year_boundary_and_closed_days_do_not_create_fake_targets(
    tmp_path, monkeypatch, minute, on_closed_day,
):
    rows = (
        ("SSE", "2026-12-30", True, "2026-12-29"),
        ("SSE", "2026-12-31", True, "2026-12-30"),
        ("SSE", "2027-01-01", False, "2026-12-31"),
        ("SSE", "2027-01-02", False, "2026-12-31"),
        ("SSE", "2027-01-03", False, "2026-12-31"),
        ("SSE", "2027-01-04", True, "2026-12-31"),
    )
    evaluated_at = datetime(
        2027, 1, 3 if on_closed_day else 4, 9, 0, tzinfo=gold_sensor.CN_A_SENSOR_TIMEZONE
    )
    _freeze_sensor_clock(monkeypatch, evaluated_at)
    expected_dates = (
        ("2026-12-30", "2026-12-31") if on_closed_day
        else ("2026-12-30", "2026-12-31", "2027-01-04")
    )
    calls = _scenario_spies(
        monkeypatch, minute=minute, expected_dates=expected_dates,
        statuses=(_ready("2026-12-30"), _missing("2026-12-31")),
        previous_date="2026-12-30", real_calendar=True,
    )
    with _calendar_context(
        tmp_path, registered=("2026-12-30", "2026-12-31"), calendar_rows=rows
    ) as context:
        result = _evaluate_gold_sensor(minute=minute, context=context)

        assert len(result.run_requests) == 1
        assert result.run_requests[0].partition_key == "2026-12-31"
        payload = _assert_cursor(result, "request_run")
        assert payload["target_date"] == "2026-12-31"
        assert calls.readiness == [("2026-12-30", "2026-12-31"), ("2026-12-30",)]
        assert calls.selector == [("2026-12-30", "2026-12-31")]
        assert calls.upstream == [("minute" if minute else "daily", "2026-12-31")]
        assert payload["details"]["evidence"]["registration_gap_class"] == (
            "none" if on_closed_day else "trailing"
        )
        _assert_read_only_context(context, minute=minute)
