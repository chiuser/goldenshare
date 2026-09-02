from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.asset_guards.etf_daily_lake_readiness import (
    EtfDailyBatchReadiness,
    EtfDailyPartitionReadiness,
)
from orchestrator.defs.asset_guards.etf_daily_source_probe import (
    EtfDailySourcePublication,
)
from orchestrator.defs.run_contracts.etf_basic import (
    build_etf_basic_silver_snapshot_reference,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_AUTOMATION_CONTRACT_REVISION,
    RAW_FUND_ADJ_SENSOR_NAME,
    RAW_FUND_DAILY_JOB_NAME,
    RAW_FUND_DAILY_SENSOR_NAME,
    SILVER_ETF_ADJ_FACTOR_SENSOR_NAME,
    SILVER_ETF_DAILY_JOB_NAME,
    SILVER_ETF_DAILY_SENSOR_NAME,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SENSOR_DOMAIN_TAG,
    SENSOR_ROLE_TAG,
    SENSOR_TARGET_LAYER_TAG,
)
from orchestrator.defs.sensors import etf_daily_sensor
from orchestrator.defs.sensors.etf_daily_sensor import (
    evaluate_raw_fund_adj_sensor,
    evaluate_raw_fund_daily_sensor,
    evaluate_silver_etf_adj_factor_sensor,
    evaluate_silver_etf_daily_sensor,
    raw_fund_adj_update_job_sensor,
    raw_fund_daily_update_job_sensor,
    silver_etf_adj_factor_update_job_sensor,
    silver_etf_daily_update_job_sensor,
)

NOW = datetime(2026, 9, 2, 21, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
BEFORE_WINDOW = datetime(
    2026,
    9,
    2,
    20,
    59,
    59,
    tzinfo=ZoneInfo("Asia/Shanghai"),
)
TRADE_DATES = ("2026-08-31", "2026-09-01", "2026-09-02")


class _ForbiddenContext:
    @property
    def resources(self):  # type: ignore[no-untyped-def]
        raise AssertionError("before-window evaluation must not access resources")

    @property
    def instance(self):  # type: ignore[no-untyped-def]
        raise AssertionError("before-window evaluation must not access Dagster")


class _FakeDuckDB:
    @contextmanager
    def connect(self):  # type: ignore[no-untyped-def]
        yield object()


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        instance=SimpleNamespace(),
        resources=SimpleNamespace(
            lake_root=SimpleNamespace(
                ensure_available_for_run=lambda: None,
                root=lambda: Path("/isolated/lake"),
            ),
            duckdb=_FakeDuckDB(),
            tushare=object(),
        ),
    )


def _window_and_gap(*, registered: tuple[str, ...] = TRADE_DATES):
    window = ContinuityExpectedDateWindow(
        expected_trade_dates=TRADE_DATES,
        min_trade_date="2025-01-01",
        max_trade_date=TRADE_DATES[-1],
        evaluated_at=NOW,
        window_limit=10,
    )
    gap = build_registered_gap_status(
        expected_trade_dates=TRADE_DATES,
        registered_trade_dates=registered,
    )
    return window, gap


def _status(
    *,
    asset_key: str,
    trade_date: str,
    state: str,
) -> EtfDailyPartitionReadiness:
    if state == "ready":
        return EtfDailyPartitionReadiness(
            asset_key=asset_key,
            trade_date=trade_date,
            ready=True,
            materialized=True,
            file_exists=True,
            checks_passed=True,
            reason_code="ready",
            row_count=1,
            content_hash="a" * 64,
        )
    if state == "invalid":
        return EtfDailyPartitionReadiness(
            asset_key=asset_key,
            trade_date=trade_date,
            ready=False,
            materialized=True,
            file_exists=True,
            checks_passed=False,
            reason_code="materialized_check_failed",
            row_count=1,
            content_hash="a" * 64,
        )
    return EtfDailyPartitionReadiness(
        asset_key=asset_key,
        trade_date=trade_date,
        ready=False,
        materialized=False,
        file_exists=False,
        checks_passed=False,
        reason_code="missing",
        row_count=None,
        content_hash=None,
    )


def _batch(asset_key: str, *states: str) -> EtfDailyBatchReadiness:
    return EtfDailyBatchReadiness(
        asset_key=asset_key,
        statuses=tuple(
            _status(asset_key=asset_key, trade_date=trade_date, state=state)
            for trade_date, state in zip(TRADE_DATES, states, strict=True)
        ),
        materialization_query_count=1,
        elapsed_ms=2,
    )


def _publication(trade_date: str, *, ready: bool = True):  # type: ignore[no-untyped-def]
    return EtfDailySourcePublication(
        api_name="fund_daily",
        trade_date=trade_date,
        ready=ready,
        reason_code="ready" if ready else "source_not_published",
        row_count=1 if ready else 0,
        observed_columns=(),
        elapsed_ms=1.0,
    )


def _basic_reference():  # type: ignore[no-untyped-def]
    return build_etf_basic_silver_snapshot_reference(
        raw_snapshot_hash="a" * 64,
        silver_content_hash="b" * 64,
        raw_uri="/isolated/raw-basic.parquet",
        silver_uri="/isolated/silver-basic.parquet",
        raw_observed_at="2026-09-02T20:55:00+08:00",
        silver_observed_at="2026-09-02T20:56:00+08:00",
        eligibility_as_of="2026-09-02",
        requestable_code_count=1,
        requestable_code_hash="c" * 64,
    )


def _patch_window(monkeypatch, *, registered: tuple[str, ...] = TRADE_DATES) -> None:  # type: ignore[no-untyped-def]
    window, gap = _window_and_gap(registered=registered)
    monkeypatch.setattr(
        etf_daily_sensor,
        "_window_and_registration",
        lambda *args, **kwargs: (window, gap),
    )


def test_all_four_evaluators_skip_before_2100_without_any_state_access() -> None:
    context = _ForbiddenContext()
    results = (
        evaluate_raw_fund_daily_sensor(context, evaluated_at=BEFORE_WINDOW),  # type: ignore[arg-type]
        evaluate_raw_fund_adj_sensor(context, evaluated_at=BEFORE_WINDOW),  # type: ignore[arg-type]
        evaluate_silver_etf_daily_sensor(context, evaluated_at=BEFORE_WINDOW),  # type: ignore[arg-type]
        evaluate_silver_etf_adj_factor_sensor(  # type: ignore[arg-type]
            context,
            evaluated_at=BEFORE_WINDOW,
        ),
    )
    assert all(not result.run_requests for result in results)
    assert all("21:00" in str(result.skip_reason) for result in results)


def test_public_evaluators_are_bound_to_their_exact_job_specs(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    observed: list[tuple[str, str]] = []
    sentinel = dg.SensorResult(skip_reason="bound")

    def raw(context, *, spec, evaluated_at):  # type: ignore[no-untyped-def]
        observed.append((spec.sensor_name, spec.job_name))
        return sentinel

    def silver(context, *, spec, evaluated_at):  # type: ignore[no-untyped-def]
        observed.append((spec.sensor_name, spec.job_name))
        return sentinel

    monkeypatch.setattr(etf_daily_sensor, "_evaluate_raw", raw)
    monkeypatch.setattr(etf_daily_sensor, "_evaluate_silver", silver)
    context = _ForbiddenContext()
    evaluate_raw_fund_daily_sensor(context, evaluated_at=NOW)  # type: ignore[arg-type]
    evaluate_raw_fund_adj_sensor(context, evaluated_at=NOW)  # type: ignore[arg-type]
    evaluate_silver_etf_daily_sensor(context, evaluated_at=NOW)  # type: ignore[arg-type]
    evaluate_silver_etf_adj_factor_sensor(context, evaluated_at=NOW)  # type: ignore[arg-type]
    assert observed == [
        ("raw_fund_daily_update_job_sensor", "raw_fund_daily_update_job"),
        ("raw_fund_adj_update_job_sensor", "raw_fund_adj_update_job"),
        ("silver_etf_daily_update_job_sensor", "silver_etf_daily_update_job"),
        (
            "silver_etf_adj_factor_update_job_sensor",
            "silver_etf_adj_factor_update_job",
        ),
    ]


def test_2100_enters_the_window_and_registration_path(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    entered = 0

    def window_path(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal entered
        entered += 1
        raise RuntimeError("window_path_entered")

    monkeypatch.setattr(etf_daily_sensor, "_window_and_registration", window_path)
    result = evaluate_raw_fund_daily_sensor(_context(), evaluated_at=NOW)  # type: ignore[arg-type]
    assert entered == 1
    assert not result.run_requests
    assert "fail-closed" in str(result.skip_reason)


def test_window_loader_clips_to_last_ten_and_checks_shared_registration() -> None:
    calendar_dates = tuple(
        f"2026-08-{day:02d}" for day in range(17, 28)
    )

    class CalendarConnection:
        def execute(self, query, params):  # type: ignore[no-untyped-def]
            assert params[-1] == NOW.date().isoformat()
            return SimpleNamespace(fetchall=lambda: [(value,) for value in calendar_dates])

    context = SimpleNamespace(
        instance=SimpleNamespace(
            get_dynamic_partitions=lambda name: list(calendar_dates),
        ),
        resources=SimpleNamespace(
            lake_root=SimpleNamespace(root=lambda: Path("/isolated/lake")),
        ),
    )
    window, gap = etf_daily_sensor._window_and_registration(  # type: ignore[arg-type]
        context,
        connection=CalendarConnection(),
        evaluated_at=NOW,
    )
    assert window.expected_trade_dates == calendar_dates[-10:]
    assert window.window_limit == 10
    assert gap.ready


def test_raw_selects_earliest_missing_date_after_one_publication_probe(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    _patch_window(monkeypatch)
    probe_dates: list[str] = []
    readiness_calls = 0

    def readiness(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal readiness_calls
        readiness_calls += 1
        return _batch("raw_tushare_fund_daily", "ready", "missing", "missing")

    def probe(tushare, trade_date):  # type: ignore[no-untyped-def]
        probe_dates.append(trade_date)
        return _publication(trade_date)

    monkeypatch.setattr(
        etf_daily_sensor,
        "_RAW_FUND_DAILY_SPEC",
        replace(
            etf_daily_sensor._RAW_FUND_DAILY_SPEC,
            readiness=readiness,
            publication_probe=probe,
        ),
    )
    result = evaluate_raw_fund_daily_sensor(_context(), evaluated_at=NOW)  # type: ignore[arg-type]

    assert readiness_calls == 1
    assert probe_dates == ["2026-09-01"]
    assert len(result.run_requests) == 1
    request = result.run_requests[0]
    assert request.partition_key == "2026-09-01"
    assert request.run_key == (
        f"{RAW_FUND_DAILY_JOB_NAME}:2026-09-01:"
        f"{ETF_DAILY_AUTOMATION_CONTRACT_REVISION}"
    )
    assert request.run_config == {}
    assert len(result.cursor.encode("utf-8")) < 3_072


def test_raw_existing_invalid_partition_blocks_without_source_probe(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    _patch_window(monkeypatch)
    monkeypatch.setattr(
        etf_daily_sensor,
        "_RAW_FUND_DAILY_SPEC",
        replace(
            etf_daily_sensor._RAW_FUND_DAILY_SPEC,
            readiness=lambda **kwargs: _batch(
                "raw_tushare_fund_daily", "ready", "invalid", "missing"
            ),
            publication_probe=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("must not probe source")
            ),
        ),
    )
    result = evaluate_raw_fund_daily_sensor(_context(), evaluated_at=NOW)  # type: ignore[arg-type]
    assert not result.run_requests
    assert "拒绝自动覆盖" in str(result.skip_reason)


def test_raw_all_ready_skips_without_source_probe(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_window(monkeypatch)
    monkeypatch.setattr(
        etf_daily_sensor,
        "_RAW_FUND_DAILY_SPEC",
        replace(
            etf_daily_sensor._RAW_FUND_DAILY_SPEC,
            readiness=lambda **kwargs: _batch(
                "raw_tushare_fund_daily", "ready", "ready", "ready"
            ),
            publication_probe=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("must not probe source")
            ),
        ),
    )
    result = evaluate_raw_fund_daily_sensor(_context(), evaluated_at=NOW)  # type: ignore[arg-type]
    assert not result.run_requests
    assert "ready" in str(result.skip_reason)


def test_unpublished_raw_has_no_run_key_and_is_probed_again_next_tick(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    _patch_window(monkeypatch)
    probe_count = 0

    def probe(tushare, trade_date):  # type: ignore[no-untyped-def]
        nonlocal probe_count
        probe_count += 1
        return _publication(trade_date, ready=False)

    monkeypatch.setattr(
        etf_daily_sensor,
        "_RAW_FUND_DAILY_SPEC",
        replace(
            etf_daily_sensor._RAW_FUND_DAILY_SPEC,
            readiness=lambda **kwargs: _batch(
                "raw_tushare_fund_daily", "ready", "missing", "missing"
            ),
            publication_probe=probe,
        ),
    )
    first = evaluate_raw_fund_daily_sensor(_context(), evaluated_at=NOW)  # type: ignore[arg-type]
    second = evaluate_raw_fund_daily_sensor(_context(), evaluated_at=NOW)  # type: ignore[arg-type]
    assert not first.run_requests and not second.run_requests
    assert probe_count == 2
    assert "run_key" not in first.cursor


def test_unregistered_date_stops_before_readiness(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_window(monkeypatch, registered=TRADE_DATES[:1])
    monkeypatch.setattr(
        etf_daily_sensor,
        "_RAW_FUND_DAILY_SPEC",
        replace(
            etf_daily_sensor._RAW_FUND_DAILY_SPEC,
            readiness=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("must not evaluate readiness")
            ),
        ),
    )
    result = evaluate_raw_fund_daily_sensor(_context(), evaluated_at=NOW)  # type: ignore[arg-type]
    assert not result.run_requests
    assert "分区注册" in str(result.skip_reason)


def test_silver_stops_at_raw_gap_and_never_selects_basic(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_window(monkeypatch)
    monkeypatch.setattr(
        etf_daily_sensor,
        "_SILVER_ETF_DAILY_SPEC",
        replace(
            etf_daily_sensor._SILVER_ETF_DAILY_SPEC,
            raw_readiness=lambda **kwargs: _batch(
                "raw_tushare_fund_daily", "ready", "missing", "ready"
            ),
            silver_readiness=lambda **kwargs: _batch(
                "silver_etf_daily", "ready", "missing", "missing"
            ),
        ),
    )
    monkeypatch.setattr(
        etf_daily_sensor,
        "select_latest_etf_basic_snapshot_reference",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not select Basic")),
    )
    result = evaluate_silver_etf_daily_sensor(_context(), evaluated_at=NOW)  # type: ignore[arg-type]
    assert not result.run_requests
    assert "不越过" in str(result.skip_reason)


def test_silver_latest_basic_failure_is_fail_closed_without_fallback(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    _patch_window(monkeypatch)
    monkeypatch.setattr(
        etf_daily_sensor,
        "_SILVER_ETF_DAILY_SPEC",
        replace(
            etf_daily_sensor._SILVER_ETF_DAILY_SPEC,
            raw_readiness=lambda **kwargs: _batch(
                "raw_tushare_fund_daily", "ready", "ready", "ready"
            ),
            silver_readiness=lambda **kwargs: _batch(
                "silver_etf_daily", "ready", "missing", "missing"
            ),
        ),
    )
    selector_calls = 0

    def fail_latest(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal selector_calls
        selector_calls += 1
        raise RuntimeError("latest failed")

    monkeypatch.setattr(
        etf_daily_sensor,
        "select_latest_etf_basic_snapshot_reference",
        fail_latest,
    )
    result = evaluate_silver_etf_daily_sensor(_context(), evaluated_at=NOW)  # type: ignore[arg-type]
    assert selector_calls == 1
    assert not result.run_requests
    assert "不回退旧版本" in str(result.skip_reason)


def test_existing_invalid_silver_blocks_before_basic_selection(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_window(monkeypatch)
    monkeypatch.setattr(
        etf_daily_sensor,
        "_SILVER_ETF_DAILY_SPEC",
        replace(
            etf_daily_sensor._SILVER_ETF_DAILY_SPEC,
            raw_readiness=lambda **kwargs: _batch(
                "raw_tushare_fund_daily", "ready", "ready", "ready"
            ),
            silver_readiness=lambda **kwargs: _batch(
                "silver_etf_daily", "ready", "invalid", "missing"
            ),
        ),
    )
    monkeypatch.setattr(
        etf_daily_sensor,
        "select_latest_etf_basic_snapshot_reference",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not select Basic")),
    )
    result = evaluate_silver_etf_daily_sensor(_context(), evaluated_at=NOW)  # type: ignore[arg-type]
    assert not result.run_requests
    assert "拒绝自动覆盖" in str(result.skip_reason)


def test_silver_selects_earliest_gap_with_stable_key_and_two_lineage_queries(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    _patch_window(monkeypatch)
    monkeypatch.setattr(
        etf_daily_sensor,
        "_SILVER_ETF_DAILY_SPEC",
        replace(
            etf_daily_sensor._SILVER_ETF_DAILY_SPEC,
            raw_readiness=lambda **kwargs: _batch(
                "raw_tushare_fund_daily", "ready", "ready", "ready"
            ),
            silver_readiness=lambda **kwargs: _batch(
                "silver_etf_daily", "ready", "missing", "missing"
            ),
        ),
    )
    monkeypatch.setattr(
        etf_daily_sensor,
        "select_latest_etf_basic_snapshot_reference",
        lambda **kwargs: _basic_reference(),
    )
    result = evaluate_silver_etf_daily_sensor(_context(), evaluated_at=NOW)  # type: ignore[arg-type]
    assert len(result.run_requests) == 1
    request = result.run_requests[0]
    assert request.partition_key == "2026-09-01"
    assert request.run_key == (
        f"{SILVER_ETF_DAILY_JOB_NAME}:2026-09-01:"
        f"{ETF_DAILY_AUTOMATION_CONTRACT_REVISION}"
    )
    cursor = json.loads(result.cursor)
    assert cursor["details"]["runtime_state"]["materialization_query_count"] == 2
    assert len(result.cursor.encode("utf-8")) < 3_072


def test_four_definitions_are_stopped_tagged_and_resource_bounded() -> None:
    sensors = (
        raw_fund_daily_update_job_sensor,
        raw_fund_adj_update_job_sensor,
        silver_etf_daily_update_job_sensor,
        silver_etf_adj_factor_update_job_sensor,
    )
    assert tuple(sensor.name for sensor in sensors) == (
        RAW_FUND_DAILY_SENSOR_NAME,
        RAW_FUND_ADJ_SENSOR_NAME,
        SILVER_ETF_DAILY_SENSOR_NAME,
        SILVER_ETF_ADJ_FACTOR_SENSOR_NAME,
    )
    assert all(
        sensor.default_status is dg.DefaultSensorStatus.STOPPED for sensor in sensors
    )
    assert all(sensor.minimum_interval_seconds == 600 for sensor in sensors)
    assert all(sensor.tags[SENSOR_DOMAIN_TAG] == "quote_data" for sensor in sensors)
    assert all(sensor.tags[SENSOR_ROLE_TAG] == "asset_update" for sensor in sensors)
    assert [sensor.tags[SENSOR_TARGET_LAYER_TAG] for sensor in sensors] == [
        "raw",
        "raw",
        "silver",
        "silver",
    ]
    assert raw_fund_daily_update_job_sensor.required_resource_keys == {
        "lake_root",
        "duckdb",
        "tushare",
    }
    assert silver_etf_daily_update_job_sensor.required_resource_keys == {
        "lake_root",
        "duckdb",
    }
