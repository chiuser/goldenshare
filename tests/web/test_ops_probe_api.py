from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.ops.models.ops.probe_run_log import ProbeRunLog
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.operations_probe_runtime_service import ProbeRuntimeService
from src.ops.services.index_daily_remote_probe_service import (
    INDEX_DAILY_REMOTE_READY_CONDITION,
    IndexDailyRemoteReadinessProbeResult,
    IndexDailyRemoteReadinessProbeService,
)
from src.ops.services.idx_factor_pro_remote_probe_service import (
    IDX_FACTOR_PRO_REMOTE_READY_CONDITION,
    IdxFactorProRemoteReadinessProbeResult,
    IdxFactorProRemoteReadinessProbeService,
)
from src.ops.services.index_mins_remote_probe_service import (
    DEFAULT_INDEX_MINS_SAMPLE_CODES,
    INDEX_MINS_REMOTE_READY_CONDITION,
    IndexMinsRemoteReadinessProbeResult,
    IndexMinsRemoteReadinessProbeService,
)
from src.ops.services.kpl_list_remote_probe_service import (
    KPL_LIST_REMOTE_READY_CONDITION,
    KplListRemoteReadinessProbeResult,
    KplListRemoteReadinessProbeService,
)
from src.ops.services.margin_remote_probe_service import (
    MARGIN_REMOTE_READY_CONDITION,
    MarginRemoteReadinessProbeResult,
    MarginRemoteReadinessProbeService,
)
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


def test_ops_probe_rule_write_endpoints_are_not_available(app_client, user_factory, probe_rule_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]
    rule = probe_rule_factory(dataset_key="daily", source_key="tushare")

    create = app_client.post(
        "/api/v1/ops/probes",
        headers={"Authorization": f"Bearer {token}"},
        json={"source_key": "tushare"},
    )
    assert create.status_code == 405

    listed = app_client.get("/api/v1/ops/probes?dataset_key=daily", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == rule.id

    for method, path in (
        ("patch", f"/api/v1/ops/probes/{rule.id}"),
        ("post", f"/api/v1/ops/probes/{rule.id}/pause"),
        ("post", f"/api/v1/ops/probes/{rule.id}/resume"),
        ("delete", f"/api/v1/ops/probes/{rule.id}"),
    ):
        request = getattr(app_client, method)
        response = (
            request(path, headers={"Authorization": f"Bearer {token}"})
            if method == "delete"
            else request(path, headers={"Authorization": f"Bearer {token}"}, json={})
        )
        assert response.status_code in {404, 405}


def test_ops_probe_write_endpoint_is_not_available_for_invalid_payload(app_client, user_factory) -> None:
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

    assert response.status_code == 405


def test_ops_probe_write_endpoint_cannot_bypass_stk_mins_binding(app_client, user_factory) -> None:
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

    assert response.status_code == 405


def test_ops_probe_write_endpoint_cannot_bypass_index_daily_binding(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/probes",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "错误指数日线源站探测",
            "dataset_key": "daily",
            "source_key": "tushare",
            "window_start": "15:30",
            "window_end": "17:30",
            "probe_interval_seconds": 180,
            "probe_condition_json": {"type": INDEX_DAILY_REMOTE_READY_CONDITION},
            "on_success_action_json": {
                "action_type": "dataset_action",
                "action_key": "daily.maintain",
                "request": {"time_input": {"mode": "point"}, "filters": {}},
            },
            "max_triggers_per_day": 2,
            "timezone_name": "Asia/Shanghai",
        },
    )

    assert response.status_code == 405


def test_ops_probe_write_endpoint_cannot_bypass_kpl_list_binding(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/probes",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "错误开盘啦源站探测",
            "dataset_key": "daily",
            "source_key": "tushare",
            "window_start": "08:35",
            "window_end": "23:30",
            "probe_interval_seconds": 1800,
            "probe_condition_json": {"type": KPL_LIST_REMOTE_READY_CONDITION},
            "on_success_action_json": {
                "action_type": "dataset_action",
                "action_key": "daily.maintain",
                "request": {"time_input": {"mode": "point"}, "filters": {}},
            },
            "max_triggers_per_day": 1,
            "timezone_name": "Asia/Shanghai",
        },
    )

    assert response.status_code == 405


def test_ops_probe_run_log_list_supports_rule_and_dataset_filters(
    app_client,
    db_session,
    user_factory,
    ops_schedule_factory,
    probe_rule_factory,
    probe_run_log_factory,
    task_run_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    schedule = ops_schedule_factory(target_key="daily.maintain", trigger_mode="schedule_probe_fallback")
    equity_rule = probe_rule_factory(schedule_id=schedule.id, name="股票日线探测", dataset_key="daily", source_key="tushare")
    biying_rule = probe_rule_factory(name="Biying 股票日线探测", dataset_key="biying_equity_daily", source_key="biying")
    deleted_rule = probe_rule_factory(schedule_id=schedule.id, name="已删除旧规则", dataset_key="daily", source_key="tushare")
    triggered_task = task_run_factory(
        resource_key="daily",
        trigger_source="probe",
        status="success",
        schedule_id=schedule.id,
    )

    probe_run_log_factory(
        probe_rule_id=equity_rule.id,
        schedule_id=schedule.id,
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
    probe_run_log_factory(
        probe_rule_id=deleted_rule.id,
        status="success",
        condition_matched=True,
        message="old hit",
        payload_json={"max_trade_date": "2026-04-14"},
        triggered_task_run_id=triggered_task.id,
    )
    db_session.delete(deleted_rule)
    db_session.commit()

    all_runs = app_client.get("/api/v1/ops/probes/runs", headers={"Authorization": f"Bearer {token}"})
    assert all_runs.status_code == 200
    all_payload = all_runs.json()
    assert all_payload["total"] == 3
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

    by_schedule_hit = app_client.get(
        f"/api/v1/ops/probes/runs?schedule_id={schedule.id}&dataset_key=daily&condition_matched=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert by_schedule_hit.status_code == 200
    by_schedule_hit_payload = by_schedule_hit.json()
    assert by_schedule_hit_payload["total"] == 2
    assert {item["schedule_id"] for item in by_schedule_hit_payload["items"]} == {schedule.id}
    assert {item["triggered_task_run_id"] for item in by_schedule_hit_payload["items"]} == {101, triggered_task.id}


def test_probe_runtime_rejects_legacy_workflow_probe_rule_without_creating_task_run(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
) -> None:
    schedule = ops_schedule_factory(
        target_type="workflow",
        target_key="daily_market_close_maintenance",
        trigger_mode="schedule",
    )
    rule = probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="daily",
        source_key="tushare",
        window_start=None,
        window_end=None,
        workflow_key="daily_market_close_maintenance",
    )

    task_runs, result = ProbeRuntimeService().run_once(
        db_session,
        now=datetime(2026, 5, 29, 1, 0, tzinfo=timezone.utc),
        limit=10,
    )

    assert result.processed_rules == 1
    assert result.triggered_rules == 0
    assert task_runs == []
    assert db_session.scalars(select(TaskRun)).all() == []
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.status == "failed"
    assert run_log.result_code == "configuration_error"
    assert run_log.result_reason == "probe_rule.target_forbidden"
    assert run_log.payload_json["reason_code"] == "probe_rule.target_forbidden"


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


def test_index_daily_remote_probe_requires_default_samples_in_raw_request_pool(db_session, monkeypatch) -> None:
    class FakeIndexSeriesActiveDAO:
        def list_active_codes(self, resource):
            assert resource == "index_daily_raw"
            return ["000001.SH", "399001.SZ", "399300.SZ", "000016.SH"]

    class FakeDAOFactory:
        def __init__(self, session):
            del session
            self.index_series_active = FakeIndexSeriesActiveDAO()

    monkeypatch.setattr("src.ops.services.index_daily_remote_probe_service.DAOFactory", FakeDAOFactory)

    with pytest.raises(ValueError, match="指数日线默认探测样本未配置完整：000905.SH"):
        IndexDailyRemoteReadinessProbeService._resolve_sample_codes(db_session, {})


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


def test_index_daily_remote_probe_rejects_direct_non_index_rule(db_session, probe_rule_factory) -> None:
    rule = probe_rule_factory(
        dataset_key="daily",
        source_key=None,
        probe_condition_json={"type": INDEX_DAILY_REMOTE_READY_CONDITION},
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

    with pytest.raises(ValueError, match="源站指数日线探测只支持指数日线行情维护"):
        IndexDailyRemoteReadinessProbeService().evaluate(
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


def test_index_daily_remote_probe_builds_sample_request_from_resolver(db_session, probe_rule_factory, monkeypatch) -> None:
    class FakeTradeCalendarDAO:
        def __init__(self, session):
            del session

        def fetch_by_pk(self, exchange, business_date):
            del exchange
            del business_date
            return SimpleNamespace(is_open=True, pretrade_date=date(2026, 5, 28))

    calls: list[dict] = []

    class FakeConnector:
        def call(self, api_name, params=None, fields=None):
            calls.append({"api_name": api_name, "params": dict(params or {}), "fields": tuple(fields or ())})
            return [{"ts_code": "000001.SH", "trade_date": "20260529"}]

    monkeypatch.setattr("src.ops.services.index_daily_remote_probe_service.TradeCalendarDAO", FakeTradeCalendarDAO)
    monkeypatch.setattr(
        "src.ops.services.index_daily_remote_probe_service.create_source_connector",
        lambda _source_key: FakeConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="index_daily",
        source_key=None,
        probe_condition_json={"type": INDEX_DAILY_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "index_daily.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"ts_code": "000001.SH", "source_key": "tushare"},
                "run_scope": "probe_triggered",
            },
        },
    )

    result = IndexDailyRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
    )

    assert result.matched is True
    assert result.payload["business_date"] == "2026-05-29"
    assert result.payload["latest_open_date"] == "2026-05-29"
    assert result.payload["sample_codes"] == ["000001.SH"]
    assert result.payload["matched_codes"] == ["000001.SH"]
    assert result.payload["missing_codes"] == []
    assert calls == [
        {
            "api_name": "index_daily",
            "params": {
                "ts_code": "000001.SH",
                "trade_date": "20260529",
                "limit": 1,
                "offset": 0,
            },
            "fields": ("ts_code", "trade_date"),
        }
    ]


def test_idx_factor_pro_remote_probe_builds_empty_filter_request_from_resolver(
    db_session,
    probe_rule_factory,
    monkeypatch,
) -> None:
    class FakeTradeCalendarDAO:
        def __init__(self, session):
            del session

        def fetch_by_pk(self, exchange, business_date):
            del exchange
            del business_date
            return SimpleNamespace(is_open=True)

    calls: list[dict] = []

    class FakeConnector:
        def call(self, api_name, params=None, fields=None):
            calls.append({"api_name": api_name, "params": dict(params or {}), "fields": tuple(fields or ())})
            return [{"ts_code": "000001.SH", "trade_date": "20260529"}]

    monkeypatch.setattr("src.ops.services.idx_factor_pro_remote_probe_service.TradeCalendarDAO", FakeTradeCalendarDAO)
    monkeypatch.setattr(
        "src.ops.services.idx_factor_pro_remote_probe_service.create_source_connector",
        lambda _source_key: FakeConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="idx_factor_pro",
        source_key=None,
        probe_condition_json={"type": IDX_FACTOR_PRO_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "idx_factor_pro.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {},
                "run_scope": "probe_triggered",
            },
        },
    )

    result = IdxFactorProRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
    )

    assert result.matched is True
    assert result.payload["business_date"] == "2026-05-29"
    assert result.payload["latest_open_date"] == "2026-05-29"
    assert result.payload["sample_request_count"] == 1
    assert result.payload["matched_ts_code"] == "000001.SH"
    assert result.payload["matched_trade_date"] == "20260529"
    assert calls == [
        {
            "api_name": "idx_factor_pro",
            "params": {"trade_date": "20260529", "limit": 1, "offset": 0},
            "fields": ("ts_code", "trade_date"),
        }
    ]


@pytest.mark.parametrize("is_open", [None, False])
def test_idx_factor_pro_remote_probe_skips_missing_or_closed_business_date(
    db_session,
    probe_rule_factory,
    trade_calendar_factory,
    monkeypatch,
    is_open,
) -> None:
    if is_open is False:
        trade_calendar_factory(exchange="SSE", trade_date=date(2026, 5, 29), is_open=False)
    connector_calls: list[dict] = []

    def create_connector(_source_key):
        connector_calls.append({"source_key": _source_key})
        raise AssertionError("non-trading probe result must not call Tushare")

    monkeypatch.setattr("src.ops.services.idx_factor_pro_remote_probe_service.create_source_connector", create_connector)
    rule = probe_rule_factory(
        dataset_key="idx_factor_pro",
        source_key=None,
        probe_condition_json={"type": IDX_FACTOR_PRO_REMOTE_READY_CONDITION, "exchange": "SSE"},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "idx_factor_pro.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}},
        },
    )

    result = IdxFactorProRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
    )

    assert result.matched is False
    assert result.payload["sample_request_count"] == 0
    assert result.payload["latest_open_date"] is None
    assert result.payload["is_open"] is is_open
    assert connector_calls == []


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"ts_code": "000001.SH", "trade_date": "20260528"}],
        [{"ts_code": "", "trade_date": "20260529"}],
    ],
)
def test_idx_factor_pro_remote_probe_miss_does_not_accept_incomplete_source_row(
    db_session,
    probe_rule_factory,
    monkeypatch,
    rows,
) -> None:
    class FakeTradeCalendarDAO:
        def __init__(self, session):
            del session

        def fetch_by_pk(self, exchange, business_date):
            del exchange
            del business_date
            return SimpleNamespace(is_open=True)

    class FakeConnector:
        def call(self, api_name, params=None, fields=None):
            del api_name
            del params
            del fields
            return rows

    monkeypatch.setattr("src.ops.services.idx_factor_pro_remote_probe_service.TradeCalendarDAO", FakeTradeCalendarDAO)
    monkeypatch.setattr(
        "src.ops.services.idx_factor_pro_remote_probe_service.create_source_connector",
        lambda _source_key: FakeConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="idx_factor_pro",
        source_key=None,
        probe_condition_json={"type": IDX_FACTOR_PRO_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "idx_factor_pro.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}},
        },
    )

    result = IdxFactorProRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
    )

    assert result.matched is False
    assert result.message == "源站尚未返回目标交易日指数技术因子"
    assert result.payload["sample_request_count"] == 1


@pytest.mark.parametrize(
    ("request_payload", "expected_message"),
    [
        ({"time_input": {"mode": "point"}, "filters": {"ts_code": "000001.SH"}}, "源站指数技术因子探测不支持维护参数"),
        ({"time_input": {"mode": "point", "trade_date": "2026-05-29"}, "filters": {}}, "源站指数技术因子探测不能与固定维护日期混用"),
    ],
)
def test_idx_factor_pro_remote_probe_rejects_invalid_direct_rule(
    db_session,
    probe_rule_factory,
    request_payload,
    expected_message,
) -> None:
    rule = probe_rule_factory(
        dataset_key="idx_factor_pro",
        source_key=None,
        probe_condition_json={"type": IDX_FACTOR_PRO_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "idx_factor_pro.maintain",
            "request": request_payload,
        },
    )

    with pytest.raises(ValueError, match=expected_message):
        IdxFactorProRemoteReadinessProbeService().evaluate(
            db_session,
            rule,
            current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
        )


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


def test_index_daily_remote_probe_requires_all_selected_codes(db_session, probe_rule_factory, monkeypatch) -> None:
    class FakeTradeCalendarDAO:
        def __init__(self, session):
            del session

        def fetch_by_pk(self, exchange, business_date):
            del exchange
            del business_date
            return SimpleNamespace(is_open=True, pretrade_date=date(2026, 5, 28))

    class FakeConnector:
        def call(self, api_name, params=None, fields=None):
            del api_name
            del fields
            if (params or {}).get("ts_code") == "000001.SH":
                return [{"ts_code": "000001.SH", "trade_date": "20260529"}]
            return []

    monkeypatch.setattr("src.ops.services.index_daily_remote_probe_service.TradeCalendarDAO", FakeTradeCalendarDAO)
    monkeypatch.setattr(
        "src.ops.services.index_daily_remote_probe_service.create_source_connector",
        lambda _source_key: FakeConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="index_daily",
        source_key=None,
        probe_condition_json={"type": INDEX_DAILY_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "index_daily.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"ts_code": ["000001.SH", "399001.SZ"]},
                "run_scope": "probe_triggered",
            },
        },
    )

    result = IndexDailyRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
    )

    assert result.matched is False
    assert result.message == "源站尚未返回全部指数日线：缺少 399001.SZ"
    assert result.payload["sample_codes"] == ["000001.SH", "399001.SZ"]
    assert result.payload["matched_codes"] == ["000001.SH"]
    assert result.payload["missing_codes"] == ["399001.SZ"]
    assert result.payload["sample_request_count"] == 2


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


def test_probe_runtime_remote_index_daily_hit_creates_task_run_with_latest_open_date(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    monkeypatch,
) -> None:
    schedule = ops_schedule_factory(target_key="index_daily.maintain", trigger_mode="schedule_probe_fallback")
    rule = probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="index_daily",
        source_key="tushare",
        probe_condition_json={"type": INDEX_DAILY_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "index_daily.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"source_key": "tushare"},
                "run_scope": "probe_triggered",
            },
        },
    )

    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.index_daily_remote_probe,
        "evaluate",
        lambda session, rule, current: IndexDailyRemoteReadinessProbeResult(
            matched=True,
            message="源站已返回目标交易日指数日线",
            payload={"latest_open_date": "2026-05-29"},
        ),
    )

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 1
    assert len(task_runs) == 1
    task_run = task_runs[0]
    assert task_run.resource_key == "index_daily"
    assert task_run.schedule_id == schedule.id
    assert task_run.time_input_json == {"mode": "point", "trade_date": "2026-05-29"}
    assert task_run.filters_json == {}
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.schedule_id == schedule.id
    assert run_log.condition_matched is True
    assert db_session.scalar(select(TaskRun).where(TaskRun.id == task_run.id)) is not None


def test_probe_runtime_remote_index_daily_miss_does_not_create_task_run(db_session, probe_rule_factory, monkeypatch) -> None:
    probe_rule_factory(
        dataset_key="index_daily",
        source_key=None,
        probe_condition_json={"type": INDEX_DAILY_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "index_daily.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {},
                "run_scope": "probe_triggered",
            },
        },
    )

    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.index_daily_remote_probe,
        "evaluate",
        lambda session, rule, current: IndexDailyRemoteReadinessProbeResult(
            matched=False,
            message="源站尚未返回全部指数日线：缺少 000001.SH",
            payload={"latest_open_date": "2026-05-29"},
        ),
    )

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 0
    assert task_runs == []
    assert db_session.scalar(select(TaskRun).where(TaskRun.resource_key == "index_daily")) is None


def test_probe_runtime_remote_idx_factor_pro_hit_creates_one_empty_filter_task_run(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    monkeypatch,
) -> None:
    schedule = ops_schedule_factory(target_key="idx_factor_pro.maintain", trigger_mode="schedule_probe_fallback")
    common = {
        "dataset_key": "idx_factor_pro",
        "source_key": "tushare",
        "probe_condition_json": {"type": IDX_FACTOR_PRO_REMOTE_READY_CONDITION},
        "on_success_action_json": {
            "action_type": "dataset_action",
            "action_key": "idx_factor_pro.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {},
                "run_scope": "probe_triggered",
            },
        },
    }
    first_rule = probe_rule_factory(schedule_id=schedule.id, **common)
    second_rule = probe_rule_factory(schedule_id=schedule.id, **common)

    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.idx_factor_pro_remote_probe,
        "evaluate",
        lambda session, rule, current: IdxFactorProRemoteReadinessProbeResult(
            matched=True,
            message="源站已返回目标交易日指数技术因子",
            payload={"latest_open_date": "2026-05-29"},
        ),
    )

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 1
    assert len(task_runs) == 1
    task_run = task_runs[0]
    assert task_run.resource_key == "idx_factor_pro"
    assert task_run.schedule_id == schedule.id
    assert task_run.time_input_json == {"mode": "point", "trade_date": "2026-05-29"}
    assert task_run.filters_json == {}
    logs = list(
        db_session.scalars(
            select(ProbeRunLog)
            .where(ProbeRunLog.probe_rule_id.in_((first_rule.id, second_rule.id)))
            .order_by(ProbeRunLog.probe_rule_id.asc())
        )
    )
    assert [item.result_code for item in logs] == ["hit", "deduplicated"]
    assert logs[0].triggered_task_run_id == task_run.id
    assert logs[1].triggered_task_run_id is None


def test_probe_runtime_remote_idx_factor_pro_source_error_only_writes_probe_log(
    db_session,
    probe_rule_factory,
    trade_calendar_factory,
    monkeypatch,
) -> None:
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 5, 29), is_open=True)

    class FailingConnector:
        def call(self, api_name, params=None, fields=None):
            del api_name
            del params
            del fields
            raise RuntimeError("Tushare unavailable")

    monkeypatch.setattr(
        "src.ops.services.idx_factor_pro_remote_probe_service.create_source_connector",
        lambda _source_key: FailingConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="idx_factor_pro",
        source_key="tushare",
        probe_condition_json={"type": IDX_FACTOR_PRO_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "idx_factor_pro.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}},
        },
    )

    task_runs, result = ProbeRuntimeService().run_once(
        db_session,
        now=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
        limit=10,
    )

    assert result.triggered_rules == 0
    assert task_runs == []
    assert db_session.scalar(select(TaskRun).where(TaskRun.resource_key == "idx_factor_pro")) is None
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.status == "failed"
    assert run_log.result_code == "error"


def test_kpl_list_remote_probe_uses_release_target_and_resolver_request_params(
    db_session,
    probe_rule_factory,
    trade_calendar_factory,
    monkeypatch,
) -> None:
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 5, 29), is_open=True)
    rule = probe_rule_factory(
        dataset_key="kpl_list",
        source_key="tushare",
        probe_condition_json={"type": KPL_LIST_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "kpl_list.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}, "run_scope": "probe_triggered"},
        },
    )
    connector_calls: list[dict] = []

    class StubConnector:
        def call(self, api_name, *, params, fields):
            connector_calls.append({"api_name": api_name, "params": params, "fields": fields})
            return [{"ts_code": "600000.SH", "trade_date": "20260529", "tag": "竞价"}]

    monkeypatch.setattr("src.ops.services.kpl_list_remote_probe_service.create_source_connector", lambda source_key: StubConnector())

    result = KplListRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 30, 0, 35, tzinfo=timezone.utc),
    )

    assert result.matched is True
    assert result.payload["target_trade_date"] == "2026-05-29"
    assert connector_calls == [
        {
            "api_name": "kpl_list",
            "params": {"trade_date": "20260529", "tag": "竞价", "limit": 1, "offset": 0},
            "fields": ("ts_code", "trade_date", "tag"),
        }
    ]


def test_kpl_list_remote_probe_miss_does_not_claim_source_release(
    db_session,
    probe_rule_factory,
    trade_calendar_factory,
    monkeypatch,
) -> None:
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 5, 29), is_open=True)
    rule = probe_rule_factory(
        dataset_key="kpl_list",
        source_key="tushare",
        probe_condition_json={"type": KPL_LIST_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "kpl_list.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}},
        },
    )

    class EmptyConnector:
        def call(self, api_name, *, params, fields):
            return []

    monkeypatch.setattr("src.ops.services.kpl_list_remote_probe_service.create_source_connector", lambda source_key: EmptyConnector())

    result = KplListRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 30, 0, 35, tzinfo=timezone.utc),
    )

    assert result.matched is False
    assert result.payload["target_trade_date"] == "2026-05-29"
    assert result.payload["sample_request_count"] == 1


def test_probe_runtime_remote_kpl_list_hit_creates_task_run_for_release_target(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    monkeypatch,
) -> None:
    schedule = ops_schedule_factory(target_key="kpl_list.maintain", trigger_mode="probe")
    rule = probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="kpl_list",
        source_key="tushare",
        probe_condition_json={"type": KPL_LIST_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "kpl_list.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}, "run_scope": "probe_triggered"},
        },
        window_start=None,
        window_end=None,
    )
    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.kpl_list_remote_probe,
        "evaluate",
        lambda session, rule, current: KplListRemoteReadinessProbeResult(
            matched=True,
            message="源站已返回目标交易日开盘啦榜单",
            payload={"target_trade_date": "2026-05-29"},
        ),
    )

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 30, 1, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 1
    assert len(task_runs) == 1
    assert task_runs[0].resource_key == "kpl_list"
    assert task_runs[0].time_input_json == {"mode": "point", "trade_date": "2026-05-29"}
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.result_code == "hit"
    assert run_log.triggered_task_run_id == task_runs[0].id


def test_probe_runtime_remote_kpl_list_skips_existing_effective_target_task(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    task_run_factory,
    monkeypatch,
) -> None:
    schedule = ops_schedule_factory(target_key="kpl_list.maintain", trigger_mode="probe")
    rule = probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="kpl_list",
        source_key="tushare",
        probe_condition_json={"type": KPL_LIST_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "kpl_list.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}, "run_scope": "probe_triggered"},
        },
        window_start=None,
        window_end=None,
    )
    task_run_factory(
        resource_key="kpl_list",
        trigger_source="probe",
        schedule_id=schedule.id,
        status="success",
        time_input_json={"mode": "point", "trade_date": "2026-05-29"},
    )
    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.kpl_list_remote_probe,
        "evaluate",
        lambda session, rule, current: KplListRemoteReadinessProbeResult(
            matched=True,
            message="源站已返回目标交易日开盘啦榜单",
            payload={"target_trade_date": "2026-05-29"},
        ),
    )

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 30, 1, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 0
    assert task_runs == []
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.condition_matched is True
    assert run_log.result_code == "deduplicated"
    assert run_log.triggered_task_run_id is None


def test_probe_runtime_remote_kpl_list_retries_failed_target_task(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    task_run_factory,
    monkeypatch,
) -> None:
    schedule = ops_schedule_factory(target_key="kpl_list.maintain", trigger_mode="probe")
    probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="kpl_list",
        source_key="tushare",
        probe_condition_json={"type": KPL_LIST_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "kpl_list.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}, "run_scope": "probe_triggered"},
        },
        window_start=None,
        window_end=None,
    )
    task_run_factory(
        resource_key="kpl_list",
        trigger_source="probe",
        schedule_id=schedule.id,
        status="failed",
        time_input_json={"mode": "point", "trade_date": "2026-05-29"},
    )
    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.kpl_list_remote_probe,
        "evaluate",
        lambda session, rule, current: KplListRemoteReadinessProbeResult(
            matched=True,
            message="源站已返回目标交易日开盘啦榜单",
            payload={"target_trade_date": "2026-05-29"},
        ),
    )

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 30, 1, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 1
    assert len(task_runs) == 1
    assert task_runs[0].time_input_json["trade_date"] == "2026-05-29"


def test_margin_remote_probe_requires_all_exchange_rows_from_resolver(db_session, probe_rule_factory, monkeypatch) -> None:
    calls: list[dict] = []

    class FakeTradeCalendarDAO:
        def __init__(self, session):
            del session

        def get_open_dates(self, exchange, start_date, end_date):
            del exchange
            del start_date
            del end_date
            return [date(2026, 5, 28), date(2026, 5, 29)]

    class FakeConnector:
        def call(self, api_name, *, params, fields):
            calls.append({"api_name": api_name, "params": dict(params), "fields": tuple(fields)})
            return [{"trade_date": "20260528", "exchange_id": params["exchange_id"]}]

    monkeypatch.setattr("src.ops.services.margin_remote_probe_service.TradeCalendarDAO", FakeTradeCalendarDAO)
    monkeypatch.setattr(
        "src.ops.services.margin_remote_probe_service.create_source_connector",
        lambda source_key: FakeConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="margin",
        source_key="tushare",
        probe_condition_json={"type": MARGIN_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "margin.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}, "run_scope": "probe_triggered"},
        },
    )

    result = MarginRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 1, 0, tzinfo=timezone.utc),
    )

    assert result.matched is True
    assert result.payload["target_trade_date"] == "2026-05-28"
    assert result.payload["matched_exchanges"] == ["SSE", "SZSE", "BSE"]
    assert result.payload["sample_request_count"] == 3
    assert calls == [
        {
            "api_name": "margin",
            "params": {"trade_date": "20260528", "exchange_id": "SSE", "limit": 1, "offset": 0},
            "fields": ("trade_date", "exchange_id"),
        },
        {
            "api_name": "margin",
            "params": {"trade_date": "20260528", "exchange_id": "SZSE", "limit": 1, "offset": 0},
            "fields": ("trade_date", "exchange_id"),
        },
        {
            "api_name": "margin",
            "params": {"trade_date": "20260528", "exchange_id": "BSE", "limit": 1, "offset": 0},
            "fields": ("trade_date", "exchange_id"),
        },
    ]


def test_margin_remote_probe_miss_does_not_create_task_run(db_session, probe_rule_factory, monkeypatch) -> None:
    class FakeTradeCalendarDAO:
        def __init__(self, session):
            del session

        def get_open_dates(self, exchange, start_date, end_date):
            del exchange
            del start_date
            del end_date
            return [date(2026, 5, 28), date(2026, 5, 29)]

    class FakeConnector:
        def call(self, api_name, *, params, fields):
            del api_name
            del fields
            return [] if params["exchange_id"] == "BSE" else [{"trade_date": "20260528", "exchange_id": params["exchange_id"]}]

    monkeypatch.setattr("src.ops.services.margin_remote_probe_service.TradeCalendarDAO", FakeTradeCalendarDAO)
    monkeypatch.setattr(
        "src.ops.services.margin_remote_probe_service.create_source_connector",
        lambda source_key: FakeConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="margin",
        probe_condition_json={"type": MARGIN_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "margin.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}},
        },
    )

    result = MarginRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 1, 0, tzinfo=timezone.utc),
    )

    assert result.matched is False
    assert result.payload["missing_exchanges"] == ["BSE"]


def test_probe_runtime_remote_margin_hit_creates_task_run_for_release_target(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    monkeypatch,
) -> None:
    schedule = ops_schedule_factory(target_key="margin.maintain", trigger_mode="probe")
    rule = probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="margin",
        source_key="tushare",
        probe_condition_json={"type": MARGIN_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "margin.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}, "run_scope": "probe_triggered"},
        },
        window_start=None,
        window_end=None,
    )
    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.margin_remote_probe,
        "evaluate",
        lambda session, rule, current: MarginRemoteReadinessProbeResult(
            matched=True,
            message="源站已完整发布融资融券汇总",
            payload={"target_trade_date": "2026-05-28"},
        ),
    )

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 29, 1, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 1
    assert len(task_runs) == 1
    assert task_runs[0].resource_key == "margin"
    assert task_runs[0].time_input_json == {"mode": "point", "trade_date": "2026-05-28"}
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.result_code == "hit"


def test_probe_runtime_remote_margin_skips_existing_effective_target_task(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    task_run_factory,
    monkeypatch,
) -> None:
    schedule = ops_schedule_factory(target_key="margin.maintain", trigger_mode="probe")
    rule = probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="margin",
        source_key="tushare",
        probe_condition_json={"type": MARGIN_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "margin.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}, "run_scope": "probe_triggered"},
        },
        window_start=None,
        window_end=None,
    )
    task_run_factory(
        resource_key="margin",
        trigger_source="probe",
        schedule_id=schedule.id,
        status="success",
        time_input_json={"mode": "point", "trade_date": "2026-05-28"},
    )
    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.margin_remote_probe,
        "evaluate",
        lambda session, rule, current: MarginRemoteReadinessProbeResult(
            matched=True,
            message="源站已完整发布融资融券汇总",
            payload={"target_trade_date": "2026-05-28"},
        ),
    )

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 29, 1, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 0
    assert task_runs == []
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.result_code == "deduplicated"


def test_probe_runtime_remote_margin_retries_failed_target_task(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    task_run_factory,
    monkeypatch,
) -> None:
    schedule = ops_schedule_factory(target_key="margin.maintain", trigger_mode="probe")
    probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="margin",
        source_key="tushare",
        probe_condition_json={"type": MARGIN_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "margin.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}, "run_scope": "probe_triggered"},
        },
        window_start=None,
        window_end=None,
    )
    task_run_factory(
        resource_key="margin",
        trigger_source="probe",
        schedule_id=schedule.id,
        status="failed",
        time_input_json={"mode": "point", "trade_date": "2026-05-28"},
    )
    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.margin_remote_probe,
        "evaluate",
        lambda session, rule, current: MarginRemoteReadinessProbeResult(
            matched=True,
            message="源站已完整发布融资融券汇总",
            payload={"target_trade_date": "2026-05-28"},
        ),
    )

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 29, 1, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 1
    assert len(task_runs) == 1
    assert task_runs[0].time_input_json["trade_date"] == "2026-05-28"


def test_probe_runtime_remote_margin_error_only_records_probe_log(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    monkeypatch,
) -> None:
    schedule = ops_schedule_factory(target_key="margin.maintain", trigger_mode="probe")
    rule = probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="margin",
        source_key="tushare",
        probe_condition_json={"type": MARGIN_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "margin.maintain",
            "request": {"time_input": {"mode": "point"}, "filters": {}, "run_scope": "probe_triggered"},
        },
        window_start=None,
        window_end=None,
    )
    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.margin_remote_probe,
        "evaluate",
        lambda session, rule, current: (_ for _ in ()).throw(RuntimeError("source unavailable")),
    )

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 29, 1, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 0
    assert task_runs == []
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.status == "failed"
    assert run_log.result_code == "error"


def test_index_mins_remote_probe_requires_all_representative_samples_in_active_pool(db_session, monkeypatch) -> None:
    class FakeIndexSeriesActiveDAO:
        def list_active_codes(self, resource):
            assert resource == "index_mins"
            return DEFAULT_INDEX_MINS_SAMPLE_CODES[:-1]

    class FakeDAOFactory:
        def __init__(self, session):
            del session
            self.index_series_active = FakeIndexSeriesActiveDAO()

    monkeypatch.setattr("src.ops.services.index_mins_remote_probe_service.DAOFactory", FakeDAOFactory)

    with pytest.raises(ValueError, match="指数分钟线代表样本未配置完整：399699.SZ"):
        IndexMinsRemoteReadinessProbeService._resolve_sample_codes(db_session)


def test_index_mins_remote_probe_rejects_direct_partial_frequency_rule(db_session, probe_rule_factory) -> None:
    rule = probe_rule_factory(
        dataset_key="index_mins",
        source_key="tushare",
        probe_condition_json={"type": INDEX_MINS_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "index_mins.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"freq": ["1min", "5min"]},
                "run_scope": "probe_triggered",
            },
        },
    )

    with pytest.raises(ValueError, match="源站指数分钟行情探测必须完整配置 1min/5min/15min/30min/60min"):
        IndexMinsRemoteReadinessProbeService().evaluate(
            db_session,
            rule,
            current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
        )


def test_index_mins_remote_probe_builds_all_requests_from_resolver(db_session, probe_rule_factory, monkeypatch) -> None:
    class FakeTradeCalendarDAO:
        def __init__(self, session):
            del session

        def fetch_by_pk(self, exchange, business_date):
            del exchange
            del business_date
            return SimpleNamespace(is_open=True, pretrade_date=date(2026, 5, 28))

    class FakeIndexSeriesActiveDAO:
        def list_active_codes(self, resource):
            assert resource == "index_mins"
            return DEFAULT_INDEX_MINS_SAMPLE_CODES

    class FakeIndexBasicDAO:
        @staticmethod
        def get_by_ts_code(ts_code):
            return SimpleNamespace(name=ts_code)

    class FakeDAOFactory:
        def __init__(self, session):
            del session
            self.index_series_active = FakeIndexSeriesActiveDAO()
            self.index_basic = FakeIndexBasicDAO()

    calls: list[dict] = []

    class FakeConnector:
        def call(self, api_name, params=None, fields=None):
            request_params = dict(params or {})
            calls.append({"api_name": api_name, "params": request_params, "fields": tuple(fields or ())})
            return [{"ts_code": request_params["ts_code"], "trade_time": "2026-05-29 15:00:00"}]

    monkeypatch.setattr("src.ops.services.index_mins_remote_probe_service.TradeCalendarDAO", FakeTradeCalendarDAO)
    monkeypatch.setattr("src.ops.services.index_mins_remote_probe_service.DAOFactory", FakeDAOFactory)
    monkeypatch.setattr("src.foundation.ingestion.unit_planner.DAOFactory", FakeDAOFactory)
    monkeypatch.setattr(
        "src.ops.services.index_mins_remote_probe_service.create_source_connector",
        lambda _source_key: FakeConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="index_mins",
        source_key="tushare",
        probe_condition_json={"type": INDEX_MINS_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "index_mins.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"freq": ["1min", "5min", "15min", "30min", "60min"]},
                "run_scope": "probe_triggered",
            },
        },
    )

    result = IndexMinsRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
    )

    assert result.matched is True
    assert result.payload["latest_open_date"] == "2026-05-29"
    assert result.payload["sample_request_count"] == 75
    assert len(result.payload["sample_hits"]) == 75
    assert len(calls) == 75
    assert calls[0] == {
        "api_name": "idx_mins",
        "params": {
            "ts_code": "000001.SH",
            "freq": "1min",
            "start_date": "2026-05-29 09:00:00",
            "end_date": "2026-05-29 19:00:00",
            "limit": 1,
            "offset": 0,
        },
        "fields": ("ts_code", "trade_time"),
    }
    assert calls[-1]["params"]["ts_code"] == "399699.SZ"
    assert calls[-1]["params"]["freq"] == "60min"


def test_index_mins_remote_probe_stops_on_first_missing_sample(db_session, probe_rule_factory, monkeypatch) -> None:
    class FakeTradeCalendarDAO:
        def __init__(self, session):
            del session

        def fetch_by_pk(self, exchange, business_date):
            del exchange
            del business_date
            return SimpleNamespace(is_open=True, pretrade_date=date(2026, 5, 28))

    class FakeIndexSeriesActiveDAO:
        def list_active_codes(self, resource):
            assert resource == "index_mins"
            return DEFAULT_INDEX_MINS_SAMPLE_CODES

    class FakeIndexBasicDAO:
        @staticmethod
        def get_by_ts_code(ts_code):
            return SimpleNamespace(name=ts_code)

    class FakeDAOFactory:
        def __init__(self, session):
            del session
            self.index_series_active = FakeIndexSeriesActiveDAO()
            self.index_basic = FakeIndexBasicDAO()

    calls: list[dict] = []

    class FakeConnector:
        def call(self, api_name, params=None, fields=None):
            del api_name
            del fields
            request_params = dict(params or {})
            calls.append(request_params)
            if request_params["freq"] == "1min":
                return [{"ts_code": request_params["ts_code"], "trade_time": "2026-05-29 15:00:00"}]
            return []

    monkeypatch.setattr("src.ops.services.index_mins_remote_probe_service.TradeCalendarDAO", FakeTradeCalendarDAO)
    monkeypatch.setattr("src.ops.services.index_mins_remote_probe_service.DAOFactory", FakeDAOFactory)
    monkeypatch.setattr("src.foundation.ingestion.unit_planner.DAOFactory", FakeDAOFactory)
    monkeypatch.setattr(
        "src.ops.services.index_mins_remote_probe_service.create_source_connector",
        lambda _source_key: FakeConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="index_mins",
        source_key="tushare",
        probe_condition_json={"type": INDEX_MINS_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "index_mins.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"freq": ["1min", "5min", "15min", "30min", "60min"]},
                "run_scope": "probe_triggered",
            },
        },
    )

    result = IndexMinsRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
    )

    assert result.matched is False
    assert result.payload["sample_request_count"] == 2
    assert result.payload["first_missing_sample"] == {"ts_code": "000001.SH", "freq": "5min"}
    assert [item["freq"] for item in calls] == ["1min", "5min"]


def test_probe_runtime_remote_index_mins_hit_creates_task_run_with_latest_open_date(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
    monkeypatch,
) -> None:
    schedule = ops_schedule_factory(target_key="index_mins.maintain", trigger_mode="probe")
    rule = probe_rule_factory(
        schedule_id=schedule.id,
        dataset_key="index_mins",
        source_key="tushare",
        probe_condition_json={"type": INDEX_MINS_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "index_mins.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"freq": ["1min", "5min", "15min", "30min", "60min"], "source_key": "tushare"},
                "run_scope": "probe_triggered",
            },
        },
    )
    service = ProbeRuntimeService()
    monkeypatch.setattr(
        service.index_mins_remote_probe,
        "evaluate",
        lambda session, rule, current: IndexMinsRemoteReadinessProbeResult(
            matched=True,
            message="源站已返回目标交易日指数分钟行情",
            payload={"latest_open_date": "2026-05-29"},
        ),
    )

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 1
    assert len(task_runs) == 1
    assert task_runs[0].resource_key == "index_mins"
    assert task_runs[0].schedule_id == schedule.id
    assert task_runs[0].time_input_json == {"mode": "point", "trade_date": "2026-05-29"}
    assert task_runs[0].filters_json == {"freq": ["1min", "5min", "15min", "30min", "60min"]}
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.condition_matched is True


def test_index_mins_remote_probe_stops_after_first_empty_response(db_session, probe_rule_factory, monkeypatch) -> None:
    class FakeTradeCalendarDAO:
        def __init__(self, session):
            del session

        def fetch_by_pk(self, exchange, business_date):
            del exchange
            del business_date
            return SimpleNamespace(is_open=True, pretrade_date=date(2026, 5, 28))

    class FakeIndexSeriesActiveDAO:
        def list_active_codes(self, resource):
            assert resource == "index_mins"
            return DEFAULT_INDEX_MINS_SAMPLE_CODES

    class FakeIndexBasicDAO:
        @staticmethod
        def get_by_ts_code(ts_code):
            return SimpleNamespace(name=ts_code)

    class FakeDAOFactory:
        def __init__(self, session):
            del session
            self.index_series_active = FakeIndexSeriesActiveDAO()
            self.index_basic = FakeIndexBasicDAO()

    connector_calls: list[dict] = []

    class FakeConnector:
        def call(self, api_name, params=None, fields=None):
            del api_name
            del fields
            connector_calls.append(dict(params or {}))
            return []

    monkeypatch.setattr("src.ops.services.index_mins_remote_probe_service.TradeCalendarDAO", FakeTradeCalendarDAO)
    monkeypatch.setattr("src.ops.services.index_mins_remote_probe_service.DAOFactory", FakeDAOFactory)
    monkeypatch.setattr("src.foundation.ingestion.unit_planner.DAOFactory", FakeDAOFactory)
    monkeypatch.setattr(
        "src.ops.services.index_mins_remote_probe_service.create_source_connector",
        lambda _source_key: FakeConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="index_mins",
        source_key="tushare",
        probe_condition_json={"type": INDEX_MINS_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "index_mins.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"freq": ["1min", "5min", "15min", "30min", "60min"]},
                "run_scope": "probe_triggered",
            },
        },
    )

    result = IndexMinsRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
    )

    assert result.matched is False
    assert result.payload["sample_request_count"] == 1
    assert result.payload["first_missing_sample"] == {"ts_code": "000001.SH", "freq": "1min"}
    assert len(connector_calls) == 1


def test_index_mins_remote_probe_rejects_stale_source_row(db_session, probe_rule_factory, monkeypatch) -> None:
    class FakeTradeCalendarDAO:
        def __init__(self, session):
            del session

        def fetch_by_pk(self, exchange, business_date):
            del exchange
            del business_date
            return SimpleNamespace(is_open=True, pretrade_date=date(2026, 5, 28))

    class FakeIndexSeriesActiveDAO:
        def list_active_codes(self, resource):
            assert resource == "index_mins"
            return DEFAULT_INDEX_MINS_SAMPLE_CODES

    class FakeIndexBasicDAO:
        @staticmethod
        def get_by_ts_code(ts_code):
            return SimpleNamespace(name=ts_code)

    class FakeDAOFactory:
        def __init__(self, session):
            del session
            self.index_series_active = FakeIndexSeriesActiveDAO()
            self.index_basic = FakeIndexBasicDAO()

    class FakeConnector:
        def call(self, api_name, params=None, fields=None):
            del api_name
            del params
            del fields
            return [{"ts_code": "000001.SH", "trade_time": "2026-05-28 15:00:00"}]

    monkeypatch.setattr("src.ops.services.index_mins_remote_probe_service.TradeCalendarDAO", FakeTradeCalendarDAO)
    monkeypatch.setattr("src.ops.services.index_mins_remote_probe_service.DAOFactory", FakeDAOFactory)
    monkeypatch.setattr("src.foundation.ingestion.unit_planner.DAOFactory", FakeDAOFactory)
    monkeypatch.setattr(
        "src.ops.services.index_mins_remote_probe_service.create_source_connector",
        lambda _source_key: FakeConnector(),
    )
    rule = probe_rule_factory(
        dataset_key="index_mins",
        source_key="tushare",
        probe_condition_json={"type": INDEX_MINS_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "index_mins.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"freq": ["1min", "5min", "15min", "30min", "60min"]},
                "run_scope": "probe_triggered",
            },
        },
    )

    result = IndexMinsRemoteReadinessProbeService().evaluate(
        db_session,
        rule,
        current=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
    )

    assert result.matched is False
    assert result.payload["sample_request_count"] == 1


def test_probe_runtime_remote_index_mins_error_does_not_create_task_run(db_session, probe_rule_factory, monkeypatch) -> None:
    rule = probe_rule_factory(
        dataset_key="index_mins",
        source_key="tushare",
        probe_condition_json={"type": INDEX_MINS_REMOTE_READY_CONDITION},
        on_success_action_json={
            "action_type": "dataset_action",
            "action_key": "index_mins.maintain",
            "request": {
                "time_input": {"mode": "point"},
                "filters": {"freq": ["1min", "5min", "15min", "30min", "60min"]},
                "run_scope": "probe_triggered",
            },
        },
    )
    service = ProbeRuntimeService()

    def raise_source_error(session, rule, current):
        del session
        del rule
        del current
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(service.index_mins_remote_probe, "evaluate", raise_source_error)

    task_runs, result = service.run_once(db_session, now=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc), limit=10)

    assert result.triggered_rules == 0
    assert task_runs == []
    assert db_session.scalar(select(TaskRun).where(TaskRun.resource_key == "index_mins")) is None
    run_log = db_session.scalar(select(ProbeRunLog).where(ProbeRunLog.probe_rule_id == rule.id))
    assert run_log is not None
    assert run_log.status == "failed"
    assert run_log.result_code == "error"
