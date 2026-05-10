from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.wealth_market_turnover_snapshot import WealthMarketTurnoverSnapshot


def _admin_token(app_client, user_factory) -> str:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    return str(login.json()["token"])


def test_ops_biz_table_cards_returns_turnover_snapshot(app_client, user_factory, db_session) -> None:
    token = _admin_token(app_client, user_factory)
    WealthMarketTurnoverSnapshot.__table__.create(db_session.connection(), checkfirst=True)
    today = date.today()
    prev_trade_date = today - timedelta(days=1)
    db_session.merge(TradeCalendar(exchange="SSE", trade_date=prev_trade_date, is_open=True, pretrade_date=None))
    db_session.merge(TradeCalendar(exchange="SSE", trade_date=today, is_open=True, pretrade_date=prev_trade_date))
    db_session.add(
        WealthMarketTurnoverSnapshot(
            type="stock",
            market="CN_A",
            trade_date=today,
            freq=30,
            latest_trade_time=datetime.combine(today, datetime.min.time().replace(hour=15)),
            security_count=5000,
            source_row_count=10000,
            total_amount=Decimal("123456.78"),
            total_vol=9876543210,
            points_json=[],
            build_status="READY",
            build_version="v1",
            built_at=datetime(2026, 5, 8, 20, 10, tzinfo=timezone.utc),
            build_note=None,
        )
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/dataset-cards?source_key=biz_tableset",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["groups"]) == 1
    group = payload["groups"][0]
    assert group["group_key"] == "wealth_market"
    assert group["group_label"] == "财势乾坤"
    card = group["items"][0]
    assert card["card_key"] == "wealth_market_turnover_snapshot"
    assert card["display_name"] == "成交额分钟快照"
    assert card["domain_key"] == "biz_tableset"
    assert card["domain_display_name"] == "Biz数据集"
    assert card["delivery_mode"] == "biz_table_snapshot"
    assert card["delivery_mode_label"] == "业务派生表"
    assert card["raw_table"] is None
    assert card["raw_table_label"] is None
    assert card["target_table"] == "core_serving.wealth_market_turnover_snapshot"
    assert card["latest_business_date"] == today.isoformat()
    assert card["earliest_business_date"] == today.isoformat()
    assert card["status"] == "healthy"
    assert card["freshness_status"] == "fresh"
    assert card["primary_action_key"] is None
    assert card["auto_schedule_total"] == 0
    assert card["auto_schedule_active"] == 0
    assert card["probe_total"] == 0
    assert card["raw_sources"] == []
    stage = card["stage_statuses"][0]
    assert stage["stage"] == "biz_table"
    assert stage["stage_label"] == "Biz表"
    assert stage["table_name"] == "core_serving.wealth_market_turnover_snapshot"
    assert stage["source_key"] == "biz_tableset"
    assert stage["source_display_name"] == "Biz数据集"
    assert stage["status"] == "healthy"
    assert stage["rows_out"] == 1
    assert stage["message"] == f"最新快照 {today.isoformat()}，期望 {card['expected_business_date']}，已就绪。"
    assert stage["calculated_at"].startswith("2026-05-08T20:10:00")
    assert stage["last_success_at"].startswith("2026-05-08T20:10:00")


def test_ops_biz_table_cards_returns_read_only_unknown_card_without_ready_rows(app_client, user_factory, db_session) -> None:
    token = _admin_token(app_client, user_factory)
    WealthMarketTurnoverSnapshot.__table__.create(db_session.connection(), checkfirst=True)

    response = app_client.get(
        "/api/v1/ops/dataset-cards?source_key=biz_tableset",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    card = response.json()["groups"][0]["items"][0]
    assert card["display_name"] == "成交额分钟快照"
    assert card["status"] == "unknown"
    assert card["freshness_status"] == "unknown"
    assert card["primary_action_key"] is None
    assert card["freshness_note"] == "暂无 READY 快照。"
    assert card["stage_statuses"][0]["rows_out"] == 0
