from __future__ import annotations

from datetime import date, datetime, timezone


def test_ops_pipeline_modes_requires_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/pipeline-modes", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_pipeline_modes_returns_mode_and_config_status(app_client, user_factory, db_session) -> None:
    from src.foundation.models.meta.dataset_resolution_policy import DatasetResolutionPolicy
    from src.ops.models.ops.dataset_pipeline_mode import DatasetPipelineMode
    from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
    from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
    from src.ops.models.ops.std_mapping_rule import StdMappingRule

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            DatasetStatusSnapshot(
                dataset_key="stock_basic",
                resource_key="stock_basic",
                display_name="股票主数据",
                domain_key="reference",
                domain_display_name="基础主数据",
                target_table="core_serving.security_serving",
                cadence="reference",
                freshness_status="fresh",
                snapshot_date=date(2026, 4, 15),
                last_calculated_at=now,
            ),
            DatasetPipelineMode(
                dataset_key="stock_basic",
                mode="multi_source_pipeline",
                source_scope="tushare,biying",
                raw_enabled=True,
                std_enabled=True,
                resolution_enabled=True,
                serving_enabled=True,
            ),
            StdMappingRule(
                dataset_key="stock_basic",
                source_key="tushare",
                src_field="*",
                std_field="*",
                src_type=None,
                std_type=None,
                transform_fn="identity_pass_through",
                lineage_preserved=True,
                status="active",
                rule_set_version=1,
            ),
            StdCleansingRule(
                dataset_key="stock_basic",
                source_key="tushare",
                rule_type="builtin_default",
                target_fields_json=[],
                condition_expr=None,
                action="pass_through",
                status="active",
                rule_set_version=1,
            ),
            DatasetResolutionPolicy(
                dataset_key="stock_basic",
                mode="primary_fallback",
                primary_source_key="tushare",
                fallback_source_keys=["biying"],
                field_rules_json={},
                version=1,
                enabled=True,
            ),
        ]
    )
    db_session.commit()

    response = app_client.get("/api/v1/ops/pipeline-modes", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    item = next(candidate for candidate in payload["items"] if candidate["dataset_key"] == "stock_basic")
    assert item["dataset_key"] == "stock_basic"
    assert item["mode"] == "multi_source_pipeline"
    assert item["layer_plan"] == "raw->std->resolution->serving"
    assert item["std_mapping_configured"] is True
    assert item["std_cleansing_configured"] is True
    assert item["resolution_policy_configured"] is True
