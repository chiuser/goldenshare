from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from src.foundation.models.core.market_moneyflow_dc import MarketMoneyflowDc
from src.foundation.models.core.trade_calendar import TradeCalendar


def _ensure_money_flow_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [TradeCalendar.__table__, MarketMoneyflowDc.__table__]:
        table.create(bind, checkfirst=True)


def _seed_money_flow_facts(db_session, *, end_date: date, days: int = 62) -> None:
    trade_dates = [end_date - timedelta(days=days - 1 - idx) for idx in range(days)]
    for idx, trade_day in enumerate(trade_dates):
        prev_trade_day = trade_dates[idx - 1] if idx > 0 else None
        db_session.add(
            TradeCalendar(
                exchange="SSE",
                trade_date=trade_day,
                is_open=True,
                pretrade_date=prev_trade_day,
            )
        )
        net_amount = Decimal("-5200000000.0000") + Decimal(idx) * Decimal("100000000.0000")
        db_session.add(
            MarketMoneyflowDc(
                trade_date=trade_day,
                close_sh=Decimal("3128.4200"),
                pct_change_sh=Decimal("0.9200"),
                close_sz=Decimal("9842.1500"),
                pct_change_sz=Decimal("-0.3500"),
                net_amount=net_amount,
                net_amount_rate=Decimal("-0.5200"),
                buy_elg_amount=Decimal("-1200000000.0000"),
                buy_elg_amount_rate=Decimal("-0.2300"),
                buy_lg_amount=Decimal("-950000000.0000"),
                buy_lg_amount_rate=Decimal("-0.1800"),
                buy_md_amount=Decimal("420000000.0000"),
                buy_md_amount_rate=Decimal("0.0800"),
                buy_sm_amount=Decimal("610000000.0000"),
                buy_sm_amount_rate=Decimal("0.1200"),
            )
        )
    db_session.commit()


def test_market_money_flow_endpoint_returns_metrics_order_size_and_history(app_client, db_session) -> None:
    _ensure_money_flow_tables(db_session)
    target_date = date(2026, 4, 28)
    _seed_money_flow_facts(db_session, end_date=target_date)

    response = app_client.get("/api/v1/wealth/market/money-flow", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["tradingDay"]["tradeDate"] == "2026-04-28"
    assert payload["tradingDay"]["prevTradeDate"] == "2026-04-27"
    assert payload["moneyFlow"]["tradeDate"] == "2026-04-28"
    assert payload["moneyFlow"]["metrics"]["todayNetAmount"] == 900000000.0
    assert payload["moneyFlow"]["metrics"]["prevNetAmount"] == 800000000.0
    assert payload["moneyFlow"]["metrics"]["unit"] == "yuan"
    assert payload["moneyFlow"]["byOrderSize"]["elg"] == {"amount": -1200000000.0, "rate": -0.23}
    assert payload["moneyFlow"]["byOrderSize"]["lg"] == {"amount": -950000000.0, "rate": -0.18}
    assert payload["moneyFlow"]["byOrderSize"]["md"] == {"amount": 420000000.0, "rate": 0.08}
    assert payload["moneyFlow"]["byOrderSize"]["sm"] == {"amount": 610000000.0, "rate": 0.12}
    assert len(payload["moneyFlow"]["historyByRange"]["oneMonth"]) == 22
    assert len(payload["moneyFlow"]["historyByRange"]["threeMonth"]) == 62
    assert payload["moneyFlow"]["historyByRange"]["oneMonth"][0]["tradeDate"] < payload["moneyFlow"]["historyByRange"]["oneMonth"][-1]["tradeDate"]
    assert set(payload["moneyFlow"]["historyByRange"]["oneMonth"][0].keys()) == {"tradeDate", "netAmount"}
    assert payload["pageStatus"]["status"] == "READY"
    assert payload["debugInfo"]["modules"][0]["moduleKey"] == "moneyFlow"
    assert payload["debugInfo"]["exceptions"] == []

    no_debug_response = app_client.get("/api/v1/wealth/market/money-flow", params={"tradeDate": "2026-04-28"})
    assert no_debug_response.status_code == 200
    no_debug_payload = no_debug_response.json()
    assert "debugInfo" not in no_debug_payload or no_debug_payload["debugInfo"] is None


def test_market_money_flow_reports_delayed_source(app_client, db_session) -> None:
    _ensure_money_flow_tables(db_session)
    observed_date = date(2026, 4, 28)
    expected_date = date(2026, 4, 29)
    _seed_money_flow_facts(db_session, end_date=observed_date)
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=expected_date,
            is_open=True,
            pretrade_date=observed_date,
        )
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/money-flow", params={"tradeDate": "2026-04-29", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["pageStatus"]["status"] == "PARTIAL"
    assert payload["debugInfo"]["modules"][0]["status"] == "DELAYED"
    assert payload["debugInfo"]["modules"][0]["observedTradeDate"] == "2026-04-28"
    assert payload["debugInfo"]["exceptions"][0]["code"] == "MF_SOURCE_DELAYED"


def test_market_money_flow_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/money-flow", params={"market": "US"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"
