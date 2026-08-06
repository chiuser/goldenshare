from __future__ import annotations

from calendar import monthrange
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from src.app.exceptions import WebAppError
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.services.schedule_automation_capability_resolver import ScheduleAutomationCapabilityResolver
from src.ops.services.schedule_probe_binding_service import ScheduleProbeBindingService


def test_ops_schedule_list_rejects_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/schedules", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_schedule_create_supports_schedulable_workflow_and_records_revision(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "workflow",
            "target_key": "daily_market_close_maintenance",
            "display_name": "每日收盘维护",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * 1-5",
            "timezone": "Asia/Shanghai",
            "params_json": {"trade_date": "2026-03-30"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_type"] == "workflow"
    assert payload["target_key"] == "daily_market_close_maintenance"
    assert payload["target_display_name"] == "每日收盘后维护"
    assert payload["status"] == "active"
    assert payload["next_run_at"] is not None

    revisions = app_client.get(
        f"/api/v1/ops/schedules/{payload['id']}/revisions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revisions.status_code == 200
    revisions_payload = revisions.json()
    assert revisions_payload["total"] == 1
    assert revisions_payload["items"][0]["action"] == "created"
    assert revisions_payload["items"][0]["changed_by_username"] == "admin"


def test_ops_schedule_create_allows_daily_workflow_without_static_trade_date(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "workflow",
            "target_key": "daily_moneyflow_maintenance",
            "display_name": "每日资金流",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * 1-5",
            "timezone": "Asia/Shanghai",
            "params_json": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["target_key"] == "daily_moneyflow_maintenance"
    assert response.json()["params_json"] == {}


@pytest.mark.parametrize("target_key", ["index_mins.maintain", "idx_factor_pro.maintain", "margin.maintain", "margin_detail.maintain"])
def test_ops_schedule_rejects_schedule_mode_for_source_ready_actions(app_client, user_factory, target_key: str) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": target_key,
            "display_name": "源站就绪数据集错误定时触发",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * 1-5",
            "timezone": "Asia/Shanghai",
            "params_json": {},
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "trigger_mode.forbidden"


def test_ops_schedule_create_allows_reference_data_refresh_without_static_date(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "workflow",
            "target_key": "reference_data_refresh",
            "display_name": "基础主数据刷新",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
            "params_json": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["target_key"] == "reference_data_refresh"
    assert response.json()["params_json"] == {}


def test_ops_schedule_create_rejects_workflow_range_without_complete_dates(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "workflow",
            "target_key": "daily_moneyflow_maintenance",
            "display_name": "每日资金流",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * 1-5",
            "timezone": "Asia/Shanghai",
            "params_json": {"time_input": {"mode": "range", "start_date": "2026-04-24"}},
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "自动流程 每日资金流向维护 的自动任务必须同时填写开始日期和结束日期"


def test_ops_schedule_create_rejects_unschedulable_target(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "maintenance_action",
            "target_key": "maintenance.rebuild_index_kline_serving",
            "display_name": "错误配置",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_ops_schedule_create_returns_readable_once_time_validation_message(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "workflow",
            "target_key": "daily_market_close_maintenance",
            "display_name": "单次维护",
            "schedule_type": "once",
            "timezone": "Asia/Shanghai",
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "单次排程必须填写下次运行时间"


def test_ops_schedule_create_rejects_dataset_action_without_maintain_suffix(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "daily",
            "display_name": "错误配置",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_ops_schedule_create_rejects_dataset_action_missing_required_filter(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "stk_mins.maintain",
            "display_name": "股票分钟自动维护",
            "schedule_type": "cron",
            "cron_expr": "15 19 * * 1,2,3,4,5",
            "timezone": "Asia/Shanghai",
            "params_json": {"time_input": {"mode": "point"}, "filters": {}},
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "股票历史分钟行情 缺少必填参数：分钟周期"


def test_ops_schedule_list_update_pause_and_resume(app_client, user_factory, ops_schedule_factory) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="stock_basic.maintain",
        display_name="股票主数据刷新",
        status="active",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        created_by_user_id=admin.id,
        updated_by_user_id=admin.id,
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    list_response = app_client.get("/api/v1/ops/schedules", headers={"Authorization": f"Bearer {token}"})
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] == 1
    assert list_payload["items"][0]["id"] == schedule.id
    assert list_payload["items"][0]["target_display_name"] == "股票主数据"

    update_response = app_client.patch(
        f"/api/v1/ops/schedules/{schedule.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "display_name": "股票主数据晚间刷新",
            "cron_expr": "30 20 * * *",
        },
    )
    assert update_response.status_code == 200
    update_payload = update_response.json()
    assert update_payload["display_name"] == "股票主数据晚间刷新"
    assert update_payload["cron_expr"] == "30 20 * * *"

    pause_response = app_client.post(
        f"/api/v1/ops/schedules/{schedule.id}/pause",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"

    resume_response = app_client.post(
        f"/api/v1/ops/schedules/{schedule.id}/resume",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resume_response.status_code == 200
    resume_payload = resume_response.json()
    assert resume_payload["status"] == "active"
    assert resume_payload["next_run_at"] is not None

    revisions_response = app_client.get(
        f"/api/v1/ops/schedules/{schedule.id}/revisions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revisions_response.status_code == 200
    revision_actions = [item["action"] for item in revisions_response.json()["items"]]
    assert revision_actions == ["resumed", "paused", "updated"]


def test_ops_schedule_delete_removes_schedule_and_records_revision(app_client, user_factory, ops_schedule_factory) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="stock_basic.maintain",
        display_name="股票主数据刷新",
        status="paused",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        created_by_user_id=admin.id,
        updated_by_user_id=admin.id,
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    delete_response = app_client.delete(
        f"/api/v1/ops/schedules/{schedule.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["id"] == schedule.id
    assert delete_response.json()["status"] == "deleted"

    list_response = app_client.get("/api/v1/ops/schedules", headers={"Authorization": f"Bearer {token}"})
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 0

    # 删除后详情与修订查询都会返回 not_found，验证删除成功
    revisions_response = app_client.get(
        f"/api/v1/ops/schedules/{schedule.id}/revisions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revisions_response.status_code == 404
    assert revisions_response.json()["code"] == "not_found"


def test_ops_schedule_delete_active_schedule_pauses_before_delete(
    app_client,
    user_factory,
    ops_schedule_factory,
    db_session,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="stock_basic.maintain",
        display_name="股票主数据刷新",
        status="active",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        created_by_user_id=admin.id,
        updated_by_user_id=admin.id,
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    delete_response = app_client.delete(
        f"/api/v1/ops/schedules/{schedule.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_response.status_code == 200

    from src.ops.models.ops.config_revision import ConfigRevision
    from sqlalchemy import select

    revisions = list(
        db_session.scalars(
            select(ConfigRevision)
            .where(ConfigRevision.object_type == "schedule")
            .where(ConfigRevision.object_id == str(schedule.id))
            .order_by(ConfigRevision.id.asc())
        )
    )
    actions = [item.action for item in revisions]
    assert actions[-2:] == ["paused", "deleted"]


def test_ops_schedule_detail_returns_not_found_for_missing_schedule(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/schedules/9999", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert response.json()["message"] == "自动任务不存在"


def test_ops_schedule_once_requires_timezone_aware_next_run_at(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "stock_basic.maintain",
            "display_name": "单次任务",
            "schedule_type": "once",
            "timezone": "Asia/Shanghai",
            "next_run_at": "2026-03-31T09:00:00",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_ops_schedule_preview_returns_next_cron_occurrences(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules/preview",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "schedule_type": "cron",
            "cron_expr": "0 19 * * 1-5",
            "timezone": "Asia/Shanghai",
            "count": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schedule_type"] == "cron"
    assert payload["timezone"] == "Asia/Shanghai"
    assert len(payload["preview_times"]) == 3


def test_ops_schedule_preview_supports_monthly_last_day_policy(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules/preview",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "monthly_last_day",
            "count": 3,
        },
    )

    assert response.status_code == 200
    preview_times = response.json()["preview_times"]
    assert len(preview_times) == 3
    for item in preview_times:
        local_dt = datetime.fromisoformat(item).astimezone(ZoneInfo("Asia/Shanghai"))
        assert local_dt.hour == 19
        assert local_dt.minute == 0
        assert local_dt.day == monthrange(local_dt.year, local_dt.month)[1]


def test_ops_schedule_preview_supports_monthly_window_current_month_policy(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules/preview",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "monthly_window_current_month",
            "count": 3,
        },
    )

    assert response.status_code == 200
    preview_times = response.json()["preview_times"]
    assert len(preview_times) == 3
    for item in preview_times:
        local_dt = datetime.fromisoformat(item).astimezone(ZoneInfo("Asia/Shanghai"))
        assert local_dt.hour == 19
        assert local_dt.minute == 0
        assert local_dt.day == monthrange(local_dt.year, local_dt.month)[1]


def test_ops_schedule_create_supports_monthly_last_day_for_calendar_month_dataset(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "stk_period_bar_month.maintain",
            "display_name": "股票月线自动维护",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "monthly_last_day",
            "params_json": {"time_input": {"mode": "point"}},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_key"] == "stk_period_bar_month.maintain"
    assert payload["calendar_policy"] == "monthly_last_day"


def test_ops_schedule_create_supports_monthly_last_trading_day_for_trading_month_dataset(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "index_monthly.maintain",
            "display_name": "指数月线自动维护",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "monthly_last_trading_day",
            "next_run_at": "2099-01-01T19:00:00+08:00",
            "params_json": {"time_input": {"mode": "point"}},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_key"] == "index_monthly.maintain"
    assert payload["calendar_policy"] == "monthly_last_trading_day"


def test_ops_schedule_create_supports_monthly_window_for_index_weight_dataset(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "index_weight.maintain",
            "display_name": "指数成分权重自动维护",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "monthly_window_current_month",
            "params_json": {"time_input": {"mode": "range"}, "filters": {"index_code": "000300.SH"}},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_key"] == "index_weight.maintain"
    assert payload["calendar_policy"] == "monthly_window_current_month"


def test_ops_schedule_create_supports_trigger_day_single_range_for_dividend_and_holdernumber(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    for target_key, display_name in (
        ("dividend.maintain", "分红送股自动维护"),
        ("stk_holdernumber.maintain", "股东户数自动维护"),
    ):
        response = app_client.post(
            "/api/v1/ops/schedules",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "target_type": "dataset_action",
                "target_key": target_key,
                "display_name": display_name,
                "schedule_type": "cron",
                "cron_expr": "0 19 * * *",
                "timezone": "Asia/Shanghai",
                "calendar_policy": "trigger_day_single_range",
                "params_json": {"time_input": {"mode": "range"}},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["target_key"] == target_key
        assert payload["calendar_policy"] == "trigger_day_single_range"


def test_ops_schedule_create_rejects_trigger_day_single_range_for_unsupported_dataset(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "daily.maintain",
            "display_name": "股票日线自动维护",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "trigger_day_single_range",
            "params_json": {"time_input": {"mode": "range"}},
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "触发日单日区间策略只支持自然日公告区间且仅支持区间维护的数据集"


def test_ops_schedule_create_supports_trigger_day_point_for_news_datasets(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    for target_key, display_name in (
        ("news.maintain", "新闻快讯高频维护"),
        ("major_news.maintain", "新闻通讯高频维护"),
    ):
        response = app_client.post(
            "/api/v1/ops/schedules",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "target_type": "dataset_action",
                "target_key": target_key,
                "display_name": display_name,
                "schedule_type": "cron",
                "cron_expr": "*/3 * * * *",
                "timezone": "Asia/Shanghai",
                "calendar_policy": "trigger_day_point",
                "params_json": {"time_input": {"mode": "point"}},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["target_key"] == target_key
        assert payload["calendar_policy"] == "trigger_day_point"
        assert payload["cron_expr"] == "*/3 * * * *"


def test_ops_schedule_create_rejects_trigger_day_point_below_min_interval(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "news.maintain",
            "display_name": "新闻快讯高频维护",
            "schedule_type": "cron",
            "cron_expr": "*/2 * * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "trigger_day_point",
            "params_json": {"time_input": {"mode": "point"}},
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "日内高频策略最小间隔为 3 分钟"


def test_ops_schedule_create_rejects_trigger_day_point_for_unsupported_dataset(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "daily.maintain",
            "display_name": "股票日线自动维护",
            "schedule_type": "cron",
            "cron_expr": "*/3 * * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "trigger_day_point",
            "params_json": {"time_input": {"mode": "point"}},
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "触发日单日策略只支持新闻快讯和新闻通讯"


def test_ops_schedule_create_rejects_trigger_day_point_with_fixed_date(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "news.maintain",
            "display_name": "新闻快讯高频维护",
            "schedule_type": "cron",
            "cron_expr": "*/3 * * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "trigger_day_point",
            "params_json": {"time_input": {"mode": "point", "trade_date": "2026-05-14"}},
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "触发日单日策略不能与固定维护日期或窗口混用"


def test_ops_schedule_create_rejects_monthly_last_day_for_trading_month_dataset(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "index_monthly.maintain",
            "display_name": "指数月线自动维护",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "monthly_last_day",
            "params_json": {"time_input": {"mode": "point"}},
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "每月最后一天策略只支持自然月末数据集"


def test_ops_schedule_create_rejects_monthly_window_for_non_window_dataset(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "stk_period_bar_month.maintain",
            "display_name": "股票月线自动维护",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "monthly_window_current_month",
            "params_json": {"time_input": {"mode": "range"}},
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "自然月窗口策略只支持月窗口数据集"


def test_ops_schedule_create_rejects_monthly_last_trading_day_for_calendar_month_dataset(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "stk_period_bar_month.maintain",
            "display_name": "股票月线自动维护",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "monthly_last_trading_day",
            "params_json": {"time_input": {"mode": "point"}},
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "每月最后交易日策略只支持交易日月末数据集"


def test_ops_schedule_create_rejects_monthly_last_day_with_fixed_trade_date(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "stk_period_bar_month.maintain",
            "display_name": "股票月线自动维护",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "monthly_last_day",
            "params_json": {"time_input": {"mode": "point", "trade_date": "2026-04-30"}},
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "每月最后一天策略不能与固定维护日期混用"


def test_ops_schedule_create_rejects_monthly_last_trading_day_with_fixed_trade_date(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "index_monthly.maintain",
            "display_name": "指数月线自动维护",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "monthly_last_trading_day",
            "params_json": {"time_input": {"mode": "point", "trade_date": "2026-04-30"}},
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "每月最后交易日策略不能与固定维护日期混用"


def test_ops_schedule_create_rejects_monthly_window_with_fixed_window(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "index_weight.maintain",
            "display_name": "指数成分权重自动维护",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
            "calendar_policy": "monthly_window_current_month",
            "params_json": {
                "time_input": {
                    "mode": "range",
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-30",
                },
                "filters": {"index_code": "000300.SH"},
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "自然月窗口策略不能与固定维护日期或窗口混用"


def test_ops_schedule_preview_returns_once_next_run(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules/preview",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "schedule_type": "once",
            "timezone": "Asia/Shanghai",
            "next_run_at": "2099-01-01T09:00:00+08:00",
            "count": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schedule_type"] == "once"
    assert len(payload["preview_times"]) == 1
    assert payload["preview_times"][0].startswith("2099-01-01T01:00:00")


def test_ops_schedule_probe_mode_rejects_workflow_target(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "workflow",
            "target_key": "daily_market_close_maintenance",
            "display_name": "收盘探测触发",
            "schedule_type": "cron",
            "trigger_mode": "probe",
            "cron_expr": "0 19 * * 1-5",
            "timezone": "Asia/Shanghai",
            "probe_config": {
                "condition_kind": "freshness_latest_open",
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "trigger_mode.forbidden"


def test_ops_schedule_schedule_mode_rejects_workflow_probe_config(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "workflow",
            "target_key": "daily_market_close_maintenance",
            "display_name": "错误探测触发",
            "schedule_type": "cron",
            "trigger_mode": "schedule",
            "cron_expr": "0 19 * * 1-5",
            "timezone": "Asia/Shanghai",
            "probe_config": {
                "condition_kind": "freshness_latest_open",
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "probe_config.forbidden"


@pytest.mark.parametrize(
    ("probe_config", "error_type"),
    [
        ({"source_key": "tushare"}, "source_key.operator_forbidden"),
        ({"workflow_dataset_keys": ["daily"]}, "workflow_dataset_keys.operator_forbidden"),
    ],
)
def test_ops_schedule_rejects_operator_owned_probe_fields(app_client, user_factory, probe_config, error_type) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    token = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"}).json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "margin_detail.maintain",
            "display_name": "禁止运营端来源字段",
            "schedule_type": "cron",
            "trigger_mode": "probe",
            "cron_expr": "*/5 9 * * 1-5",
            "timezone": "Asia/Shanghai",
            "probe_config": probe_config,
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == error_type


def test_ops_schedule_schedule_mode_allows_workflow_without_probe_config(app_client, user_factory, db_session) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "workflow",
            "target_key": "daily_market_close_maintenance",
            "display_name": "收盘直接触发",
            "schedule_type": "cron",
            "trigger_mode": "schedule",
            "cron_expr": "0 19 * * 1-5",
            "timezone": "Asia/Shanghai",
        },
    )

    assert response.status_code == 200
    schedule_id = response.json()["id"]
    assert db_session.scalars(select(ProbeRule).where(ProbeRule.schedule_id == schedule_id)).all() == []


def test_schedule_probe_binding_pauses_invalid_legacy_workflow_without_validation() -> None:
    session = Mock()
    schedule = SimpleNamespace(
        id=42,
        status="paused",
        target_type="workflow",
        target_key="daily_market_close_maintenance",
        trigger_mode="probe",
        probe_config_json={"workflow_dataset_keys": ["daily"]},
    )

    ScheduleProbeBindingService().sync_for_schedule(session, schedule=schedule, actor_user_id=None)

    session.execute.assert_called_once()


def test_schedule_probe_binding_keeps_existing_rule_when_new_configuration_is_invalid(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
) -> None:
    schedule = ops_schedule_factory(
        target_key="margin_detail.maintain",
        trigger_mode="probe",
        probe_config_json={
            "condition_kind": "remote_margin_detail_ready",
            "window_start": "09:05",
            "window_end": "09:30",
            "probe_interval_seconds": 300,
            "max_triggers_per_day": 1,
        },
        params_json={"time_input": {"mode": "point"}, "filters": {}},
    )
    existing = probe_rule_factory(schedule_id=schedule.id, dataset_key="margin_detail", source_key="tushare")

    with pytest.raises(WebAppError) as error:
        ScheduleProbeBindingService().sync_for_schedule(db_session, schedule=schedule, actor_user_id=None)

    assert error.value.code == "probe_window.forbidden"
    assert db_session.scalar(select(ProbeRule).where(ProbeRule.id == existing.id)) is not None


def test_ops_schedule_remote_stk_mins_probe_mode_creates_probe_rule(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    create_response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "stk_mins.maintain",
            "display_name": "分钟源站就绪后同步",
            "schedule_type": "cron",
            "trigger_mode": "probe",
            "cron_expr": "*/5 15-18 * * 1-5",
            "timezone": "Asia/Shanghai",
            "probe_config": {
                "window_start": "15:20",
                "window_end": "18:30",
                "probe_interval_seconds": 300,
                "max_triggers_per_day": 1,
                "condition_kind": "remote_stk_mins_ready",
            },
            "params_json": {
                "time_input": {"mode": "point"},
                "filters": {"freq": ["1min", "5min"]},
            },
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["probe_config"]["condition_kind"] == "remote_stk_mins_ready"

    probe_response = app_client.get(
        f"/api/v1/ops/probes?schedule_id={created['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert probe_response.status_code == 200
    probe_payload = probe_response.json()
    assert probe_payload["total"] == 1
    rule = probe_payload["items"][0]
    assert rule["dataset_key"] == "stk_mins"
    assert rule["probe_condition_json"] == {"type": "remote_stk_mins_ready"}
    assert rule["on_success_action_json"]["action_key"] == "stk_mins.maintain"
    assert rule["source_key"] == "tushare"
    assert rule["on_success_action_json"]["request"]["filters"] == {"freq": ["1min", "5min"]}


def test_ops_schedule_remote_index_daily_probe_mode_creates_probe_rule(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    create_response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "index_daily.maintain",
            "display_name": "指数日线源站就绪后同步",
            "schedule_type": "cron",
            "trigger_mode": "probe",
            "cron_expr": "*/5 15-18 * * 1-5",
            "timezone": "Asia/Shanghai",
            "probe_config": {
                "window_start": "15:20",
                "window_end": "18:30",
                "probe_interval_seconds": 300,
                "max_triggers_per_day": 1,
                "condition_kind": "remote_index_daily_ready",
            },
            "params_json": {
                "time_input": {"mode": "point"},
                "filters": {"ts_code": ["000001.SH", "399001.SZ"]},
            },
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["probe_config"]["condition_kind"] == "remote_index_daily_ready"

    probe_response = app_client.get(
        f"/api/v1/ops/probes?schedule_id={created['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert probe_response.status_code == 200
    probe_payload = probe_response.json()
    assert probe_payload["total"] == 1
    rule = probe_payload["items"][0]
    assert rule["dataset_key"] == "index_daily"
    assert rule["probe_condition_json"] == {"type": "remote_index_daily_ready"}
    assert rule["on_success_action_json"]["action_key"] == "index_daily.maintain"
    assert rule["source_key"] == "tushare"
    assert rule["on_success_action_json"]["request"]["filters"] == {"ts_code": ["000001.SH", "399001.SZ"]}


def test_ops_schedule_remote_index_mins_probe_mode_creates_probe_rule(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    create_response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "index_mins.maintain",
            "display_name": "指数分钟行情源站就绪后同步",
            "schedule_type": "cron",
            "trigger_mode": "probe",
            "cron_expr": "*/5 15-18 * * 1-5",
            "timezone": "Asia/Shanghai",
            "probe_config": {
                "window_start": "15:20",
                "window_end": "18:30",
                "probe_interval_seconds": 300,
                "max_triggers_per_day": 1,
                "condition_kind": "remote_index_mins_ready",
            },
            "params_json": {
                "time_input": {"mode": "point"},
                "filters": {"freq": ["1min", "5min", "15min", "30min", "60min"]},
            },
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["probe_config"]["condition_kind"] == "remote_index_mins_ready"
    probe_response = app_client.get(
        f"/api/v1/ops/probes?schedule_id={created['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert probe_response.status_code == 200
    rule = probe_response.json()["items"][0]
    assert rule["dataset_key"] == "index_mins"
    assert rule["probe_condition_json"] == {"type": "remote_index_mins_ready"}
    assert rule["on_success_action_json"]["action_key"] == "index_mins.maintain"
    assert rule["on_success_action_json"]["request"]["filters"] == {
        "freq": ["1min", "5min", "15min", "30min", "60min"],
    }


def test_ops_schedule_remote_kpl_list_probe_mode_creates_probe_rule(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    create_response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "kpl_list.maintain",
            "display_name": "开盘啦榜单源站就绪后同步",
            "schedule_type": "cron",
            "trigger_mode": "probe",
            "cron_expr": "*/30 * * * *",
            "timezone": "Asia/Shanghai",
            "probe_config": {
                "window_start": "08:35",
                "window_end": "23:30",
                "probe_interval_seconds": 1800,
                "max_triggers_per_day": 1,
                "condition_kind": "remote_kpl_list_ready",
            },
            "params_json": {
                "time_input": {"mode": "point"},
                "filters": {},
            },
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["probe_config"]["condition_kind"] == "remote_kpl_list_ready"

    probe_response = app_client.get(
        f"/api/v1/ops/probes?schedule_id={created['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert probe_response.status_code == 200
    rule = probe_response.json()["items"][0]
    assert rule["dataset_key"] == "kpl_list"
    assert rule["probe_condition_json"] == {"type": "remote_kpl_list_ready"}
    assert rule["on_success_action_json"]["action_key"] == "kpl_list.maintain"
    assert rule["source_key"] == "tushare"
    assert rule["on_success_action_json"]["request"]["filters"] == {}


@pytest.mark.parametrize(
    ("payload_patch", "expected_code"),
    [
        (
            {
                "target_type": "workflow",
                "target_key": "daily_market_close_maintenance",
            },
            "trigger_mode.forbidden",
        ),
        (
            {
                "target_type": "dataset_action",
                "target_key": "daily.maintain",
            },
            "condition.unsupported",
        ),
        (
            {
                "params_json": {"time_input": {"mode": "point"}, "filters": {}},
            },
            "validation_error",
        ),
        (
            {
                "params_json": {
                    "time_input": {"mode": "point", "trade_date": "2026-05-29"},
                    "filters": {"freq": ["1min"]},
                },
            },
            "time_input.forbidden",
        ),
    ],
)
def test_ops_schedule_remote_stk_mins_probe_mode_rejects_invalid_binding(
    app_client,
    user_factory,
    payload_patch,
    expected_code,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    payload = {
        "target_type": "dataset_action",
        "target_key": "stk_mins.maintain",
        "display_name": "错误分钟源站探测",
        "schedule_type": "cron",
        "trigger_mode": "probe",
        "cron_expr": "*/5 15-18 * * 1-5",
        "timezone": "Asia/Shanghai",
        "probe_config": {
            "window_start": "15:20",
            "window_end": "18:30",
            "probe_interval_seconds": 300,
            "max_triggers_per_day": 1,
            "condition_kind": "remote_stk_mins_ready",
        },
        "params_json": {
            "time_input": {"mode": "point"},
            "filters": {"freq": ["1min"]},
        },
    }
    payload.update(payload_patch)

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == expected_code


@pytest.mark.parametrize(
    ("payload_patch", "expected_code"),
    [
        (
            {
                "target_type": "workflow",
                "target_key": "daily_market_close_maintenance",
            },
            "trigger_mode.forbidden",
        ),
        (
            {
                "target_type": "dataset_action",
                "target_key": "daily.maintain",
            },
            "condition.unsupported",
        ),
        (
            {
                "calendar_policy": "trigger_day_point",
            },
            "validation_error",
        ),
        (
            {
                "params_json": {
                    "time_input": {"mode": "point", "trade_date": "2026-05-29"},
                    "filters": {},
                },
            },
            "time_input.forbidden",
        ),
        (
            {
                "params_json": {
                    "time_input": {"mode": "range", "start_date": "2026-05-01", "end_date": "2026-05-29"},
                    "filters": {},
                },
            },
            "time_input.forbidden",
        ),
    ],
)
def test_ops_schedule_remote_index_daily_probe_mode_rejects_invalid_binding(
    app_client,
    user_factory,
    payload_patch,
    expected_code,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    payload = {
        "target_type": "dataset_action",
        "target_key": "index_daily.maintain",
        "display_name": "错误指数日线源站探测",
        "schedule_type": "cron",
        "trigger_mode": "probe",
        "cron_expr": "*/5 15-18 * * 1-5",
        "timezone": "Asia/Shanghai",
        "probe_config": {
            "window_start": "15:20",
            "window_end": "18:30",
            "probe_interval_seconds": 300,
            "max_triggers_per_day": 1,
            "condition_kind": "remote_index_daily_ready",
        },
        "params_json": {
            "time_input": {"mode": "point"},
            "filters": {},
        },
    }
    payload.update(payload_patch)

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == expected_code


def test_ops_schedule_remote_idx_factor_pro_probe_mode_creates_empty_filter_rule(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]
    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "idx_factor_pro.maintain",
            "display_name": "指数技术因子源站探测",
            "schedule_type": "cron",
            "trigger_mode": "probe",
            "cron_expr": "*/5 15-18 * * 1-5",
            "timezone": "Asia/Shanghai",
            "probe_config": {
                "window_start": "15:20",
                "window_end": "18:30",
                "probe_interval_seconds": 300,
                "max_triggers_per_day": 1,
                "condition_kind": "remote_idx_factor_pro_ready",
            },
            "params_json": {"time_input": {"mode": "point"}, "filters": {}},
        },
    )

    assert response.status_code == 200
    created = response.json()
    probe_response = app_client.get(
        f"/api/v1/ops/probes?schedule_id={created['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert probe_response.status_code == 200
    rule = probe_response.json()["items"][0]
    assert rule["dataset_key"] == "idx_factor_pro"
    assert rule["probe_condition_json"] == {"type": "remote_idx_factor_pro_ready"}
    assert rule["on_success_action_json"]["action_key"] == "idx_factor_pro.maintain"
    assert rule["on_success_action_json"]["request"]["filters"] == {}


@pytest.mark.parametrize(
    ("payload_patch", "expected_code"),
    [
        ({"target_key": "index_daily.maintain"}, "condition.unsupported"),
        (
            {"target_type": "workflow", "target_key": "daily_market_close_maintenance"},
            "trigger_mode.forbidden",
        ),
        ({"trigger_mode": "schedule"}, "trigger_mode.forbidden"),
        ({"calendar_policy": "monthly_last_day"}, "validation_error"),
        (
            {"params_json": {"time_input": {"mode": "point"}, "filters": {"ts_code": "000001.SH"}}},
            "filters.forbidden",
        ),
        (
            {"params_json": {"time_input": {"mode": "range", "start_date": "2026-05-01", "end_date": "2026-05-29"}, "filters": {}}},
            "time_input.forbidden",
        ),
        (
            {"probe_config": {"condition_kind": "remote_idx_factor_pro_ready", "probe_interval_seconds": 299}},
            "probe_config.invalid",
        ),
        (
            {"probe_config": {"condition_kind": "remote_idx_factor_pro_ready", "max_triggers_per_day": 2}},
            "probe_config.forbidden",
        ),
    ],
)
def test_ops_schedule_remote_idx_factor_pro_probe_mode_rejects_invalid_binding(
    app_client,
    user_factory,
    payload_patch,
    expected_code,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]
    payload = {
        "target_type": "dataset_action",
        "target_key": "idx_factor_pro.maintain",
        "display_name": "错误指数技术因子源站探测",
        "schedule_type": "cron",
        "trigger_mode": "probe",
        "cron_expr": "*/5 15-18 * * 1-5",
        "timezone": "Asia/Shanghai",
        "probe_config": {
            "window_start": "15:20",
            "window_end": "18:30",
            "probe_interval_seconds": 300,
            "max_triggers_per_day": 1,
            "condition_kind": "remote_idx_factor_pro_ready",
        },
        "params_json": {"time_input": {"mode": "point"}, "filters": {}},
    }
    payload.update(payload_patch)

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == expected_code


@pytest.mark.parametrize(
    ("payload_patch", "expected_code"),
    [
        (
            {"target_key": "index_daily.maintain"},
            "condition.unsupported",
        ),
        (
            {"probe_config": {"condition_kind": "remote_index_mins_ready", "probe_interval_seconds": 299}},
            "probe_config.invalid",
        ),
        (
            {
                "params_json": {
                    "time_input": {"mode": "point"},
                    "filters": {"freq": ["1min", "5min", "15min", "30min"]},
                },
            },
            "filters.incomplete",
        ),
        (
            {
                "params_json": {
                    "time_input": {"mode": "point", "trade_date": "2026-05-29"},
                    "filters": {"freq": ["1min", "5min", "15min", "30min", "60min"]},
                },
            },
            "time_input.forbidden",
        ),
    ],
)
def test_ops_schedule_remote_index_mins_probe_mode_rejects_invalid_binding(
    app_client,
    user_factory,
    payload_patch,
    expected_code,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]
    payload = {
        "target_type": "dataset_action",
        "target_key": "index_mins.maintain",
        "display_name": "错误指数分钟行情源站探测",
        "schedule_type": "cron",
        "trigger_mode": "probe",
        "cron_expr": "*/5 15-18 * * 1-5",
        "timezone": "Asia/Shanghai",
        "probe_config": {
            "window_start": "15:20",
            "window_end": "18:30",
            "probe_interval_seconds": 300,
            "max_triggers_per_day": 1,
            "condition_kind": "remote_index_mins_ready",
        },
        "params_json": {
            "time_input": {"mode": "point"},
            "filters": {"freq": ["1min", "5min", "15min", "30min", "60min"]},
        },
    }
    payload.update(payload_patch)

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == expected_code


def test_ops_schedule_index_mins_rejects_local_freshness_probe(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "index_mins.maintain",
            "display_name": "错误本地分钟线探测",
            "schedule_type": "cron",
            "trigger_mode": "probe",
            "cron_expr": "*/5 15-18 * * 1-5",
            "timezone": "Asia/Shanghai",
            "probe_config": {
                "window_start": "15:20",
                "window_end": "18:30",
                "probe_interval_seconds": 300,
                "max_triggers_per_day": 1,
                "condition_kind": "freshness_latest_open",
            },
            "params_json": {"time_input": {"mode": "point"}, "filters": {}},
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "condition.unsupported"


def test_ops_schedule_margin_rejects_local_freshness_probe(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "margin.maintain",
            "display_name": "错误本地融资融券探测",
            "schedule_type": "cron",
            "trigger_mode": "probe",
            "cron_expr": "*/5 9 * * 1-5",
            "timezone": "Asia/Shanghai",
            "probe_config": {
                "window_start": "09:00",
                "window_end": "09:30",
                "probe_interval_seconds": 300,
                "max_triggers_per_day": 1,
                "condition_kind": "freshness_latest_open",
            },
            "params_json": {"time_input": {"mode": "point"}, "filters": {}},
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "condition.unsupported"


@pytest.mark.parametrize(
    ("payload_patch", "expected_code"),
    [
        (
            {"trigger_mode": "schedule_probe_fallback"},
            "trigger_mode.forbidden",
        ),
        (
            {
                "target_type": "workflow",
                "target_key": "daily_market_close_maintenance",
            },
            "trigger_mode.forbidden",
        ),
        (
            {
                "params_json": {
                    "time_input": {"mode": "point", "trade_date": "2026-05-29"},
                    "filters": {},
                },
            },
            "time_input.forbidden",
        ),
    ],
)
def test_ops_schedule_remote_kpl_list_probe_mode_rejects_invalid_binding(
    app_client,
    user_factory,
    payload_patch,
    expected_code,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    payload = {
        "target_type": "dataset_action",
        "target_key": "kpl_list.maintain",
        "display_name": "错误开盘啦榜单源站探测",
        "schedule_type": "cron",
        "trigger_mode": "probe",
        "cron_expr": "*/30 * * * *",
        "timezone": "Asia/Shanghai",
        "probe_config": {
            "window_start": "08:35",
            "window_end": "23:30",
            "probe_interval_seconds": 1800,
            "max_triggers_per_day": 1,
            "condition_kind": "remote_kpl_list_ready",
        },
        "params_json": {
            "time_input": {"mode": "point"},
            "filters": {},
        },
    }
    payload.update(payload_patch)

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == expected_code


@pytest.mark.parametrize(
    ("payload_patch", "expected_code"),
    [
        ({"trigger_mode": "schedule_probe_fallback"}, "trigger_mode.forbidden"),
        (
            {"target_type": "workflow", "target_key": "daily_market_close_maintenance"},
            "trigger_mode.forbidden",
        ),
        (
            {"params_json": {"time_input": {"mode": "point"}, "filters": {"exchange_id": ["SSE"]}}},
            "filters.forbidden",
        ),
        (
            {"probe_config": {"window_start": "09:05", "window_end": "09:30", "probe_interval_seconds": 300, "max_triggers_per_day": 1, "condition_kind": "remote_margin_ready"}},
            "probe_window.forbidden",
        ),
        (
            {"probe_config": {"window_start": "09:00", "window_end": "09:30", "probe_interval_seconds": 600, "max_triggers_per_day": 1, "condition_kind": "remote_margin_ready"}},
            "probe_config.forbidden",
        ),
        (
            {"probe_config": {"window_start": "09:00", "window_end": "09:30", "probe_interval_seconds": 300, "max_triggers_per_day": 2, "condition_kind": "remote_margin_ready"}},
            "probe_config.forbidden",
        ),
    ],
)
def test_ops_schedule_remote_margin_probe_rejects_invalid_binding(
    app_client,
    user_factory,
    payload_patch,
    expected_code,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]
    payload = {
        "target_type": "dataset_action",
        "target_key": "margin.maintain",
        "display_name": "融资融券汇总源站探测",
        "schedule_type": "cron",
        "trigger_mode": "probe",
        "cron_expr": "*/5 9 * * 1-5",
        "timezone": "Asia/Shanghai",
        "probe_config": {
            "window_start": "09:00",
            "window_end": "09:30",
            "probe_interval_seconds": 300,
            "max_triggers_per_day": 1,
            "condition_kind": "remote_margin_ready",
        },
        "params_json": {"time_input": {"mode": "point"}, "filters": {}},
    }
    payload.update(payload_patch)

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == expected_code


def test_ops_schedule_remote_margin_probe_creates_fixed_probe_rule(app_client, user_factory, db_session) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "margin.maintain",
            "display_name": "融资融券汇总源站探测",
            "schedule_type": "cron",
            "trigger_mode": "probe",
            "cron_expr": "*/5 9 * * 1-5",
            "timezone": "Asia/Shanghai",
            "probe_config": {
                "window_start": "09:00",
                "window_end": "09:30",
                "probe_interval_seconds": 300,
                "max_triggers_per_day": 1,
                "condition_kind": "remote_margin_ready",
            },
            "params_json": {"time_input": {"mode": "point"}, "filters": {}},
        },
    )

    assert response.status_code == 200
    schedule_id = response.json()["id"]
    rules = db_session.scalars(select(ProbeRule).where(ProbeRule.schedule_id == schedule_id)).all()
    assert len(rules) == 1
    assert rules[0].probe_condition_json == {"type": "remote_margin_ready"}
    assert rules[0].window_start == "09:00"
    assert rules[0].window_end == "09:30"
    assert rules[0].probe_interval_seconds == 300


def test_schedule_automation_capability_rejects_remote_index_daily_probe_with_calendar_policy() -> None:
    schedule = SimpleNamespace(
        trigger_mode="probe",
        target_type="dataset_action",
        target_key="index_daily.maintain",
        calendar_policy="monthly_last_day",
        params_json={"time_input": {"mode": "point"}, "filters": {}},
        probe_config_json={
            "window_start": "15:20",
            "window_end": "18:30",
            "probe_interval_seconds": 300,
            "max_triggers_per_day": 1,
            "condition_kind": "remote_index_daily_ready",
        },
        timezone="Asia/Shanghai",
    )

    with pytest.raises(WebAppError, match="日期策略混用"):
        ScheduleAutomationCapabilityResolver().validate_schedule(schedule)


@pytest.mark.parametrize(
    "target_key",
    (
        "fund_company.maintain",
        "mkt_idx_bmk.maintain",
        "fund_basic.maintain",
        "fund_manager.maintain",
    ),
)
def test_schedule_automation_capability_keeps_public_fund_snapshots_schedule_only(target_key: str) -> None:
    resolver = ScheduleAutomationCapabilityResolver()
    capability = resolver.resolve(target_type="dataset_action", target_key=target_key)
    assert capability is not None
    assert [item.mode for item in capability.trigger_options] == ["schedule"]
    assert capability.probe_conditions == ()

    schedule = SimpleNamespace(
        trigger_mode="schedule",
        target_type="dataset_action",
        target_key=target_key,
        calendar_policy=None,
        params_json={"time_input": {"mode": "none"}, "filters": {}},
        probe_config_json={},
        timezone="Asia/Shanghai",
    )
    assert resolver.validate_schedule(schedule).trigger_mode == "schedule"

    schedule.trigger_mode = "probe"
    schedule.probe_config_json = {"condition_kind": "remote_margin_ready"}
    with pytest.raises(WebAppError, match="不支持所选触发方式"):
        resolver.validate_schedule(schedule)
