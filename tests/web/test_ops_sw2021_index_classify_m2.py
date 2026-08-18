from __future__ import annotations

import pytest


def _admin_headers(app_client, user_factory) -> dict[str, str]:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_index_classify_ops_catalog_and_card_use_generic_contract(
    app_client,
    user_factory,
) -> None:
    headers = _admin_headers(app_client, user_factory)

    actions_response = app_client.get("/api/v1/ops/manual-actions", headers=headers)
    cards_response = app_client.get(
        "/api/v1/ops/dataset-cards?source_key=tushare",
        headers=headers,
    )

    assert actions_response.status_code == 200
    actions = {
        action["action_key"]: action
        for group in actions_response.json()["groups"]
        for action in group["actions"]
    }
    action = actions["index_classify.maintain"]
    assert action["resource_key"] == "index_classify"
    assert action["filters"] == []
    assert action["date_model"]["input_shape"] == "none"
    assert action["date_model"]["audit_applicable"] is False
    assert action["time_form"]["default_mode"] == "none"
    assert action["time_form"]["modes"] == [
        {
            "mode": "none",
            "label": "按默认策略处理",
            "description": "不填写时间条件，按该维护对象默认策略执行。",
            "control": "none",
            "selection_rule": "none",
            "date_field": None,
        }
    ]

    assert cards_response.status_code == 200
    cards = {
        item["detail_dataset_key"]: item
        for group in cards_response.json()["groups"]
        for item in group["items"]
    }
    card = cards["index_classify"]
    assert card["group_key"] == "board_theme"
    assert card["freshness_policy"] == "snapshot_run_trace"
    assert card["raw_table"] is None
    assert card["raw_table_label"] is None
    assert card["target_table"] == "core_serving.sw_industry_classification"
    assert card["primary_action_key"] == "index_classify.maintain"


def test_index_classify_manual_action_accepts_only_unfiltered_no_time_intent(
    app_client,
    user_factory,
) -> None:
    headers = _admin_headers(app_client, user_factory)

    accepted = app_client.post(
        "/api/v1/ops/manual-actions/index_classify.maintain/task-runs",
        headers=headers,
        json={"time_input": {"mode": "none"}, "filters": {}},
    )
    assert accepted.status_code == 200
    assert accepted.json()["run"]["resource_key"] == "index_classify"
    assert accepted.json()["run"]["time_input"] == {"mode": "none"}
    assert accepted.json()["run"]["filters"] == {}

    for payload in (
        {"time_input": {"mode": "none"}, "filters": {"src": "SW2014"}},
        {
            "time_input": {"mode": "point", "trade_date": "2026-08-18"},
            "filters": {},
        },
    ):
        rejected = app_client.post(
            "/api/v1/ops/manual-actions/index_classify.maintain/task-runs",
            headers=headers,
            json=payload,
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "validation_error"


@pytest.mark.parametrize(
    "payload",
    (
        {
            "time_input": {
                "mode": "range",
                "start_date": "2026-08-01",
                "end_date": "2026-08-18",
            },
            "filters": {},
        },
        {"time_input": {"mode": "none"}, "filters": {"level": "L1"}},
        {"time_input": {"mode": "none"}, "filters": {"index_code": "801010.SI"}},
    ),
)
def test_index_classify_rejects_all_scoped_maintenance_inputs(
    app_client,
    user_factory,
    payload: dict,
) -> None:
    headers = _admin_headers(app_client, user_factory)
    response = app_client.post(
        "/api/v1/ops/manual-actions/index_classify.maintain/task-runs",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
