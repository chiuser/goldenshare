from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing


_LARGE_INDEX_CODE = "000300.SH"
_SMALL_INDEX_CODE = "000852.SH"


def _ensure_style_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [
        TradeCalendar.__table__,
        IndexDailyServing.__table__,
        EquityDailyBar.__table__,
    ]:
        table.create(bind, checkfirst=True)


def _seed_style_facts(db_session, *, end_date: date, days: int = 62) -> None:
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

        large_pct = Decimal("0.7200") if trade_day == end_date else Decimal("0.1200")
        small_pct = Decimal("1.4800") if trade_day == end_date else Decimal("0.2400")
        db_session.add(
            IndexDailyServing(
                ts_code=_LARGE_INDEX_CODE,
                trade_date=trade_day,
                close=Decimal("3726.8400"),
                change_amount=Decimal("26.5800"),
                pct_chg=large_pct,
            )
        )
        db_session.add(
            IndexDailyServing(
                ts_code=_SMALL_INDEX_CODE,
                trade_date=trade_day,
                close=Decimal("5948.1700"),
                change_amount=Decimal("86.7000"),
                pct_chg=small_pct,
            )
        )

        if trade_day == end_date:
            pct_values = [Decimal("-1.0000"), Decimal("0.4800"), Decimal("2.0000")]
        else:
            pct_values = [Decimal("-1.0000"), Decimal("0.0000"), Decimal("1.0000")]
        for stock_index, pct in enumerate(pct_values):
            db_session.add(
                EquityDailyBar(
                    ts_code=f"000{idx:02d}{stock_index}.SZ",
                    trade_date=trade_day,
                    open=Decimal("10.0000"),
                    high=Decimal("10.2000"),
                    low=Decimal("9.8000"),
                    close=Decimal("10.1000"),
                    pre_close=Decimal("10.0000"),
                    change_amount=Decimal("0.1000"),
                    pct_chg=pct,
                    vol=Decimal("1000.0000"),
                    amount=Decimal("100000.0000"),
                    source="tushare",
                )
            )

    db_session.commit()


def test_market_style_endpoint_returns_cards_and_history(app_client, db_session) -> None:
    _ensure_style_tables(db_session)
    target_date = date(2026, 4, 28)
    _seed_style_facts(db_session, end_date=target_date)

    response = app_client.get("/api/v1/wealth/market/style", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["tradingDay"]["tradeDate"] == "2026-04-28"
    assert payload["style"]["definition"]["fixedCardCount"] == 3
    assert len(payload["style"]["cards"]) == 3
    cards_by_key = {card["cardKey"]: card for card in payload["style"]["cards"]}
    assert set(cards_by_key.keys()) == {"largeCap", "smallCap", "median"}
    assert cards_by_key["largeCap"]["valuePct"] == 0.72
    assert cards_by_key["smallCap"]["valuePct"] == 1.48
    assert cards_by_key["median"]["valuePct"] == 0.48
    assert cards_by_key["median"]["direction"] == "UP"
    assert cards_by_key["largeCap"]["sourceText"]
    assert len(payload["style"]["historyByRange"]["oneMonth"]) == 22
    assert len(payload["style"]["historyByRange"]["threeMonth"]) == 62
    first_history_point = payload["style"]["historyByRange"]["oneMonth"][0]
    assert set(first_history_point.keys()) == {"tradeDate", "largePct", "smallPct", "medianPct"}
    assert payload["pageStatus"]["status"] == "READY"
    assert payload["debugInfo"]["modules"][0]["moduleKey"] == "marketStyle"

    no_debug_response = app_client.get("/api/v1/wealth/market/style", params={"tradeDate": "2026-04-28"})
    assert no_debug_response.status_code == 200
    no_debug_payload = no_debug_response.json()
    assert "debugInfo" not in no_debug_payload or no_debug_payload["debugInfo"] is None


def test_market_style_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/style", params={"market": "US"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"
