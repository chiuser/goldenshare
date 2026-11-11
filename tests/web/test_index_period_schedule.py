from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.foundation.ingestion import DatasetActionResolver
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.task_run import TaskRun
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher
from src.ops.services.operations_schedule_service import OperationsScheduleService
from src.ops.services.task_run_service import TaskRunCommandService


NOW = datetime(2026, 4, 29, 13, tzinfo=timezone.utc)
URL = "/api/v1/ops/schedules"
WEEKLY_RAW = ("dataset_action", "index_weekly.maintain", "weekly_last_trading_day")
MONTHLY_RAW = ("dataset_action", "index_monthly.maintain", "monthly_first_trading_day")
WEEKLY_SERVING = ("maintenance_action", "maintenance.update_index_weekly_serving", "trading_day_point")
MONTHLY_SERVING = ("maintenance_action", "maintenance.update_index_monthly_serving", "trading_day_point")


@pytest.fixture
def schedule_context(app_client, user_factory, db_session, monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr("src.ops.services.operations_schedule_service.datetime", FixedDatetime)
    start = date(2026, 4, 1)
    end = date(2026, 6, 30)
    # The SSE calendar returned 2026-04-30 open and 2026-05-01 to 05-05 closed.
    holidays = {date(2026, 5, day) for day in range(1, 6)}
    days = (start + timedelta(days=i) for i in range((end - start).days + 1))
    db_session.add_all([
        TradeCalendar(exchange="SSE", trade_date=day, is_open=day.weekday() < 5 and day not in holidays)
        for day in days
    ])
    db_session.commit()
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    return app_client, {"Authorization": f"Bearer {login.json()['token']}"}


def config(action, **changes):
    target_type, target_key, policy = action
    return {
        "target_type": target_type, "target_key": target_key, "calendar_policy": policy,
        "display_name": target_key, "schedule_type": "cron", "trigger_mode": "schedule",
        "cron_expr": "10 19 * * *", "timezone": "Asia/Shanghai", **changes,
    }


def serving_probe_config(action, **changes):
    return config(action, trigger_mode="probe", cron_expr=None, probe_config={
        "condition_kind": "index_period_serving_ready", "window_start": "19:00", "window_end": "00:00",
        "probe_interval_seconds": 300, "max_triggers_per_day": 1, **changes,
    })


@pytest.mark.parametrize("action", [WEEKLY_SERVING, MONTHLY_SERVING])
def test_serving_probe_api_save_read_pause_and_resume(schedule_context, db_session, action):
    client, headers = schedule_context
    created = client.post(URL, headers=headers, json=serving_probe_config(action))
    assert created.status_code == 200, created.json()
    body = created.json()
    assert body["next_run_at"] is None and body["cron_expr"] is None
    assert body["probe_config"]["source_label"] == "Prod Raw"
    assert body["probe_config"]["probe_interval_seconds"] == 300
    sid = body["id"]
    response = client.get(f"/api/v1/ops/probes?schedule_id={sid}", headers=headers)
    assert response.status_code == 200, response.json()
    rule, = response.json()["items"]
    assert rule["dataset_key"] == ("index_weekly_serving" if action == WEEKLY_SERVING else "index_monthly_serving")
    assert rule["source_key"] is None and rule["source_display_name"] == "Prod Raw"
    assert client.get(f"/api/v1/ops/probes/{rule['id']}", headers=headers).status_code == 200
    assert client.post(f"{URL}/{sid}/pause", headers=headers).status_code == 200
    assert client.get(f"/api/v1/ops/probes?schedule_id={sid}", headers=headers).json()["total"] == 0
    resumed = client.post(f"{URL}/{sid}/resume", headers=headers)
    assert resumed.status_code == 200, resumed.json()
    assert resumed.json()["next_run_at"] is None
    assert client.get(f"/api/v1/ops/probes?schedule_id={sid}", headers=headers).json()["total"] == 1


@pytest.mark.parametrize("probe_changes", [
    {"condition_kind": "freshness_latest_open"}, {"window_start": "18:00"},
    {"window_end": "01:00"}, {"probe_interval_seconds": 29}, {"source_key": "tushare"},
])
def test_serving_probe_rejects_conflicting_probe_input(schedule_context, probe_changes):
    client, headers = schedule_context
    response = client.post(URL, headers=headers, json=serving_probe_config(WEEKLY_SERVING, **probe_changes))
    assert response.status_code == 422, response.json()


@pytest.mark.parametrize("changes", [
    {"params_json": {"ts_code": "000001.SH"}},
    {"params_json": {"time_input": {"mode": "point", "trade_date": "2026-04-29"}}},
    {"timezone": "UTC"}, {"trigger_mode": "schedule_probe_fallback"},
    {"target_type": "dataset_action", "target_key": "index_weekly.maintain", "calendar_policy": "weekly_last_trading_day"},
    {"target_key": "maintenance.rebuild_dm", "calendar_policy": None},
])
def test_serving_probe_does_not_expand_to_other_targets_or_scopes(schedule_context, changes):
    client, headers = schedule_context
    response = client.post(URL, headers=headers, json={**serving_probe_config(WEEKLY_SERVING), **changes})
    assert response.status_code == 422, response.json()


@pytest.mark.parametrize(("action", "first", "second", "target"), [
    (WEEKLY_RAW, "2026-04-30", "2026-05-08", "2026-04-30"),
    (MONTHLY_RAW, "2026-05-06", "2026-06-01", "2026-04-30"),
    (WEEKLY_SERVING, "2026-04-30", "2026-05-06", "2026-04-30"),
    (MONTHLY_SERVING, "2026-04-30", "2026-05-06", "2026-04-30"),
])
def test_preview_enqueue_plan_and_retry_share_the_same_target(schedule_context, db_session, action, first, second, target):
    client, headers = schedule_context
    body = config(action)
    preview = client.post(URL + "/preview", headers=headers, json={
        key: body[key] for key in ("schedule_type", "calendar_policy", "cron_expr", "timezone")
    } | {"count": 2})
    assert preview.status_code == 200, preview.json()
    first_time = datetime.fromisoformat(f"{first}T11:10:00+00:00")
    second_time = datetime.fromisoformat(f"{second}T11:10:00+00:00")
    assert [datetime.fromisoformat(item) for item in preview.json()["preview_times"]] == [first_time, second_time]

    created = client.post(URL, headers=headers, json=body)
    assert created.status_code == 200, created.json()
    catalog = client.get("/api/v1/ops/catalog", headers=headers).json()
    catalog_action = next(item for item in catalog["actions"] if item["key"] == action[1])
    capability = catalog_action["automation_capability"]
    expected_options = [{"mode": "schedule", "allowed_schedule_types": ["cron"]}]
    if action[0] == "maintenance_action":
        expected_options.append({"mode": "probe", "allowed_schedule_types": ["cron"]})
    assert capability["trigger_options"] == expected_options
    rule, = capability["calendar_policy_rules"]
    assert (rule["policy"], rule["generated_time_field"], rule["explicit_time_input"]) == (action[2], "trade_date", "forbidden")
    assert datetime.fromisoformat(created.json()["next_run_at"]).replace(tzinfo=timezone.utc) == first_time
    service = OperationsScheduleService()
    assert service.enqueue_due_schedules(db_session, now=first_time - timedelta(minutes=1)) == []
    task, = service.enqueue_due_schedules(db_session, now=first_time + timedelta(hours=5))
    assert task.time_input_json == {"mode": "point", "trade_date": target}
    assert task.filters_json == {}
    assert task.schedule_id == created.json()["id"]
    if action[0] == "dataset_action":
        request = TaskRunDispatcher()._build_dataset_action_request(task)
        unit, = DatasetActionResolver(db_session).build_plan(request).units
        assert unit.request_params["trade_date"] == target.replace("-", "")
    retried = TaskRunCommandService().retry_task_run(db_session, task_run_id=task.id, requested_by_user_id=1)
    assert retried.schedule_id == task.schedule_id
    assert retried.time_input_json == task.time_input_json
    detail = client.get(f"{URL}/{task.schedule_id}", headers=headers).json()
    assert datetime.fromisoformat(detail["next_run_at"]).replace(tzinfo=timezone.utc) == second_time


@pytest.mark.parametrize(("action", "changes"), [
    (MONTHLY_RAW, {"cron_expr": "59 18 * * *"}),
    (WEEKLY_RAW, {"cron_expr": "59 14 * * *"}),
    (WEEKLY_SERVING, {"cron_expr": "0 15 * * 5"}),
    (MONTHLY_SERVING, {"timezone": "UTC"}),
    (WEEKLY_SERVING, {"schedule_type": "once"}),
    (MONTHLY_RAW, {"calendar_policy": "monthly_last_trading_day"}),
    (WEEKLY_RAW, {"params_json": {"time_input": {"mode": "point", "trade_date": "2026-04-30"}}}),
    (MONTHLY_SERVING, {"params_json": {"ts_code": "000001.SH"}}),
    (WEEKLY_RAW, {"params_json": {"filters": {"ts_code": "000001.SH"}}}),
    (MONTHLY_RAW, {"next_run_at": "2026-05-06T19:10:00+08:00"}),
])
def test_rejects_conflicting_schedule_input(schedule_context, db_session, action, changes):
    client, headers = schedule_context
    result = client.post(URL, headers=headers, json=config(action, **changes))
    assert result.status_code == 422, result.json()
    assert db_session.scalar(select(TaskRun)) is None


def test_paused_legacy_monthly_schedule_recalculates_when_resumed(schedule_context, db_session, ops_schedule_factory):
    client, headers = schedule_context
    legacy = ops_schedule_factory(
        target_key=MONTHLY_RAW[1], calendar_policy="monthly_last_trading_day",
        schedule_type="cron", cron_expr="0 19 * * *",
        next_run_at=datetime(2026, 4, 29, 11, tzinfo=timezone.utc),
    )
    url = f"{URL}/{legacy.id}"
    assert client.post(url + "/pause", headers=headers).status_code == 200
    updated = client.patch(url, headers=headers, json={
        "calendar_policy": MONTHLY_RAW[2], "cron_expr": "10 19 * * *", "next_run_at": None,
    })
    assert updated.status_code == 200, updated.json()
    assert updated.json()["status"] == "paused"
    assert updated.json()["next_run_at"] is None
    assert OperationsScheduleService().enqueue_due_schedules(db_session, now=NOW) == []
    resumed = client.post(url + "/resume", headers=headers)
    assert resumed.status_code == 200, resumed.json()
    assert datetime.fromisoformat(resumed.json()["next_run_at"]).replace(tzinfo=timezone.utc) == datetime(
        2026, 5, 6, 11, 10, tzinfo=timezone.utc,
    )


def test_retired_action_history_is_readable_but_cannot_be_retried(schedule_context, db_session, task_run_factory):
    client, headers = schedule_context
    legacy = task_run_factory(
        task_type="maintenance_action", resource_key=None, status="failed", title="旧指数周期服务表补齐",
        request_payload_json={"target_type": "maintenance_action", "target_key": "maintenance.rebuild_index_kline_serving"},
    )
    url = f"/api/v1/ops/task-runs/{legacy.id}"
    assert client.get(url + "/view", headers=headers).status_code == 200
    assert client.post(url + "/retry", headers=headers).status_code == 422
    assert db_session.scalars(select(TaskRun.id)).all() == [legacy.id]
