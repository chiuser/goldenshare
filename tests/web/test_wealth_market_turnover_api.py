from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.wealth_market_turnover_snapshot import WealthMarketTurnoverSnapshot


def _ensure_turnover_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [
        TradeCalendar.__table__,
        EquityDailyBar.__table__,
        WealthMarketTurnoverSnapshot.__table__,
    ]:
        table.create(bind, checkfirst=True)


def _seed_turnover_facts(db_session, *, end_date: date, days: int = 62) -> None:
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
        amount = Decimal("1000000000.0000") + Decimal(idx) * Decimal("10000000.0000")
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
                amount=amount,
                source="tushare",
            )
        )

    intraday_points = [
        (time(hour=9, minute=30), Decimal("10000000")),
        (time(hour=10, minute=0), Decimal("12000000")),
        (time(hour=10, minute=30), Decimal("14000000")),
        (time(hour=11, minute=0), Decimal("16000000")),
        (time(hour=11, minute=30), Decimal("18000000")),
        (time(hour=13, minute=30), Decimal("20000000")),
        (time(hour=14, minute=0), Decimal("22000000")),
        (time(hour=14, minute=30), Decimal("24000000")),
        (time(hour=15, minute=0), Decimal("26000000")),
    ]
    points_json = []
    total_amount = Decimal("0")
    total_vol = Decimal("0")
    security_count = 2
    source_row_count = 0
    for tick_time, amount in intraday_points:
        point_amount = amount * Decimal("2.3")
        point_vol = Decimal("1200000") * Decimal("2")
        total_amount += point_amount
        total_vol += point_vol
        source_row_count += security_count
        points_json.append(
            {
                "tradeTime": tick_time.strftime("%H:%M"),
                "tradeTimeTs": datetime.combine(end_date, tick_time).strftime("%Y-%m-%d %H:%M:%S"),
                "amount": float(point_amount),
                "vol": float(point_vol),
                "securityCount": security_count,
            }
        )
    db_session.add(
        WealthMarketTurnoverSnapshot(
            type="stock",
            market="CN_A",
            trade_date=end_date,
            freq=30,
            latest_trade_time=datetime.combine(end_date, time(hour=15, minute=0)),
            security_count=security_count,
            source_row_count=source_row_count,
            total_amount=total_amount,
            total_vol=total_vol,
            points_json=points_json,
            build_status="READY",
            build_version="v1",
            built_at=datetime.now(),
            build_note=None,
        )
    )
    db_session.commit()


def test_market_turnover_endpoint_returns_metrics_intraday_and_history(app_client, db_session) -> None:
    _ensure_turnover_tables(db_session)
    target_date = date(2026, 4, 28)
    _seed_turnover_facts(db_session, end_date=target_date)

    response = app_client.get("/api/v1/wealth/market/turnover", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["tradingDay"]["tradeDate"] == "2026-04-28"
    assert payload["turnover"]["tradeDate"] == "2026-04-28"
    assert payload["turnover"]["metrics"]["todayAmount"] == 1610000000.0
    assert payload["turnover"]["metrics"]["prevAmount"] == 1600000000.0
    assert payload["turnover"]["metrics"]["amountDelta"] == 10000000.0
    assert payload["turnover"]["metrics"]["amountDeltaPct"] == 0.63
    assert len(payload["turnover"]["historyByRange"]["oneMonth"]) == 22
    assert len(payload["turnover"]["historyByRange"]["threeMonth"]) == 62
    assert len(payload["turnover"]["intradayCumulative"]) == 5
    assert payload["turnover"]["intradayCumulative"][-1]["cumAmount"] > payload["turnover"]["intradayCumulative"][0]["cumAmount"]
    assert payload["pageStatus"]["status"] == "READY"
    assert payload["debugInfo"]["modules"][0]["moduleKey"] == "turnover"


def test_market_turnover_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/turnover", params={"market": "US"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"


def test_market_turnover_ignores_failed_snapshot_rows(app_client, db_session) -> None:
    _ensure_turnover_tables(db_session)
    target_date = date(2026, 4, 28)
    _seed_turnover_facts(db_session, end_date=target_date)
    ready_row = db_session.scalar(
        select(WealthMarketTurnoverSnapshot).where(
            WealthMarketTurnoverSnapshot.type == "stock",
            WealthMarketTurnoverSnapshot.market == "CN_A",
            WealthMarketTurnoverSnapshot.trade_date == target_date,
            WealthMarketTurnoverSnapshot.freq == 30,
        )
    )
    assert ready_row is not None
    ready_row.build_status = "FAILED"
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/turnover", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["pageStatus"]["status"] == "PARTIAL"
    assert all(point["cumAmount"] is None for point in payload["turnover"]["intradayCumulative"])
