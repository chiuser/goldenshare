from __future__ import annotations


def test_ops_std_rules_reject_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/std-rules/mapping", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_std_mapping_rule_crud_like_flow(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    created = app_client.post(
        "/api/v1/ops/std-rules/mapping",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "dataset_key": "security_master",
            "source_key": "biying",
            "src_field": "dm",
            "std_field": "ts_code",
            "transform_fn": "upper",
            "status": "active",
            "rule_set_version": 1,
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["total"] == 1
    rule_id = payload["items"][0]["id"]
    assert payload["items"][0]["src_field"] == "dm"
    assert payload["items"][0]["std_field"] == "ts_code"

    updated = app_client.patch(
        f"/api/v1/ops/std-rules/mapping/{rule_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"transform_fn": "normalize_stock_code", "rule_set_version": 2},
    )
    assert updated.status_code == 200
    changed = [item for item in updated.json()["items"] if item["id"] == rule_id][0]
    assert changed["transform_fn"] == "normalize_stock_code"
    assert changed["rule_set_version"] == 2

    disabled = app_client.post(
        f"/api/v1/ops/std-rules/mapping/{rule_id}/disable",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert disabled.status_code == 200
    state = [item for item in disabled.json()["items"] if item["id"] == rule_id][0]
    assert state["status"] == "disabled"

    enabled = app_client.post(
        f"/api/v1/ops/std-rules/mapping/{rule_id}/enable",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert enabled.status_code == 200
    state = [item for item in enabled.json()["items"] if item["id"] == rule_id][0]
    assert state["status"] == "active"


def test_ops_std_cleansing_rule_crud_like_flow(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    created = app_client.post(
        "/api/v1/ops/std-rules/cleansing",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "dataset_key": "security_master",
            "source_key": "biying",
            "rule_type": "required_fields",
            "target_fields_json": ["ts_code", "name"],
            "condition_expr": None,
            "action": "drop_row",
            "status": "active",
            "rule_set_version": 1,
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["total"] == 1
    rule_id = payload["items"][0]["id"]
    assert payload["items"][0]["action"] == "drop_row"

    updated = app_client.patch(
        f"/api/v1/ops/std-rules/cleansing/{rule_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"action": "fill_default", "target_fields_json": ["ts_code", "name", "exchange"]},
    )
    assert updated.status_code == 200
    changed = [item for item in updated.json()["items"] if item["id"] == rule_id][0]
    assert changed["action"] == "fill_default"
    assert changed["target_fields_json"] == ["ts_code", "name", "exchange"]

    disabled = app_client.post(
        f"/api/v1/ops/std-rules/cleansing/{rule_id}/disable",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert disabled.status_code == 200
    state = [item for item in disabled.json()["items"] if item["id"] == rule_id][0]
    assert state["status"] == "disabled"
