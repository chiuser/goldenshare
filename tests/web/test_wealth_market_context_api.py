from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.foundation.models.core.trade_calendar import TradeCalendar


def _ensure_context_tables(db_session) -> None:
    bind = db_session.get_bind()
    TradeCalendar.__table__.create(bind, checkfirst=True)


def test_market_context_returns_explicit_trade_date(app_client, db_session) -> None:
    _ensure_context_tables(db_session)
    db_session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 4, 27),
                is_open=True,
                pretrade_date=date(2026, 4, 24),
            ),
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 4, 28),
                is_open=True,
                pretrade_date=date(2026, 4, 27),
            ),
        ]
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/context", params={"tradeDate": "2026-04-28"})

    assert response.status_code == 200
    payload = response.json()
    context = payload["pageContext"]
    assert context["market"] == "CN_A"
    assert context["tradeDate"] == "2026-04-28"
    assert context["prevTradeDate"] == "2026-04-27"
    assert context["isTradingDay"] is True
    assert context["sessionStatus"] in {"PRE_OPEN", "TRADING", "BREAK", "CLOSED"}
    assert context["timezone"] == "Asia/Shanghai"
    assert context["source"] == "explicit"
    assert datetime.fromisoformat(context["generatedAt"])


def test_market_context_marks_non_trading_explicit_date(app_client, db_session) -> None:
    _ensure_context_tables(db_session)
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=date(2026, 4, 27),
            is_open=True,
            pretrade_date=date(2026, 4, 24),
        )
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/context", params={"tradeDate": "2026-04-26"})

    assert response.status_code == 200
    context = response.json()["pageContext"]
    assert context["tradeDate"] == "2026-04-26"
    assert context["prevTradeDate"] is None
    assert context["isTradingDay"] is False
    assert context["sessionStatus"] == "CLOSED"
    assert context["source"] == "explicit"


def test_market_context_resolves_default_trade_date(app_client, db_session) -> None:
    _ensure_context_tables(db_session)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=today,
            is_open=True,
            pretrade_date=date(2026, 4, 27),
        )
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/context")

    assert response.status_code == 200
    context = response.json()["pageContext"]
    assert context["market"] == "CN_A"
    assert context["source"] == "default"
    assert "tradeDate" in context
    assert "generatedAt" in context


def test_market_context_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/context", params={"market": "US"})

    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"
