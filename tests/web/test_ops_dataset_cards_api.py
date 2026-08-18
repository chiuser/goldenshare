from __future__ import annotations

from datetime import date, datetime, timezone

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService


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

    snapshot_date = OpsFreshnessQueryService._business_reference_date()
    now = datetime(snapshot_date.year, snapshot_date.month, snapshot_date.day, 10, 0, tzinfo=timezone.utc)
    db_session.add_all(
        [
            DatasetStatusSnapshot(
                dataset_key="limit_list_ths",
                resource_key="limit_list_ths",
                display_name="涨跌停列表（同花顺）",
                domain_key="market",
                domain_display_name="行情",
                target_table="core_serving.limit_list_ths",
                earliest_business_date=snapshot_date,
                latest_business_date=snapshot_date,
                last_sync_date=snapshot_date,
                latest_success_at=None,
                freshness_status="fresh",
                primary_action_key="limit_list_ths.maintain",
                snapshot_date=snapshot_date,
                last_calculated_at=now,
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
    assert card["group_key"] == "limit_board"
    assert card["group_label"] == "涨跌停榜"
    assert card["domain_key"] == "equity_market"
    assert card["domain_display_name"] == "股票行情"
    assert card["delivery_mode"] == "single_source_serving"
    assert card["freshness_policy"] == "continuous_open_day"
    assert card["latest_observed_date_label"] == "最新业务日期"
    assert card["raw_table_label"] == "raw_tushare.limit_list_ths"
    assert card["latest_success_at"] is None
    assert card["last_sync_date"] == snapshot_date.isoformat()
    assert card["status"] == "healthy"
    assert card["probe_total"] == 1
    assert card["probe_active"] == 1
    assert "stage_statuses" not in card
    assert "raw_sources" not in card
    assert "status_updated_at" not in card

    fund_basic = cards["fund_basic"]
    assert fund_basic["display_name"] == "基金列表"
    assert fund_basic["group_key"] == "public_fund"
    assert fund_basic["group_label"] == "公募基金"
    assert fund_basic["freshness_policy"] == "snapshot_run_trace"
    assert fund_basic["raw_table_label"] is None
    assert fund_basic["target_table"] == "core_serving.fund_basic_current"
    assert fund_basic["primary_action_key"] == "fund_basic.maintain"
    assert fund_basic["probe_total"] == 0

    fund_manager = cards["fund_manager"]
    assert fund_manager["display_name"] == "基金经理"
    assert fund_manager["group_key"] == "public_fund"
    assert fund_manager["group_label"] == "公募基金"
    assert fund_manager["freshness_policy"] == "snapshot_run_trace"
    assert fund_manager["raw_table_label"] is None
    assert fund_manager["target_table"] == "core_serving.fund_manager_current"
    assert fund_manager["primary_action_key"] == "fund_manager.maintain"
    assert fund_manager["probe_total"] == 0


def test_ops_dataset_cards_main_status_uses_freshness(
    app_client,
    user_factory,
    db_session,
    monkeypatch,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    fixed_now = datetime(2026, 8, 19, 1, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        OpsFreshnessQueryService,
        "_business_reference_now",
        staticmethod(lambda *, today=None, now=None: fixed_now),
    )
    snapshot_date = date(2026, 8, 18)
    calculated_at = fixed_now
    db_session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 8, 18),
                is_open=True,
                pretrade_date=date(2026, 8, 17),
            ),
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 8, 19),
                is_open=True,
                pretrade_date=date(2026, 8, 18),
            ),
            DatasetStatusSnapshot(
                dataset_key="kpl_list",
                resource_key="kpl_list",
                display_name="开盘啦榜单",
                domain_key="equity_market",
                domain_display_name="股票行情",
                target_table="core_serving.kpl_list",
                earliest_business_date=snapshot_date,
                latest_business_date=snapshot_date,
                last_sync_date=snapshot_date,
                latest_success_at=datetime(2026, 8, 19, 0, 40, tzinfo=timezone.utc),
                freshness_status="fresh",
                primary_action_key="kpl_list.maintain",
                snapshot_date=date(2026, 8, 19),
                last_calculated_at=calculated_at,
            ),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/dataset-cards?source_key=tushare",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    cards = {
        item["detail_dataset_key"]: item
        for group in response.json()["groups"]
        for item in group["items"]
    }
    assert cards["kpl_list"]["freshness_status"] == "fresh"
    assert cards["kpl_list"]["status"] == "healthy"


def test_ops_dataset_cards_preserve_stale_freshness_status_for_date_based_dataset(app_client, user_factory, db_session) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    now = datetime(2026, 5, 5, 14, 0, tzinfo=timezone.utc)
    snapshot_date = OpsFreshnessQueryService._business_reference_date()
    db_session.add_all(
        [
            DatasetStatusSnapshot(
                dataset_key="limit_list_ths",
                resource_key="limit_list_ths",
                display_name="涨跌停列表（同花顺）",
                domain_key="equity_market",
                domain_display_name="股票行情",
                target_table="core_serving.limit_list_ths",
                earliest_business_date=date(2026, 4, 30),
                latest_business_date=date(2026, 4, 30),
                last_sync_date=date(2026, 5, 5),
                latest_success_at=now,
                freshness_status="stale",
                primary_action_key="limit_list_ths.maintain",
                snapshot_date=snapshot_date,
                last_calculated_at=now,
            ),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/dataset-cards?source_key=tushare",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    cards = {
        item["detail_dataset_key"]: item
        for group in response.json()["groups"]
        for item in group["items"]
    }
    assert cards["limit_list_ths"]["status"] == "stale"


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
    assert cards["biying_moneyflow"]["group_key"] == "moneyflow"
    assert cards["biying_moneyflow"]["group_label"] == "资金流向"
    assert cards["biying_equity_daily"]["dataset_key"] == "biying_equity_daily"
    assert cards["biying_equity_daily"]["card_key"] == "biying_equity_daily"
    assert cards["biying_equity_daily"]["group_key"] == "equity_market"
    assert cards["biying_equity_daily"]["group_label"] == "A股行情"
