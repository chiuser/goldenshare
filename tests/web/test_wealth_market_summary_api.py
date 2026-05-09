from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core.limit_list_ths import LimitListThs
from src.foundation.models.core.market_moneyflow_dc import MarketMoneyflowDc
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing


def _ensure_summary_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [
        TradeCalendar.__table__,
        EquityDailyBar.__table__,
        MarketMoneyflowDc.__table__,
        LimitListThs.__table__,
        IndexDailyServing.__table__,
    ]:
        table.create(bind, checkfirst=True)


def test_market_summary_endpoint_returns_debug_payload(app_client, db_session) -> None:
    _ensure_summary_tables(db_session)
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
    db_session.add_all(
        [
            EquityDailyBar(
                ts_code="000001.SZ",
                trade_date=date(2026, 4, 28),
                open=Decimal("10.0000"),
                high=Decimal("10.6000"),
                low=Decimal("9.9000"),
                close=Decimal("10.5000"),
                pre_close=Decimal("10.0000"),
                change_amount=Decimal("0.5000"),
                pct_chg=Decimal("5.0000"),
                vol=Decimal("100000.0000"),
                amount=Decimal("1000000000.0000"),
                source="tushare",
            ),
            EquityDailyBar(
                ts_code="000002.SZ",
                trade_date=date(2026, 4, 28),
                open=Decimal("20.0000"),
                high=Decimal("20.3000"),
                low=Decimal("19.5000"),
                close=Decimal("19.7000"),
                pre_close=Decimal("20.0000"),
                change_amount=Decimal("-0.3000"),
                pct_chg=Decimal("-1.5000"),
                vol=Decimal("200000.0000"),
                amount=Decimal("2000000000.0000"),
                source="tushare",
            ),
            EquityDailyBar(
                ts_code="000003.SZ",
                trade_date=date(2026, 4, 28),
                open=Decimal("5.0000"),
                high=Decimal("5.2000"),
                low=Decimal("4.9000"),
                close=Decimal("5.0000"),
                pre_close=Decimal("5.0000"),
                change_amount=Decimal("0.0000"),
                pct_chg=Decimal("0.0000"),
                vol=Decimal("50000.0000"),
                amount=Decimal("500000000.0000"),
                source="tushare",
            ),
            EquityDailyBar(
                ts_code="000001.SZ",
                trade_date=date(2026, 4, 27),
                open=Decimal("9.8000"),
                high=Decimal("10.2000"),
                low=Decimal("9.7000"),
                close=Decimal("10.0000"),
                pre_close=Decimal("9.9000"),
                change_amount=Decimal("0.1000"),
                pct_chg=Decimal("1.0101"),
                vol=Decimal("110000.0000"),
                amount=Decimal("3000000000.0000"),
                source="tushare",
            ),
        ]
    )
    db_session.add(
        MarketMoneyflowDc(
            trade_date=date(2026, 4, 28),
            close_sh=Decimal("3128.4200"),
            pct_change_sh=Decimal("0.9200"),
            close_sz=Decimal("9842.1500"),
            pct_change_sz=Decimal("-0.3500"),
            net_amount=Decimal("-5280000000.0000"),
            net_amount_rate=Decimal("-0.1200"),
            buy_elg_amount=Decimal("0"),
            buy_elg_amount_rate=Decimal("0"),
            buy_lg_amount=Decimal("0"),
            buy_lg_amount_rate=Decimal("0"),
            buy_md_amount=Decimal("0"),
            buy_md_amount_rate=Decimal("0"),
            buy_sm_amount=Decimal("0"),
            buy_sm_amount_rate=Decimal("0"),
        )
    )
    db_session.add_all(
        [
            LimitListThs(
                ts_code="000001.SZ",
                trade_date=date(2026, 4, 28),
                query_limit_type="涨停",
                query_market="A股",
                limit_type="涨停池",
                name="平安银行",
                status="换手板",
            ),
            LimitListThs(
                ts_code="000002.SZ",
                trade_date=date(2026, 4, 28),
                query_limit_type="涨停",
                query_market="A股",
                limit_type="炸板池",
                name="万 科Ａ",
                status="炸板",
            ),
            LimitListThs(
                ts_code="000003.SZ",
                trade_date=date(2026, 4, 28),
                query_limit_type="跌停",
                query_market="A股",
                limit_type="跌停池",
                name="国农科技",
                status="跌停",
            ),
        ]
    )
    db_session.add_all(
        [
            IndexDailyServing(
                ts_code="000001.SH",
                trade_date=date(2026, 4, 28),
                close=Decimal("3128.4200"),
                pct_chg=Decimal("0.9200"),
            ),
            IndexDailyServing(
                ts_code="399001.SZ",
                trade_date=date(2026, 4, 28),
                close=Decimal("9842.1500"),
                pct_chg=Decimal("-0.3500"),
            ),
            IndexDailyServing(
                ts_code="399006.SZ",
                trade_date=date(2026, 4, 28),
                close=Decimal("1986.2200"),
                pct_chg=Decimal("1.1200"),
            ),
        ]
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/summary", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["tradingDay"]["tradeDate"] == "2026-04-28"
    assert payload["marketSummary"]["definition"]["cardCount"] == 5
    assert len(payload["marketSummary"]["cards"]) == 5
    cards_by_key = {card["cardKey"]: card for card in payload["marketSummary"]["cards"]}
    assert cards_by_key["majorIndexUpCount"]["label"] == "主要指数涨跌比"
    assert cards_by_key["majorIndexUpCount"]["value"] == "2:1"
    assert cards_by_key["majorIndexUpCount"]["subText"] == "上涨数量:下跌数量"
    # equity_daily_bar.amount is in thousand-yuan unit, so billion-yuan display divides by 100000.
    assert cards_by_key["turnoverTotal"]["value"] == "35000亿"
    assert cards_by_key["turnoverTotal"]["subText"] == "较昨日：+5000亿"
    assert cards_by_key["limitUpDown"]["value"] == "1 / 1"
    assert cards_by_key["limitUpDown"]["subText"] == "炸板 1"
    expected_template = "objective_close_v1" if payload["tradingDay"]["sessionStatus"] == "CLOSED" else "objective_intraday_v1"
    assert payload["marketSummary"]["textCard"]["templateKey"] == expected_template
    assert payload["debugInfo"]["modules"][0]["moduleKey"] == "marketSummary"


def test_market_summary_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/summary", params={"market": "US"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"
