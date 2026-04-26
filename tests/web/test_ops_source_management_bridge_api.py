from __future__ import annotations

from datetime import date, datetime, timezone


def test_ops_source_management_bridge_requires_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/source-management/bridge", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_source_management_bridge_returns_aggregated_payload(
    app_client,
    user_factory,
    probe_rule_factory,
    resolution_release_factory,
    resolution_release_stage_status_factory,
    dataset_layer_snapshot_history_factory,
    db_session,
) -> None:
    from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
    from src.ops.models.ops.std_mapping_rule import StdMappingRule

    admin = user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    probe_rule_factory(name="p1", dataset_key="daily", source_key="tushare", status="active")
    probe_rule_factory(name="p2", dataset_key="etf_basic", source_key="biying", status="paused")

    resolution_release_factory(dataset_key="daily", target_policy_version=1, status="running", triggered_by_user_id=admin.id)
    rel2 = resolution_release_factory(dataset_key="daily", target_policy_version=2, status="completed", triggered_by_user_id=admin.id)
    resolution_release_stage_status_factory(
        release_id=rel2.id,
        dataset_key="daily",
        source_key="tushare",
        stage="std",
        status="success",
    )

    db_session.add(
        StdMappingRule(
            dataset_key="daily",
            source_key="biying",
            src_field="dm",
            std_field="ts_code",
            status="active",
            rule_set_version=1,
            created_by_user_id=admin.id,
            updated_by_user_id=admin.id,
        )
    )
    db_session.add(
        StdCleansingRule(
            dataset_key="daily",
            source_key="biying",
            rule_type="required_fields",
            target_fields_json=["ts_code"],
            action="drop_row",
            status="disabled",
            rule_set_version=1,
            created_by_user_id=admin.id,
            updated_by_user_id=admin.id,
        )
    )
    db_session.commit()

    dataset_layer_snapshot_history_factory(
        snapshot_date=date(2026, 4, 14),
        dataset_key="daily",
        source_key="tushare",
        stage="serving",
        status="healthy",
        calculated_at=datetime(2026, 4, 14, 8, 0, tzinfo=timezone.utc),
    )
    dataset_layer_snapshot_history_factory(
        snapshot_date=date(2026, 4, 14),
        dataset_key="etf_basic",
        source_key="biying",
        stage="std",
        status="failed",
        calculated_at=datetime(2026, 4, 14, 8, 5, tzinfo=timezone.utc),
    )

    response = app_client.get("/api/v1/ops/source-management/bridge", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["probe_total"] == 2
    assert payload["summary"]["probe_active"] == 1
    assert payload["summary"]["release_total"] == 2
    assert payload["summary"]["release_running"] == 1
    assert payload["summary"]["std_mapping_total"] == 1
    assert payload["summary"]["std_mapping_active"] == 1
    assert payload["summary"]["std_cleansing_total"] == 1
    assert payload["summary"]["std_cleansing_active"] == 0
    assert payload["summary"]["layer_latest_total"] == 2
    assert payload["summary"]["layer_latest_failed"] == 1
    probe_by_key = {item["dataset_key"]: item for item in payload["probe_rules"]}
    assert probe_by_key["daily"]["dataset_display_name"] == "股票日线"
    assert payload["releases"][0]["dataset_display_name"] == "股票日线"
    assert payload["std_mapping_rules"][0]["dataset_display_name"] == "股票日线"
    assert payload["std_cleansing_rules"][0]["dataset_display_name"] == "股票日线"
    latest_by_key = {item["dataset_key"]: item for item in payload["layer_latest"]}
    assert latest_by_key["daily"]["dataset_display_name"] == "股票日线"
