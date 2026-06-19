from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.ops.models.ops.probe_run_log import ProbeRunLog
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.operations_probe_runtime_service import ProbeRuntimeService
from src.ops.services.stk_mins_remote_probe_service import (
    STK_MINS_REMOTE_READY_CONDITION,
    StkMinsRemoteReadinessProbeResult,
    StkMinsRemoteReadinessProbeService,
)


def test_ops_probe_list_rejects_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/probes", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_probe_create_list_update_pause_resume_delete(app_client, user_factory, db_session) -> None:
    from sqlalchemy import select

    from src.ops.models.ops.config_revision import ConfigRevision

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    create = app_client.post(
        "/api/v1/ops/probes",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "收盘后日线探测",
            "dataset_key": "daily",
            "source_key": "tushare",
            "window_start": "15:30",
            "window_end": "17:30",
            "probe_interval_seconds": 180,
            "probe_condition_json": {"metric": "max_trade_date", "op": ">=", "value": "today"},
            "on_success_action_json": {"action_type": "workflow", "action_key": "daily_market_close_maintenance"},
            "max_triggers_per_day": 2,
            "timezone_name": "Asia/Shanghai",
        },
    )
    assert create.status_code == 200
    created = create.json()
    probe_rule_id = created["id"]
    assert created["status"] == "active"
    assert created["dataset_key"] == "daily"
    assert created["probe_interval_seconds"] == 180
    assert created["created_by_username"] == "admin"

    listed = app_client.get("/api/v1/ops/probes?dataset_key=daily", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["total"] == 1
    assert listed_payload["items"][0]["id"] == probe_rule_id
    assert listed_payload["items"][0]["source_display_name"] == "Tushare"

    updated = app_client.patch(
        f"/api/v1/ops/probes/{probe_rule_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "收盘后探测（更新）", "probe_interval_seconds": 120},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "收盘后探测（更新）"
    assert updated.json()["probe_interval_seconds"] == 120

    paused = app_client.post(f"/api/v1/ops/probes/{probe_rule_id}/pause", headers={"Authorization": f"Bearer {token}"})
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = app_client.post(f"/api/v1/ops/probes/{probe_rule_id}/resume", headers={"Authorization": f"Bearer {token}"})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "active"

    deleted = app_client.delete(f"/api/v1/ops/probes/{probe_rule_id}", headers={"Authorization": f"Bearer {token}"})
    assert deleted.status_code == 200
    assert deleted.json()["id"] == probe_rule_id
    assert deleted.json()["status"] == "deleted"

    detail_after_delete = app_client.get(f"/api/v1/ops/probes/{probe_rule_id}", headers={"Authorization": f"Bearer {token}"})
    assert detail_after_delete.status_code == 404
    assert detail_after_delete.json()["code"] == "not_found"
    assert detail_after_delete.json()["message"] == "探测规则不存在"

    revisions = list(
        db_session.scalars(
            select(ConfigRevision)
            .where(ConfigRevision.object_type == "probe_rule")
            .where(ConfigRevision.object_id == str(probe_rule_id))
            .order_by(ConfigRevision.id.asc())
        )
    )
    assert [item.action for item in revisions] == ["created", "updated", "paused", "resumed", "deleted"]


def test_ops_probe_create_returns_readable_validation_message(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/probes",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "",
            "dataset_key": "daily",
            "source_key": "tushare",
            "window_start": "15:30",
            "window_end": "17:30",
            "probe_interval_seconds": 180,
            "probe_condition_json": {},
            "on_success_action_json": {"action_type": "dataset_action", "action_key": "daily.maintain"},
            "max_triggers_per_day": 2,
            "timezone_name": "Asia/Shanghai",
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "探测规则名称不能为空"


def test_ops_probe_create_rejects_invalid_remote_stk_mins_condition(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/probes",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "错误分钟源站探测",
            "dataset_key": "daily",
            "source_key": "tushare",
            "window_start": "15:30",
            "window_end": "17:30",
            "probe_interval_seconds": 180,
            "probe_condition_json": {"type": STK_MINS_REMOTE_READY_CONDITION},
            "on_success_action_json": {
                "action_type": "dataset_action",
                "action_key": "daily.maintain",
                "request": {"time_input": {"mode": "point"}, "filters": {}},
            },
            "max_triggers_per_day": 2,
            "timezone_name": "Asia/Shanghai",
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "源站分钟行情探测只支持股票历史分钟行情维护"


def test_ops_probe_run_log_list_supports_rule_and_dataset_filters(
    app_client,
    user_factory,
    probe_rule_factory,
    probe_run_log_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    equity_rule = probe_rule_factory(name="股票日线探测", dataset_key="daily", source_key="tushare")
    biying_rule = probe_rule_factory(name="Biying 股票日线探测", dataset_key="biying_equity_daily", source_key="biying")

    probe_run_log_factory(
        probe_rule_id=equity_rule.id,
        status="success",
        condition_matched=True,
        message="hit",
        payload_json={"max_trade_date": "2026-04-14"},
        triggered_task_run_id=101,
    )
    probe_run_log_factory(
        probe_rule_id=biying_rule.id,
        status="failed",
        condition_matched=False,
        message="timeout",
        payload_json={"error": "timeout"},
    )

    all_runs = app_client.get("/api/v1/ops/probes/runs", headers={"Authorization": f"Bearer {token}"})
    assert all_runs.status_code == 200
    all_payload = all_runs.json()
    assert all_payload["total"] == 2
    assert {item["dataset_key"] for item in all_payload["items"]} == {"daily", "biying_equity_daily"}

    by_rule = app_client.get(f"/api/v1/ops/probes/{equity_rule.id}/runs", headers={"Authorization": f"Bearer {token}"})
    assert by_rule.status_code == 200
    by_rule_payload = by_rule.json()
    assert by_rule_payload["total"] == 1
    assert by_rule_payload["items"][0]["probe_rule_id"] == equity_rule.id
    assert by_rule_payload["items"][0]["status"] == "success"
    assert by_rule_payload["items"][0]["source_display_name"] == "Tushare"
    assert by_rule_payload["items"][0]["rule_version"] == 1
    assert by_rule_payload["items"][0]["result_code"] in {"miss", "hit", "error"}

    by_dataset = app_client.get(
        "/api/v1/ops/probes/runs?dataset_key=biying_equity_daily",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert by_dataset.status_code == 200
    by_dataset_payload = by_dataset.json()
    assert by_dataset_payload["total"] == 1
    assert by_dataset_payload["items"][0]["dataset_key"] == "biying_equity_daily"
    assert by_dataset_payload["items"][0]["status"] == "failed"
    assert by_dataset_payload["items"][0]["rule_version"] == 1


def test_probe_runtime_requires_explicit_action_key(db_session, probe_rule_factory) -> None:
    rule = probe_rule_factory(
        name="股票日线探测",
        dataset_key="daily",
        on_success_action_json={
            "action_type": "dataset_action",
            "request": {"time_input": {"mode": "point"}, "filters": {}},
        },
    )

    with pytest.raises(ValueError, match="探测触发动作缺少 action_key"):
        ProbeRuntimeService()._enqueue_on_match(db_session, rule)


def test_probe_runtime_uses_action_key_as_dataset_action_fact(db_session, probe_rule_factory) -> None:
    rule = probe_rule_factory(
        name="股票日线探测",
        dataset_key="stock_basic",
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "daily.maintain",
            "request": {
                "time_input": {"mode": "point", "trade_date": "2026-04-24"},
                "filters": {},
                "run_scope": "probe_triggered",
            },
        },
    )

    task_run = ProbeRuntimeService()._enqueue_on_match(db_session, rule)

    assert task_run.resource_key == "daily"
    assert task_run.action == "maintain"
    assert task_run.request_payload_json["resource_key"] == "daily"


def test_stk_mins_remote_probe_uses_default_listed_tushare_sample_codes(db_session, monkeypatch) -> None:
    class FakeSecurityDAO:
        def __init__(self, session):
            del session

        def get_by_ts_code(self, ts_code):
            if ts_code == "600000.SH":
                return SimpleNamespace(source="tushare", list_status="L")
            if ts_code == "000001.SZ":
                return SimpleNamespace(source="other", list_status="L")
            if ts_code == "300750.SZ":
                return SimpleNamespace(source="tushare", list_status="D")
            return None

    monkeypatch.setattr("src.ops.services.stk_mins_remote_probe_service.SecurityDAO", FakeSecurityDAO)

    samples = StkMinsRemoteReadinessProbeService._resolve_sample_codes(db_session, {})

    assert samples == ["600000.SH"]


def test_stk_mins_remote_probe_rejects_direct_non_stk_rule(db_session, probe_rule_factory) -> None:
    rule = probe_rule_factory(
        dataset_key="daily",
        source_key=None,
        probe_condition_json={"type": STK_MINS_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "daily.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {},
                "run_scope": "probe_triggered",
            },
        },
    )

    with pytest.raises(ValueError, match="源站分钟行情探测只支持股票历史分钟行情维护"):
        StkMinsRemoteReadinessProbeService().evaluate(
            db_session,
            rule,
            current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
        )


def test_stk_mins_remote_probe_builds_sample_request_from_resolver(db_session, probe_rule_factory, monkeypatch) -> None:
    class FakeTradeCalendarDAO:
        def __init__(self, session):
            del session

        def fetch_by_pk(self, exchange, business_date):
            del exchange
            del business_date
            return SimpleNamespace(is_open=True, pretrade_date=date(2026, 5, 28))

    class FakeDAOFactory:
        def __init__(self, session):
            del session
            self.security = SimpleNamespace(get_by_ts_code=lambda code: SimpleNamespace(name="浦发银行"))

    calls: list[dict] = []

    class FakeConnector:
        def call(self, api_name, params=None, fields=None):
            calls.append({"api_name": api_name, "params": dict(params or {}), "fields": tuple(fields or ())})
            return [{"ts_code": "600000.SH", "trade_time": "2026-05-29 15:00:00"}]

    monkeypatch.setattr("src.ops.services.stk_mins_remote_probe_service.TradeCalendarDAO", FakeTradeCalendarDAO)
    monkeypatch.setattr("src.foundation.ingestion.unit_planner.DAOFactory", FakeDAOFactory)
    monkeypatch.setattr(
        "src.ops.services.stk_mins_remote_probe_service.create_source_connector",
        lambda _source_key: FakeConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="stk_mins",
        source_key=None,
        probe_condition_json={"type": STK_MINS_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "stk_mins.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"ts_code": "600000.SH", "freq": ["1min"], "source_key": "tushare"},
                "run_scope": "probe_triggered",
            },
        },
    )

    result = StkMinsRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
    )

    assert result.matched is True
    assert result.payload["latest_open_date"] == "2026-05-29"
    assert result.payload["checked_freqs"] == ["1min"]
    assert result.payload["matched_freqs"] == ["1min"]
    assert result.payload["sample_codes"] == ["600000.SH"]
    assert calls == [
        {
            "api_name": "stk_mins",
            "params": {
                "ts_code": "600000.SH",
                "freq": "1min",
                "start_date": "2026-05-29 09:00:00",
                "end_date": "2026-05-29 19:00:00",
                "limit": 1,
                "offset": 0,
            },
            "fields": ("ts_code", "trade_time"),
        }
    ]


def test_stk_mins_remote_probe_skips_closed_business_date(
    db_session,
    probe_rule_factory,
    trade_calendar_factory,
    monkeypatch,
) -> None:
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 6, 18), is_open=True)
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 6, 19), is_open=False, pretrade_date=date(2026, 6, 18))
    connector_calls: list[dict] = []

    def create_connector(_source_key):
        connector_calls.append({"source_key": _source_key})
        raise AssertionError("closed business date must not call Tushare")

    monkeypatch.setattr("src.ops.services.stk_mins_remote_probe_service.create_source_connector", create_connector)
    rule = probe_rule_factory(
        dataset_key="stk_mins",
        source_key=None,
        probe_condition_json={"type": STK_MINS_REMOTE_READY_CONDITION, "exchange": "SSE"},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "stk_mins.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"ts_code": "600000.SH", "freq": ["1min"]},
                "run_scope": "probe_triggered",
            },
        },
    )

    result = StkMinsRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 6, 19, 9, 0, tzinfo=timezone.utc),
    )

    assert result.matched is False
    assert result.message == "2026-06-19 非交易日，已跳过源站分钟行情探测"
    assert result.payload["business_date"] == "2026-06-19"
    assert result.payload["is_open"] is False
    assert result.payload["pretrade_date"] == "2026-06-18"
    assert result.payload["latest_open_date"] is None
    assert result.payload["sample_request_count"] == 0
    assert result.payload["checked_freqs"] == []
    assert result.payload["matched_freqs"] == []
    assert result.payload["sample_codes"] == []
    assert connector_calls == []


def test_stk_mins_remote_probe_skips_missing_business_calendar(
    db_session,
    probe_rule_factory,
    monkeypatch,
) -> None:
    connector_calls: list[dict] = []

    def create_connector(_source_key):
        connector_calls.append({"source_key": _source_key})
        raise AssertionError("missing business calendar must not call Tushare")

    monkeypatch.setattr("src.ops.services.stk_mins_remote_probe_service.create_source_connector", create_connector)
    rule = probe_rule_factory(
        dataset_key="stk_mins",
        source_key=None,
        probe_condition_json={"type": STK_MINS_REMOTE_READY_CONDITION, "exchange": "SSE"},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "stk_mins.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"ts_code": "600000.SH", "freq": ["1min"]},
                "run_scope": "probe_triggered",
            },
        },
    )

    result = StkMinsRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 6, 19, 9, 0, tzinfo=timezone.utc),
    )

    assert result.matched is False
    assert result.message == "交易日历缺少 2026-06-19 记录，已跳过源站分钟行情探测"
    assert result.payload["business_date"] == "2026-06-19"
    assert result.payload["is_open"] is None
    assert result.payload["pretrade_date"] is None
    assert result.payload["latest_open_date"] is None
    assert result.payload["sample_request_count"] == 0
    assert result.payload["checked_freqs"] == []
    assert result.payload["matched_freqs"] == []
    assert result.payload["sample_codes"] == []
    assert connector_calls == []


def test_stk_mins_remote_probe_requires_all_selected_freqs(db_session, probe_rule_factory, monkeypatch) -> None:
    class FakeTradeCalendarDAO:
        def __init__(self, session):
            del session

        def fetch_by_pk(self, exchange, business_date):
            del exchange
            del business_date
            return SimpleNamespace(is_open=True, pretrade_date=date(2026, 5, 28))

    class FakeDAOFactory:
        def __init__(self, session):
            del session
            self.security = SimpleNamespace(get_by_ts_code=lambda code: SimpleNamespace(name="浦发银行"))

    class FakeConnector:
        def call(self, api_name, params=None, fields=None):
            del api_name
            del fields
            if (params or {}).get("freq") == "1min":
                return [{"ts_code": "600000.SH", "trade_time": "2026-05-29 15:00:00"}]
            return []

    monkeypatch.setattr("src.ops.services.stk_mins_remote_probe_service.TradeCalendarDAO", FakeTradeCalendarDAO)
    monkeypatch.setattr("src.foundation.ingestion.unit_planner.DAOFactory", FakeDAOFactory)
    monkeypatch.setattr(
        "src.ops.services.stk_mins_remote_probe_service.create_source_connector",
        lambda _source_key: FakeConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="stk_mins",
        source_key=None,
        probe_condition_json={"type": STK_MINS_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "stk_mins.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"ts_code": "600000.SH", "freq": ["1min", "5min"]},
                "run_scope": "probe_triggered",
            },
        },
    )

    result = StkMinsRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
    )

    assert result.matched is False
    assert result.payload["checked_freqs"] == ["1min", "5min"]
    assert result.payload["matched_freqs"] == ["1min"]
    assert result.payload["sample_request_count"] == 2


def test_probe_runtime_remote_stk_mins_hit_creates_task_run_with_latest_open_date(db_session, probe_rule_factory, monkeypatch) -> None:
    rule = probe_rule_factory(
        dataset_key="stk_mins",
        source_key="tushare",
        probe_condition_json={"type": STK_MINS_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "stk_mins.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"freq": ["1min"], "source_key": "tushare"},
                "run_scope": "probe_triggered",
            },
        },
    )

    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.stk_mins_remote_probe,
        "evaluate",
        lambda session, rule, current: StkMinsRemoteReadinessProbeResult(
            matched=True,
            message="源站已返回目标交易日分钟行情",
            payload={"latest_open_date": "2026-05-29"},
        ),
    )

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 1
    assert len(task_runs) == 1
    task_run = task_runs[0]
    assert task_run.resource_key == "stk_mins"
    assert task_run.time_input_json == {"mode": "point", "trade_date": "2026-05-29"}
    assert task_run.filters_json == {"freq": ["1min"]}
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.condition_matched is True
    assert db_session.scalar(select(TaskRun).where(TaskRun.id == task_run.id)) is not None


def test_probe_runtime_remote_stk_mins_miss_does_not_create_task_run(db_session, probe_rule_factory, monkeypatch) -> None:
    probe_rule_factory(
        dataset_key="stk_mins",
        source_key=None,
        probe_condition_json={"type": STK_MINS_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "stk_mins.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"freq": ["1min"]},
                "run_scope": "probe_triggered",
            },
        },
    )

    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.stk_mins_remote_probe,
        "evaluate",
        lambda session, rule, current: StkMinsRemoteReadinessProbeResult(
            matched=False,
            message="源站尚未返回 1min 的最新交易日分钟行情",
            payload={"latest_open_date": "2026-05-29"},
        ),
    )

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 0
    assert task_runs == []
    assert db_session.scalar(select(TaskRun).where(TaskRun.resource_key == "stk_mins")) is None
