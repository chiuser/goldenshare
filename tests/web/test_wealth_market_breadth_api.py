from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


def _ensure_breadth_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [
        TradeCalendar.__table__,
        EquityDailyBar.__table__,
    ]:
        table.create(bind, checkfirst=True)


def _seed_breadth_facts(db_session, *, end_date: date, days: int = 62) -> None:
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

        db_session.add(
            EquityDailyBar(
                ts_code=f"000{idx:03d}.SZ",
                trade_date=trade_day,
                open=Decimal("10.0000"),
                high=Decimal("10.2000"),
                low=Decimal("9.8000"),
                close=Decimal("10.1000"),
                pre_close=Decimal("10.0000"),
                change_amount=Decimal("0.1000"),
                pct_chg=Decimal("1.0000"),
                vol=Decimal("1000.0000"),
                amount=Decimal("100000.0000"),
                source="tushare",
            )
        )
        db_session.add(
            EquityDailyBar(
                ts_code=f"300{idx:03d}.SZ",
                trade_date=trade_day,
                open=Decimal("20.0000"),
                high=Decimal("20.1000"),
                low=Decimal("19.6000"),
                close=Decimal("19.8000"),
                pre_close=Decimal("20.0000"),
                change_amount=Decimal("-0.2000"),
                pct_chg=Decimal("-1.0000"),
                vol=Decimal("1000.0000"),
                amount=Decimal("100000.0000"),
                source="tushare",
            )
        )

    db_session.add(
        EquityDailyBar(
            ts_code="688999.SH",
            trade_date=end_date,
            open=Decimal("8.0000"),
            high=Decimal("8.1000"),
            low=Decimal("7.9000"),
            close=Decimal("8.0000"),
            pre_close=Decimal("8.0000"),
            change_amount=Decimal("0.0000"),
            pct_chg=Decimal("0.0000"),
            vol=Decimal("1000.0000"),
            amount=Decimal("100000.0000"),
            source="tushare",
        )
    )
    db_session.commit()


def test_market_breadth_endpoint_returns_metrics_and_history(app_client, db_session) -> None:
    _ensure_breadth_tables(db_session)
    target_date = date(2026, 4, 28)
    _seed_breadth_facts(db_session, end_date=target_date)

    response = app_client.get("/api/v1/wealth/market/breadth", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["tradingDay"]["tradeDate"] == "2026-04-28"
    assert payload["breadth"]["tradeDate"] == "2026-04-28"
    assert payload["breadth"]["metrics"]["upCount"] == 1
    assert payload["breadth"]["metrics"]["downCount"] == 1
    assert payload["breadth"]["metrics"]["flatCount"] == 1
    assert payload["breadth"]["metrics"]["redRate"] == 33.33
    assert len(payload["breadth"]["historyByRange"]["1m"]) == 22
    assert len(payload["breadth"]["historyByRange"]["3m"]) == 62
    assert payload["pageStatus"]["status"] == "READY"
    assert payload["debugInfo"]["modules"][0]["moduleKey"] == "breadth"


def test_market_breadth_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/breadth", params={"market": "US"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"
