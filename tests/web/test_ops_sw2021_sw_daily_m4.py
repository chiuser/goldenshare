from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.task_run import TaskRun


def _admin_headers(app_client, user_factory) -> dict[str, str]:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _items_by_key(payload: dict, *, key: str) -> dict[str, dict]:
    return {item[key]: item for group in payload["groups"] for item in group["items"]}


def test_sw_daily_ops_catalog_card_and_completeness_use_open_day_contract(
    app_client,
    user_factory,
) -> None:
    headers = _admin_headers(app_client, user_factory)

    actions_response = app_client.get("/api/v1/ops/manual-actions", headers=headers)
    cards_response = app_client.get(
        "/api/v1/ops/dataset-cards?source_key=tushare",
        headers=headers,
    )
    rules_response = app_client.get(
        "/api/v1/ops/review/date-completeness/rules",
        headers=headers,
    )

    assert actions_response.status_code == 200
    actions = {
        action["action_key"]: action
        for group in actions_response.json()["groups"]
        for action in group["actions"]
    }
    action = actions["sw_daily.maintain"]
    assert action["resource_key"] == "sw_daily"
    assert action["filters"] == []
    assert action["date_model"] == {
        "date_axis": "trade_open_day",
        "bucket_rule": "every_open_day",
        "window_mode": "point_or_range",
        "input_shape": "trade_date_or_start_end",
        "observed_field": "trade_date",
        "audit_applicable": True,
        "not_applicable_reason": None,
    }
    assert action["time_form"]["default_mode"] == "point"
    assert action["time_form"]["max_units_per_execution"] == 60
    assert [mode["mode"] for mode in action["time_form"]["modes"]] == [
        "point",
        "range",
    ]
    assert all(
        mode["selection_rule"] == "trading_day_only"
        for mode in action["time_form"]["modes"]
    )

    assert cards_response.status_code == 200
    cards = _items_by_key(cards_response.json(), key="detail_dataset_key")
    card = cards["sw_daily"]
    assert card["group_key"] == "board_theme"
    assert card["freshness_policy"] == "continuous_open_day"
    assert card["raw_table"] is None
    assert card["raw_table_label"] is None
    assert card["target_table"] == "core_serving.sw_industry_daily"
    assert card["primary_action_key"] == "sw_daily.maintain"

    assert rules_response.status_code == 200
    supported_group = next(
        group
        for group in rules_response.json()["groups"]
        if group["group_key"] == "supported"
    )
    supported = {item["dataset_key"]: item for item in supported_group["items"]}
    rule = supported["sw_daily"]
    assert rule["date_axis"] == "trade_open_day"
    assert rule["bucket_rule"] == "every_open_day"
    assert rule["observed_field"] == "trade_date"
    assert rule["audit_scope"] == "date_bucket"
    assert rule["audit_applicable"] is True


def test_sw_daily_manual_action_accepts_point_and_range_without_filters(
    app_client,
    user_factory,
    trade_calendar_factory,
) -> None:
    headers = _admin_headers(app_client, user_factory)
    trade_calendar_factory(
        trade_date=date(2026, 8, 13),
        pretrade_date=date(2026, 8, 12),
    )
    trade_calendar_factory(
        trade_date=date(2026, 8, 14),
        pretrade_date=date(2026, 8, 13),
    )

    point = app_client.post(
        "/api/v1/ops/manual-actions/sw_daily.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "point", "trade_date": "2026-08-14"},
            "filters": {},
        },
    )
    assert point.status_code == 200
    assert point.json()["run"]["resource_key"] == "sw_daily"
    assert point.json()["run"]["time_input"] == {
        "mode": "point",
        "trade_date": "2026-08-14",
    }
    assert point.json()["run"]["filters"] == {}

    range_response = app_client.post(
        "/api/v1/ops/manual-actions/sw_daily.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {
                "mode": "range",
                "start_date": "2026-08-13",
                "end_date": "2026-08-14",
            },
            "filters": {},
        },
    )
    assert range_response.status_code == 200
    assert range_response.json()["run"]["time_input"] == {
        "mode": "range",
        "start_date": "2026-08-13",
        "end_date": "2026-08-14",
    }


@pytest.mark.parametrize(
    "payload",
    (
        {"time_input": {"mode": "none"}, "filters": {}},
        {
            "time_input": {"mode": "point", "trade_date": "2026-08-14"},
            "filters": {"ts_code": "850412.SI"},
        },
        {
            "time_input": {
                "mode": "range",
                "start_date": "2026-08-14",
            },
            "filters": {},
        },
    ),
)
def test_sw_daily_manual_action_rejects_unsupported_intents(
    app_client,
    user_factory,
    payload: dict,
) -> None:
    headers = _admin_headers(app_client, user_factory)
    response = app_client.post(
        "/api/v1/ops/manual-actions/sw_daily.maintain/task-runs",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_sw_daily_manual_action_rejects_non_open_day_and_sixty_one_units(
    app_client,
    user_factory,
    db_session,
) -> None:
    headers = _admin_headers(app_client, user_factory)
    non_open = date(2026, 8, 15)
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=non_open,
            is_open=False,
            pretrade_date=date(2026, 8, 14),
        )
    )
    start_date = date(2026, 1, 1)
    db_session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=start_date + timedelta(days=index),
                is_open=True,
                pretrade_date=(start_date + timedelta(days=index - 1))
                if index
                else None,
            )
            for index in range(61)
        ]
    )
    db_session.commit()

    before_ids = set(db_session.scalars(select(TaskRun.id)).all())
    point = app_client.post(
        "/api/v1/ops/manual-actions/sw_daily.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "point", "trade_date": non_open.isoformat()},
            "filters": {},
        },
    )
    assert point.status_code == 422
    assert point.json()["code"] == "trade_date_not_open"
    assert set(db_session.scalars(select(TaskRun.id)).all()) == before_ids

    too_wide = app_client.post(
        "/api/v1/ops/manual-actions/sw_daily.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {
                "mode": "range",
                "start_date": start_date.isoformat(),
                "end_date": (start_date + timedelta(days=60)).isoformat(),
            },
            "filters": {},
        },
    )
    assert too_wide.status_code == 422
    assert too_wide.json()["code"] == "units_exceeded"
    assert set(db_session.scalars(select(TaskRun.id)).all()) == before_ids
