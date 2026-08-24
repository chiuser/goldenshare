from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.app.exceptions import WebAppError
from src.foundation.datasets.registry import get_dataset_definition
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.probe_run_log import ProbeRunLog
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.margin_detail_remote_probe_service import (
    MARGIN_DETAIL_REMOTE_READY_CONDITION,
    MARGIN_DETAIL_REQUIRED_SAMPLES,
    MarginDetailRemoteReadinessProbeResult,
    MarginDetailRemoteReadinessProbeService,
)
from src.ops.services.operations_probe_runtime_service import ProbeRuntimeService
from src.ops.services.schedule_automation_capability_resolver import ScheduleAutomationCapabilityResolver


MARGIN_DETAIL_FIELDS = get_dataset_definition("margin_detail").source.source_fields
MARGIN_DETAIL_TARGET_DATE = date(2026, 5, 28)
MARGIN_DETAIL_TARGET_TEXT = "20260528"


def _margin_detail_rule_action(*, filters: dict | None = None, time_input: dict | None = None) -> dict:
    return {
        "action_type": "dataset_action",
        "action_key": "margin_detail.maintain",
        "request": {
            "time_input": time_input or {"mode": "point"},
            "filters": filters or {},
            "run_scope": "probe_triggered",
        },
    }


def _margin_detail_schedule_payload(*, probe_config: dict | None = None, params_json: dict | None = None) -> dict:
    return {
        "target_type": "dataset_action",
        "target_key": "margin_detail.maintain",
        "display_name": "融资融券交易明细源站探测",
        "schedule_type": "cron",
        "trigger_mode": "probe",
        "cron_expr": None,
        "timezone": "Asia/Shanghai",
        "probe_config": probe_config
        or {
            "window_start": "09:00",
            "window_end": "09:30",
            "probe_interval_seconds": 300,
            "max_triggers_per_day": 1,
            "condition_kind": MARGIN_DETAIL_REMOTE_READY_CONDITION,
        },
        "params_json": params_json or {"time_input": {"mode": "point"}, "filters": {}},
    }


def _sample_row(*, ts_code: str, trade_date: object = MARGIN_DETAIL_TARGET_TEXT) -> dict:
    row = {field: None for field in MARGIN_DETAIL_FIELDS}
    row.update({"trade_date": trade_date, "ts_code": ts_code})
    return row


class _FakeTradeCalendarDAO:
    def __init__(self, session) -> None:
        del session

    def get_open_dates(self, exchange, start_date, end_date) -> list[date]:
        del exchange
        del start_date
        del end_date
        return [MARGIN_DETAIL_TARGET_DATE, date(2026, 5, 29)]


def _patch_margin_detail_probe_dependencies(monkeypatch, connector) -> None:
    monkeypatch.setattr(
        "src.ops.services.margin_detail_remote_probe_service.TradeCalendarDAO",
        _FakeTradeCalendarDAO,
    )
    monkeypatch.setattr(
        "src.ops.services.margin_detail_remote_probe_service.create_source_connector",
        lambda source_key: connector,
    )


def test_margin_detail_probe_uses_full_definition_contract_and_all_three_samples(
    db_session,
    probe_rule_factory,
    monkeypatch,
) -> None:
    calls: list[dict] = []

    class FakeConnector:
        def call(self, api_name, *, params, fields):
            calls.append({"api_name": api_name, "params": dict(params), "fields": tuple(fields)})
            return [_sample_row(ts_code=params["ts_code"])]

    _patch_margin_detail_probe_dependencies(monkeypatch, FakeConnector())
    rule = probe_rule_factory(
        dataset_key="margin_detail",
        source_key="tushare",
        probe_condition_json={"type": MARGIN_DETAIL_REMOTE_READY_CONDITION},
        on_success_action_json=_margin_detail_rule_action(),
    )

    result = MarginDetailRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 1, 0, tzinfo=timezone.utc),
    )

    assert result.matched is True
    assert result.payload["target_trade_date"] == "2026-05-28"
    assert result.payload["matched_markets"] == ["SSE", "SZSE", "BSE"]
    assert result.payload["sample_request_count"] == 3
    assert calls == [
        {
            "api_name": "margin_detail",
            "params": {"trade_date": MARGIN_DETAIL_TARGET_TEXT, "ts_code": ts_code, "limit": 1, "offset": 0},
            "fields": MARGIN_DETAIL_FIELDS,
        }
        for _market, ts_code in MARGIN_DETAIL_REQUIRED_SAMPLES
    ]


@pytest.mark.parametrize("invalid_result", ("wrong_date", "wrong_code", "missing_name"))
def test_margin_detail_probe_rejects_inexact_or_incomplete_sample_rows(
    db_session,
    probe_rule_factory,
    monkeypatch,
    invalid_result,
) -> None:
    class FakeConnector:
        def call(self, api_name, *, params, fields):
            del api_name
            del fields
            row = _sample_row(ts_code=params["ts_code"])
            if params["ts_code"] == "920992.BJ":
                if invalid_result == "wrong_date":
                    row["trade_date"] = "20260529"
                elif invalid_result == "wrong_code":
                    row["ts_code"] = "600000.SH"
                else:
                    row.pop("name")
            return [row]

    _patch_margin_detail_probe_dependencies(monkeypatch, FakeConnector())
    rule = probe_rule_factory(
        dataset_key="margin_detail",
        probe_condition_json={"type": MARGIN_DETAIL_REMOTE_READY_CONDITION},
        on_success_action_json=_margin_detail_rule_action(),
    )

    result = MarginDetailRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 1, 0, tzinfo=timezone.utc),
    )

    assert result.matched is False
    assert result.payload["missing_markets"] == ["BSE"]
    assert result.payload["sample_request_count"] == 3


@pytest.mark.parametrize(
    ("previous_open_day", "next_open_day"),
    (
        (date(2026, 5, 29), date(2026, 6, 1)),
        (date(2026, 9, 30), date(2026, 10, 9)),
    ),
)
def test_margin_detail_probe_resolves_previous_open_day_after_non_trading_gap(
    db_session,
    probe_rule_factory,
    monkeypatch,
    previous_open_day,
    next_open_day,
) -> None:
    target_text = previous_open_day.strftime("%Y%m%d")

    class WeekendCalendarDAO:
        def __init__(self, session) -> None:
            del session

        def get_open_dates(self, exchange, start_date, end_date) -> list[date]:
            del exchange
            del start_date
            del end_date
            return [previous_open_day, next_open_day]

    class FakeConnector:
        def call(self, api_name, *, params, fields):
            del api_name
            del fields
            assert params["trade_date"] == target_text
            return [_sample_row(ts_code=params["ts_code"], trade_date=target_text)]

    monkeypatch.setattr("src.ops.services.margin_detail_remote_probe_service.TradeCalendarDAO", WeekendCalendarDAO)
    monkeypatch.setattr(
        "src.ops.services.margin_detail_remote_probe_service.create_source_connector",
        lambda source_key: FakeConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="margin_detail",
        probe_condition_json={"type": MARGIN_DETAIL_REMOTE_READY_CONDITION},
        on_success_action_json=_margin_detail_rule_action(),
    )

    result = MarginDetailRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(next_open_day.year, next_open_day.month, next_open_day.day, 1, 0, tzinfo=timezone.utc),
    )

    assert result.matched is True
    assert result.payload["business_date"] == next_open_day.isoformat()
    assert result.payload["target_trade_date"] == previous_open_day.isoformat()


def test_margin_detail_probe_rejects_tampered_maintenance_filter(probe_rule_factory) -> None:
    rule = probe_rule_factory(
        dataset_key="margin_detail",
        probe_condition_json={"type": MARGIN_DETAIL_REMOTE_READY_CONDITION},
        on_success_action_json=_margin_detail_rule_action(filters={"ts_code": "600000.SH"}),
    )

    with pytest.raises(ValueError, match="不支持维护参数"):
        MarginDetailRemoteReadinessProbeService._validate_rule(rule)


def test_probe_runtime_margin_detail_hit_normalizes_tampered_request_to_full_market_point(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    monkeypatch,
) -> None:
    schedule = ops_schedule_factory(target_key="margin_detail.maintain", trigger_mode="probe")
    rule = probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="margin_detail",
        source_key="tushare",
        probe_condition_json={"type": MARGIN_DETAIL_REMOTE_READY_CONDITION},
        on_success_action_json=_margin_detail_rule_action(
            filters={"ts_code": "600000.SH"},
            time_input={"mode": "range", "start_date": "2026-05-01", "end_date": "2026-05-28"},
        ),
        window_start=None,
        window_end=None,
    )
    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.margin_detail_remote_probe,
        "evaluate",
        lambda session, rule, current: MarginDetailRemoteReadinessProbeResult(
            matched=True,
            message="源站已完整发布融资融券交易明细",
            payload={"target_trade_date": "2026-05-28"},
        ),
    )

    task_runs, result = service.run_once(
        db_session,
        now=datetime(2026, 5, 29, 1, 0, tzinfo=timezone.utc),
        limit=10,
    )

    assert result.triggered_rules == 1
    assert len(task_runs) == 1
    assert task_runs[0].resource_key == "margin_detail"
    assert task_runs[0].time_input_json == {"mode": "point", "trade_date": "2026-05-28"}
    assert task_runs[0].filters_json == {}
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.result_code == "hit"


def test_probe_runtime_margin_detail_miss_creates_no_task_run(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    monkeypatch,
) -> None:
    schedule = ops_schedule_factory(target_key="margin_detail.maintain", trigger_mode="probe")
    rule = probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="margin_detail",
        probe_condition_json={"type": MARGIN_DETAIL_REMOTE_READY_CONDITION},
        on_success_action_json=_margin_detail_rule_action(),
        window_start=None,
        window_end=None,
    )
    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.margin_detail_remote_probe,
        "evaluate",
        lambda session, rule, current: MarginDetailRemoteReadinessProbeResult(
            matched=False,
            message="缺少 BSE",
            payload={"target_trade_date": "2026-05-28", "missing_markets": ["BSE"]},
        ),
    )

    task_runs, result = service.run_once(
        db_session,
        now=datetime(2026, 5, 29, 1, 0, tzinfo=timezone.utc),
        limit=10,
    )

    assert result.triggered_rules == 0
    assert task_runs == []
    assert db_session.scalars(select(TaskRun)).all() == []
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.result_code == "miss"


@pytest.mark.parametrize(
    ("existing_status", "expected_created", "expected_result_code"),
    (("success", 0, "deduplicated"), ("failed", 1, "hit")),
)
def test_probe_runtime_margin_detail_deduplicates_effective_target_and_retries_failed(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    task_run_factory,
    monkeypatch,
    existing_status,
    expected_created,
    expected_result_code,
) -> None:
    schedule = ops_schedule_factory(target_key="margin_detail.maintain", trigger_mode="probe")
    rule = probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="margin_detail",
        probe_condition_json={"type": MARGIN_DETAIL_REMOTE_READY_CONDITION},
        on_success_action_json=_margin_detail_rule_action(),
        window_start=None,
        window_end=None,
    )
    task_run_factory(
        resource_key="margin_detail",
        action="maintain",
        trigger_source="probe",
        schedule_id=schedule.id,
        status=existing_status,
        time_input_json={"mode": "point", "trade_date": "2026-05-28"},
    )
    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.margin_detail_remote_probe,
        "evaluate",
        lambda session, rule, current: MarginDetailRemoteReadinessProbeResult(
            matched=True,
            message="源站已完整发布融资融券交易明细",
            payload={"target_trade_date": "2026-05-28"},
        ),
    )

    task_runs, result = service.run_once(
        db_session,
        now=datetime(2026, 5, 29, 1, 0, tzinfo=timezone.utc),
        limit=10,
    )

    assert result.triggered_rules == expected_created
    assert len(task_runs) == expected_created
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.result_code == expected_result_code


def test_probe_runtime_margin_detail_error_only_records_probe_log(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    monkeypatch,
) -> None:
    schedule = ops_schedule_factory(target_key="margin_detail.maintain", trigger_mode="probe")
    rule = probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="margin_detail",
        probe_condition_json={"type": MARGIN_DETAIL_REMOTE_READY_CONDITION},
        on_success_action_json=_margin_detail_rule_action(),
        window_start=None,
        window_end=None,
    )
    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.margin_detail_remote_probe,
        "evaluate",
        lambda session, rule, current: (_ for _ in ()).throw(RuntimeError("source unavailable")),
    )

    task_runs, result = service.run_once(
        db_session,
        now=datetime(2026, 5, 29, 1, 0, tzinfo=timezone.utc),
        limit=10,
    )

    assert result.triggered_rules == 0
    assert task_runs == []
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.status == "failed"
    assert run_log.result_code == "error"


def test_ops_schedule_margin_detail_probe_creates_fixed_empty_filter_rule(app_client, user_factory, db_session) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
        json=_margin_detail_schedule_payload(),
    )

    assert response.status_code == 200
    schedule_id = response.json()["id"]
    rules = db_session.scalars(select(ProbeRule).where(ProbeRule.schedule_id == schedule_id)).all()
    assert len(rules) == 1
    rule = rules[0]
    assert rule.dataset_key == "margin_detail"
    assert rule.probe_condition_json == {"type": MARGIN_DETAIL_REMOTE_READY_CONDITION}
    assert rule.window_start == "09:00"
    assert rule.window_end == "09:30"
    assert rule.probe_interval_seconds == 300
    assert rule.max_triggers_per_day == 1
    assert rule.on_success_action_json["request"] == {
        "time_input": {"mode": "point"},
        "filters": {},
        "run_scope": "probe_triggered",
    }


@pytest.mark.parametrize(
    ("payload_patch", "expected_code"),
    (
        ({"trigger_mode": "schedule_probe_fallback", "cron_expr": "0 19 * * *"}, "trigger_mode.forbidden"),
        (
            {"target_type": "workflow", "target_key": "daily_market_close_maintenance"},
            "trigger_mode.forbidden",
        ),
        (
            {"params_json": {"time_input": {"mode": "point"}, "filters": {"ts_code": "600000.SH"}}},
            "filters.forbidden",
        ),
        (
            {"params_json": {"time_input": {"mode": "range", "start_date": "2026-05-01", "end_date": "2026-05-28"}, "filters": {}}},
            "time_input.forbidden",
        ),
        ({"calendar_policy": "monthly_last_day"}, "validation_error"),
        (
            {"probe_config": {"window_start": "09:05", "window_end": "09:30", "probe_interval_seconds": 300, "max_triggers_per_day": 1, "condition_kind": MARGIN_DETAIL_REMOTE_READY_CONDITION}},
            "probe_window.forbidden",
        ),
        (
            {"probe_config": {"window_start": "09:00", "window_end": "09:30", "probe_interval_seconds": 600, "max_triggers_per_day": 1, "condition_kind": MARGIN_DETAIL_REMOTE_READY_CONDITION}},
            "probe_config.forbidden",
        ),
        (
            {"probe_config": {"window_start": "09:00", "window_end": "09:30", "probe_interval_seconds": 300, "max_triggers_per_day": 2, "condition_kind": MARGIN_DETAIL_REMOTE_READY_CONDITION}},
            "probe_config.forbidden",
        ),
    ),
)
def test_ops_schedule_margin_detail_probe_rejects_invalid_binding(
    app_client,
    user_factory,
    payload_patch,
    expected_code,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    payload = _margin_detail_schedule_payload()
    payload.update(payload_patch)

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == expected_code


def test_ops_schedule_margin_detail_rejects_generic_freshness_condition(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    payload = _margin_detail_schedule_payload()
    payload["probe_config"] = {"condition_kind": "freshness_latest_open"}

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "condition.unsupported"


def test_schedule_binding_rejects_margin_detail_probe_calendar_policy() -> None:
    schedule = SimpleNamespace(
        trigger_mode="probe",
        schedule_type="cron",
        cron_expr=None,
        next_run_at=None,
        target_type="dataset_action",
        target_key="margin_detail.maintain",
        calendar_policy="monthly_last_day",
        params_json={"time_input": {"mode": "point"}, "filters": {}},
        probe_config_json={
            "window_start": "09:00",
            "window_end": "09:30",
            "probe_interval_seconds": 300,
            "max_triggers_per_day": 1,
            "condition_kind": MARGIN_DETAIL_REMOTE_READY_CONDITION,
        },
        timezone="Asia/Shanghai",
    )

    with pytest.raises(WebAppError, match="日期策略混用"):
        ScheduleAutomationCapabilityResolver().validate_schedule(schedule)
