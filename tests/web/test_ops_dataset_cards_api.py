from __future__ import annotations

from datetime import date, datetime, timezone

from src.ops.models.ops.dataset_layer_snapshot_current import DatasetLayerSnapshotCurrent
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.models.ops.probe_rule import ProbeRule


def test_ops_dataset_cards_requires_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/dataset-cards", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_dataset_cards_returns_authoritative_card_fields(app_client, user_factory, db_session) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    now = datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc)
    db_session.add_all(
        [
            DatasetStatusSnapshot(
                dataset_key="limit_list_ths",
                resource_key="limit_list_ths",
                display_name="涨跌停列表（同花顺）",
                domain_key="market",
                domain_display_name="行情",
                target_table="core_serving.limit_list_ths",
                cadence="daily",
                latest_business_date=date(2026, 4, 24),
                last_sync_date=date(2026, 4, 24),
                latest_success_at=None,
                freshness_status="fresh",
                primary_action_key="limit_list_ths.maintain",
                snapshot_date=date(2026, 4, 24),
                last_calculated_at=now,
            ),
            DatasetLayerSnapshotCurrent(
                dataset_key="limit_list_ths",
                source_key="tushare",
                stage="raw",
                status="success",
                rows_in=120,
                rows_out=120,
                error_count=0,
                last_success_at=None,
                calculated_at=now,
            ),
            ProbeRule(
                name="涨跌停列表探测",
                dataset_key="limit_list_ths",
                source_key="tushare",
                status="active",
                probe_interval_seconds=600,
                probe_condition_json={},
                on_success_action_json={},
            ),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/dataset-cards?source_key=tushare",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    cards = {
        item["detail_dataset_key"]: item
        for group in payload["groups"]
        for item in group["items"]
    }
    card = cards["limit_list_ths"]
    assert card["display_name"] == "同花顺涨停名单"
    assert card["delivery_mode"] == "single_source_serving"
    assert card["cadence_display_name"] == "每日"
    assert card["raw_table_label"] == "raw_tushare.limit_list_ths"
    assert card["latest_success_at"] is None
    assert card["last_sync_date"] == "2026-04-24"
    assert card["status"] == "healthy"
    assert card["probe_total"] == 1
    assert card["probe_active"] == 1

    raw_stage = next(item for item in card["stage_statuses"] if item["stage"] == "raw")
    assert raw_stage["status"] == "healthy"
    assert raw_stage["source_display_name"] == "Tushare"
    assert raw_stage["last_success_at"] is None
    raw_source = next(item for item in card["raw_sources"] if item["source_key"] == "tushare")
    assert raw_source["source_display_name"] == "Tushare"


def test_ops_dataset_cards_uses_definition_card_grouping_for_biying_source(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get(
        "/api/v1/ops/dataset-cards?source_key=biying",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    cards = {
        item["detail_dataset_key"]: item
        for group in payload["groups"]
        for item in group["items"]
    }
    assert cards["biying_moneyflow"]["dataset_key"] == "moneyflow"
    assert cards["biying_moneyflow"]["card_key"] == "moneyflow"
    assert cards["biying_equity_daily"]["dataset_key"] == "biying_equity_daily"
    assert cards["biying_equity_daily"]["card_key"] == "biying_equity_daily"
