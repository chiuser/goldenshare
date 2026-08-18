from __future__ import annotations

import pytest


def _admin_headers(app_client, user_factory) -> dict[str, str]:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_index_member_all_ops_catalog_and_card_use_snapshot_contract(
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
    action = actions["index_member_all.maintain"]
    assert action["resource_key"] == "index_member_all"
    assert action["filters"] == []
    assert action["date_model"]["input_shape"] == "none"
    assert action["date_model"]["audit_applicable"] is False
    assert action["time_form"]["default_mode"] == "none"
    assert [mode["mode"] for mode in action["time_form"]["modes"]] == ["none"]

    assert cards_response.status_code == 200
    cards = {
        item["detail_dataset_key"]: item
        for group in cards_response.json()["groups"]
        for item in group["items"]
    }
    card = cards["index_member_all"]
    assert card["group_key"] == "board_theme"
    assert card["freshness_policy"] == "snapshot_run_trace"
    assert card["raw_table"] is None
    assert card["raw_table_label"] is None
    assert card["target_table"] == "core_serving.sw_industry_member"
    assert card["primary_action_key"] == "index_member_all.maintain"


def test_index_member_all_manual_action_accepts_only_unfiltered_no_time_intent(
    app_client,
    user_factory,
) -> None:
    headers = _admin_headers(app_client, user_factory)

    accepted = app_client.post(
        "/api/v1/ops/manual-actions/index_member_all.maintain/task-runs",
        headers=headers,
        json={"time_input": {"mode": "none"}, "filters": {}},
    )
    assert accepted.status_code == 200
    assert accepted.json()["run"]["resource_key"] == "index_member_all"
    assert accepted.json()["run"]["time_input"] == {"mode": "none"}
    assert accepted.json()["run"]["filters"] == {}


@pytest.mark.parametrize(
    "payload",
    (
        {"time_input": {"mode": "none"}, "filters": {"is_new": "Y"}},
        {
            "time_input": {"mode": "none"},
            "filters": {"l1_code": "801040.SI"},
        },
        {
            "time_input": {"mode": "none"},
            "filters": {"l2_code": "801045.SI"},
        },
        {
            "time_input": {"mode": "none"},
            "filters": {"l3_code": "850412.SI"},
        },
        {
            "time_input": {"mode": "none"},
            "filters": {"ts_code": "000001.SZ"},
        },
        {
            "time_input": {"mode": "point", "trade_date": "2026-08-18"},
            "filters": {},
        },
        {
            "time_input": {
                "mode": "range",
                "start_date": "2026-08-01",
                "end_date": "2026-08-18",
            },
            "filters": {},
        },
    ),
)
def test_index_member_all_rejects_all_scoped_inputs(
    app_client,
    user_factory,
    payload: dict,
) -> None:
    headers = _admin_headers(app_client, user_factory)
    response = app_client.post(
        "/api/v1/ops/manual-actions/index_member_all.maintain/task-runs",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
