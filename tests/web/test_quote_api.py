from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.foundation.config.settings import get_settings
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core.equity_daily_bar import EquityDailyBar
from src.foundation.models.core.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core.equity_price_restore_factor import EquityPriceRestoreFactor
from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.models.core.fund_daily_bar import FundDailyBar
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.index_daily_basic import IndexDailyBasic
from src.foundation.models.core.index_daily_serving import IndexDailyServing
from src.foundation.models.core.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.core.kpl_concept_cons import KplConceptCons
from src.foundation.models.core.security import Security
from src.foundation.models.core.stk_period_bar import StkPeriodBar
from src.foundation.models.core.stk_period_bar_adj import StkPeriodBarAdj
from src.foundation.models.core.ths_member import ThsMember
from src.foundation.models.core.trade_calendar import TradeCalendar


def _ensure_quote_tables(db_session) -> None:
    bind = db_session.get_bind()
    tables = [
        Security.__table__,
        EquityDailyBar.__table__,
        EquityDailyBasic.__table__,
        EquityAdjFactor.__table__,
        EquityPriceRestoreFactor.__table__,
        IndexBasic.__table__,
        IndexDailyServing.__table__,
        IndexDailyBasic.__table__,
        IndexWeeklyServing.__table__,
        IndexMonthlyServing.__table__,
        EtfBasic.__table__,
        FundDailyBar.__table__,
        StkPeriodBar.__table__,
        StkPeriodBarAdj.__table__,
        ThsMember.__table__,
        DcMember.__table__,
        DcIndex.__table__,
        KplConceptCons.__table__,
        TradeCalendar.__table__,
    ]
    for table in tables:
        table.create(bind, checkfirst=True)


def test_quote_kline_returns_unsupported_for_minute_period(app_client) -> None:
    response = app_client.get(
        "/api/v1/quote/detail/kline",
        params={"ts_code": "002245.SZ", "period": "minute5", "adjustment": "forward"},
    )
    assert response.status_code == 501
    payload = response.json()
    assert payload["code"] == "UNSUPPORTED_PERIOD"


def test_quote_page_init_and_kline_for_stock(app_client, db_session) -> None:
    _ensure_quote_tables(db_session)
    db_session.add(
        Security(
            ts_code="002245.SZ",
            symbol="002245",
            name="蔚蓝锂芯",
            exchange="SZSE",
            industry="锂电池",
            list_status="L",
            security_type="EQUITY",
            source="tushare",
        )
    )
    db_session.add_all(
        [
            EquityDailyBar(
                ts_code="002245.SZ",
                trade_date=date(2026, 4, 1),
                open=Decimal("10.0000"),
                high=Decimal("11.0000"),
                low=Decimal("9.8000"),
                close=Decimal("10.5000"),
                pre_close=Decimal("9.9000"),
                change_amount=Decimal("0.6000"),
                pct_chg=Decimal("6.0600"),
                vol=Decimal("100000.0000"),
                amount=Decimal("1000000.0000"),
                source="api",
            ),
            EquityDailyBar(
                ts_code="002245.SZ",
                trade_date=date(2026, 4, 2),
                open=Decimal("10.6000"),
                high=Decimal("11.2000"),
                low=Decimal("10.4000"),
                close=Decimal("11.0000"),
                pre_close=Decimal("10.5000"),
                change_amount=Decimal("0.5000"),
                pct_chg=Decimal("4.7619"),
                vol=Decimal("120000.0000"),
                amount=Decimal("1200000.0000"),
                source="api",
            ),
        ]
    )
    db_session.add_all(
        [
            EquityDailyBasic(
                ts_code="002245.SZ",
                trade_date=date(2026, 4, 1),
                close=Decimal("10.5000"),
                turnover_rate=Decimal("2.1000"),
                turnover_rate_f=Decimal("2.5000"),
                volume_ratio=Decimal("1.2000"),
                pe=Decimal("20.1000"),
                pe_ttm=Decimal("21.1000"),
                pb=Decimal("3.2000"),
                ps=Decimal("1.1000"),
                ps_ttm=Decimal("1.1000"),
                dv_ratio=Decimal("0.5000"),
                dv_ttm=Decimal("0.6000"),
                total_share=Decimal("1000000.0000"),
                float_share=Decimal("800000.0000"),
                free_share=Decimal("600000.0000"),
                total_mv=Decimal("10000000.0000"),
                circ_mv=Decimal("8000000.0000"),
            ),
            EquityDailyBasic(
                ts_code="002245.SZ",
                trade_date=date(2026, 4, 2),
                close=Decimal("11.0000"),
                turnover_rate=Decimal("2.3000"),
                turnover_rate_f=Decimal("2.7000"),
                volume_ratio=Decimal("1.3000"),
                pe=Decimal("20.3000"),
                pe_ttm=Decimal("21.3000"),
                pb=Decimal("3.4000"),
                ps=Decimal("1.2000"),
                ps_ttm=Decimal("1.2000"),
                dv_ratio=Decimal("0.5000"),
                dv_ttm=Decimal("0.6000"),
                total_share=Decimal("1000000.0000"),
                float_share=Decimal("800000.0000"),
                free_share=Decimal("600000.0000"),
                total_mv=Decimal("11000000.0000"),
                circ_mv=Decimal("8500000.0000"),
            ),
        ]
    )
    db_session.add_all(
        [
            EquityAdjFactor(ts_code="002245.SZ", trade_date=date(2026, 4, 1), adj_factor=Decimal("1.00000000")),
            EquityAdjFactor(ts_code="002245.SZ", trade_date=date(2026, 4, 2), adj_factor=Decimal("2.00000000")),
        ]
    )
    db_session.add(
        ThsMember(
            ts_code="002245.SZ",
            con_code="885001.TI",
            con_name="储能",
            weight=Decimal("1.000000"),
            is_new="Y",
        )
    )
    db_session.commit()

    init_response = app_client.get("/api/v1/quote/detail/page-init", params={"ts_code": "002245.SZ"})
    assert init_response.status_code == 200
    init_payload = init_response.json()
    assert init_payload["instrument"]["ts_code"] == "002245.SZ"
    assert init_payload["price_summary"]["latest_price"] == "11.0000"
    assert init_payload["default_chart"]["default_period"] == "day"

    kline_response = app_client.get(
        "/api/v1/quote/detail/kline",
        params={"ts_code": "002245.SZ", "period": "day", "adjustment": "forward", "limit": 10},
    )
    assert kline_response.status_code == 200
    kline_payload = kline_response.json()
    assert kline_payload["meta"]["bar_count"] == 2
    first_bar = kline_payload["bars"][0]
    second_bar = kline_payload["bars"][1]
    assert first_bar["trade_date"] == "2026-04-01"
    assert first_bar["close"] == "5.2500"
    assert first_bar["turnover_rate"] == "2.1000"
    assert second_bar["close"] == "11.0000"
    single_day_response = app_client.get(
        "/api/v1/quote/detail/kline",
        params={
            "ts_code": "002245.SZ",
            "period": "day",
            "adjustment": "forward",
            "start_date": "2026-04-01",
            "end_date": "2026-04-01",
            "limit": 10,
        },
    )
    assert single_day_response.status_code == 200
    single_day_payload = single_day_response.json()
    assert single_day_payload["meta"]["bar_count"] == 1
    assert single_day_payload["bars"][0]["trade_date"] == "2026-04-01"
    assert single_day_payload["bars"][0]["open"] == "5.0000"
    assert single_day_payload["bars"][0]["close"] == "5.2500"

    related_response = app_client.get("/api/v1/quote/detail/related-info", params={"ts_code": "002245.SZ"})
    assert related_response.status_code == 200
    related_payload = related_response.json()
    assert any(item["type"] == "industry" for item in related_payload["items"])
    assert any(item["type"] == "concept" and item["value"] == "储能" for item in related_payload["items"])
    assert related_payload["capability"]["related_etf"] == "not_available_in_v1"


def test_quote_kline_rejects_adjustment_for_index(app_client, db_session) -> None:
    _ensure_quote_tables(db_session)
    db_session.add(
        IndexBasic(
            ts_code="000001.SH",
            name="上证指数",
            market="SSE",
            category="综合",
        )
    )
    db_session.add(
        IndexDailyServing(
            ts_code="000001.SH",
            trade_date=date(2026, 4, 2),
            open=Decimal("3000.0000"),
            high=Decimal("3010.0000"),
            low=Decimal("2990.0000"),
            close=Decimal("3005.0000"),
            pre_close=Decimal("2998.0000"),
            change_amount=Decimal("7.0000"),
            pct_chg=Decimal("0.2334"),
            vol=Decimal("100.0000"),
            amount=Decimal("200.0000"),
            source="api",
        )
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/quote/detail/kline",
        params={"ts_code": "000001.SH", "security_type": "index", "period": "day", "adjustment": "forward"},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "UNSUPPORTED_ADJUSTMENT"


def test_trade_calendar_endpoint_returns_rows(app_client, db_session) -> None:
    _ensure_quote_tables(db_session)
    db_session.add_all(
        [
            TradeCalendar(exchange="SSE", trade_date=date(2026, 4, 1), is_open=True, pretrade_date=date(2026, 3, 31)),
            TradeCalendar(exchange="SSE", trade_date=date(2026, 4, 2), is_open=False, pretrade_date=date(2026, 4, 1)),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/market/trade-calendar",
        params={"exchange": "SSE", "start_date": "2026-04-01", "end_date": "2026-04-02"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["exchange"] == "SSE"
    assert len(payload["items"]) == 2
    assert payload["items"][0]["trade_date"] == "2026-04-01"


def test_quote_api_auth_required_can_be_enforced(app_client, monkeypatch) -> None:
    monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        response = app_client.get("/api/v1/quote/detail/announcements")
        assert response.status_code == 401
        payload = response.json()
        assert payload["code"] == "auth_required"
    finally:
        monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "false")
        get_settings.cache_clear()


def test_quote_kline_can_switch_factor_source_to_price_restore(app_client, db_session, monkeypatch) -> None:
    _ensure_quote_tables(db_session)
    db_session.add(
        Security(
            ts_code="002245.SZ",
            symbol="002245",
            name="蔚蓝锂芯",
            exchange="SZSE",
            industry="锂电池",
            list_status="L",
            security_type="EQUITY",
            source="tushare",
        )
    )
    db_session.add_all(
        [
            EquityDailyBar(
                ts_code="002245.SZ",
                trade_date=date(2026, 4, 1),
                open=Decimal("10.0000"),
                high=Decimal("11.0000"),
                low=Decimal("9.8000"),
                close=Decimal("10.5000"),
                pre_close=Decimal("9.9000"),
                change_amount=Decimal("0.6000"),
                pct_chg=Decimal("6.0600"),
                vol=Decimal("100000.0000"),
                amount=Decimal("1000000.0000"),
                source="api",
            ),
            EquityDailyBar(
                ts_code="002245.SZ",
                trade_date=date(2026, 4, 2),
                open=Decimal("10.6000"),
                high=Decimal("11.2000"),
                low=Decimal("10.4000"),
                close=Decimal("11.0000"),
                pre_close=Decimal("10.5000"),
                change_amount=Decimal("0.5000"),
                pct_chg=Decimal("4.7619"),
                vol=Decimal("120000.0000"),
                amount=Decimal("1200000.0000"),
                source="api",
            ),
        ]
    )
    db_session.add_all(
        [
            EquityAdjFactor(ts_code="002245.SZ", trade_date=date(2026, 4, 1), adj_factor=Decimal("1.00000000")),
            EquityAdjFactor(ts_code="002245.SZ", trade_date=date(2026, 4, 2), adj_factor=Decimal("2.00000000")),
            EquityPriceRestoreFactor(ts_code="002245.SZ", trade_date=date(2026, 4, 1), cum_factor=Decimal("1.00000000")),
            EquityPriceRestoreFactor(ts_code="002245.SZ", trade_date=date(2026, 4, 2), cum_factor=Decimal("4.00000000")),
        ]
    )
    db_session.commit()

    monkeypatch.setenv("EQUITY_ADJUSTMENT_FACTOR_SOURCE", "price_restore_factor")
    get_settings.cache_clear()
    try:
        response = app_client.get(
            "/api/v1/quote/detail/kline",
            params={"ts_code": "002245.SZ", "period": "day", "adjustment": "forward", "limit": 10},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["meta"]["bar_count"] == 2
        # With restore factor anchor=4, first-day qfq close should be 10.5 * 1/4 = 2.6250
        assert payload["bars"][0]["close"] == "2.6250"
        assert payload["bars"][1]["close"] == "11.0000"
    finally:
        monkeypatch.setenv("EQUITY_ADJUSTMENT_FACTOR_SOURCE", "adj_factor")
        get_settings.cache_clear()


def test_quote_kline_uses_preheat_window_for_ma_on_single_day_request(app_client, db_session) -> None:
    _ensure_quote_tables(db_session)
    db_session.add(
        Security(
            ts_code="300001.SZ",
            symbol="300001",
            name="测试预热",
            exchange="SZSE",
            industry="测试",
            list_status="L",
            security_type="EQUITY",
            source="tushare",
        )
    )
    db_session.add_all(
        [
            EquityDailyBar(
                ts_code="300001.SZ",
                trade_date=date(2026, 4, 1),
                open=Decimal("10.0000"),
                high=Decimal("10.2000"),
                low=Decimal("9.9000"),
                close=Decimal("10.0000"),
                pre_close=Decimal("9.9000"),
                change_amount=Decimal("0.1000"),
                pct_chg=Decimal("1.0101"),
                vol=Decimal("100.0000"),
                amount=Decimal("1000.0000"),
                source="api",
            ),
            EquityDailyBar(
                ts_code="300001.SZ",
                trade_date=date(2026, 4, 2),
                open=Decimal("10.1000"),
                high=Decimal("10.3000"),
                low=Decimal("10.0000"),
                close=Decimal("10.1000"),
                pre_close=Decimal("10.0000"),
                change_amount=Decimal("0.1000"),
                pct_chg=Decimal("1.0000"),
                vol=Decimal("110.0000"),
                amount=Decimal("1100.0000"),
                source="api",
            ),
            EquityDailyBar(
                ts_code="300001.SZ",
                trade_date=date(2026, 4, 3),
                open=Decimal("10.2000"),
                high=Decimal("10.4000"),
                low=Decimal("10.1000"),
                close=Decimal("10.2000"),
                pre_close=Decimal("10.1000"),
                change_amount=Decimal("0.1000"),
                pct_chg=Decimal("0.9901"),
                vol=Decimal("120.0000"),
                amount=Decimal("1200.0000"),
                source="api",
            ),
            EquityDailyBar(
                ts_code="300001.SZ",
                trade_date=date(2026, 4, 6),
                open=Decimal("10.3000"),
                high=Decimal("10.5000"),
                low=Decimal("10.2000"),
                close=Decimal("10.3000"),
                pre_close=Decimal("10.2000"),
                change_amount=Decimal("0.1000"),
                pct_chg=Decimal("0.9804"),
                vol=Decimal("130.0000"),
                amount=Decimal("1300.0000"),
                source="api",
            ),
            EquityDailyBar(
                ts_code="300001.SZ",
                trade_date=date(2026, 4, 7),
                open=Decimal("10.4000"),
                high=Decimal("10.6000"),
                low=Decimal("10.3000"),
                close=Decimal("10.4000"),
                pre_close=Decimal("10.3000"),
                change_amount=Decimal("0.1000"),
                pct_chg=Decimal("0.9709"),
                vol=Decimal("140.0000"),
                amount=Decimal("1400.0000"),
                source="api",
            ),
        ]
    )
    db_session.add_all(
        [
            EquityAdjFactor(ts_code="300001.SZ", trade_date=date(2026, 4, 1), adj_factor=Decimal("1.00000000")),
            EquityAdjFactor(ts_code="300001.SZ", trade_date=date(2026, 4, 2), adj_factor=Decimal("1.00000000")),
            EquityAdjFactor(ts_code="300001.SZ", trade_date=date(2026, 4, 3), adj_factor=Decimal("1.00000000")),
            EquityAdjFactor(ts_code="300001.SZ", trade_date=date(2026, 4, 6), adj_factor=Decimal("1.00000000")),
            EquityAdjFactor(ts_code="300001.SZ", trade_date=date(2026, 4, 7), adj_factor=Decimal("1.00000000")),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/quote/detail/kline",
        params={
            "ts_code": "300001.SZ",
            "period": "day",
            "adjustment": "forward",
            "start_date": "2026-04-07",
            "end_date": "2026-04-07",
            "limit": 10,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["bar_count"] == 1
    # Should use preheat bars before 2026-04-07, not treat this as first bar.
    assert payload["bars"][0]["ma5"] == "10.2000"


def test_quote_kline_supports_stock_week_backward_and_month_none(app_client, db_session) -> None:
    _ensure_quote_tables(db_session)
    db_session.add(
        Security(
            ts_code="002245.SZ",
            symbol="002245",
            name="蔚蓝锂芯",
            exchange="SZSE",
            industry="锂电池",
            list_status="L",
            security_type="EQUITY",
            source="tushare",
        )
    )
    db_session.add_all(
        [
            StkPeriodBarAdj(
                ts_code="002245.SZ",
                trade_date=date(2026, 3, 27),
                freq="week",
                open=Decimal("10.0000"),
                high=Decimal("11.0000"),
                low=Decimal("9.8000"),
                close=Decimal("10.5000"),
                pre_close=Decimal("9.9000"),
                open_qfq=Decimal("5.0000"),
                high_qfq=Decimal("5.5000"),
                low_qfq=Decimal("4.9000"),
                close_qfq=Decimal("5.2500"),
                open_hfq=Decimal("20.0000"),
                high_hfq=Decimal("22.0000"),
                low_hfq=Decimal("19.6000"),
                close_hfq=Decimal("21.0000"),
                vol=Decimal("100000.0000"),
                amount=Decimal("1000000.0000"),
                change_amount=Decimal("0.6000"),
                pct_chg=Decimal("6.0600"),
            ),
            StkPeriodBarAdj(
                ts_code="002245.SZ",
                trade_date=date(2026, 4, 3),
                freq="week",
                open=Decimal("10.6000"),
                high=Decimal("11.2000"),
                low=Decimal("10.4000"),
                close=Decimal("11.0000"),
                pre_close=Decimal("10.5000"),
                open_qfq=Decimal("5.3000"),
                high_qfq=Decimal("5.6000"),
                low_qfq=Decimal("5.2000"),
                close_qfq=Decimal("5.5000"),
                open_hfq=Decimal("21.2000"),
                high_hfq=Decimal("22.4000"),
                low_hfq=Decimal("20.8000"),
                close_hfq=Decimal("22.0000"),
                vol=Decimal("120000.0000"),
                amount=Decimal("1200000.0000"),
                change_amount=Decimal("0.5000"),
                pct_chg=Decimal("4.7619"),
            ),
        ]
    )
    db_session.add_all(
        [
            StkPeriodBar(
                ts_code="002245.SZ",
                trade_date=date(2026, 3, 31),
                freq="month",
                end_date=date(2026, 3, 31),
                open=Decimal("9.0000"),
                high=Decimal("11.5000"),
                low=Decimal("8.8000"),
                close=Decimal("10.8000"),
                pre_close=Decimal("9.6000"),
                vol=Decimal("500000.0000"),
                amount=Decimal("5000000.0000"),
                change_amount=Decimal("1.2000"),
                pct_chg=Decimal("12.5000"),
            )
        ]
    )
    db_session.commit()

    week_response = app_client.get(
        "/api/v1/quote/detail/kline",
        params={
            "ts_code": "002245.SZ",
            "security_type": "stock",
            "period": "week",
            "adjustment": "backward",
        },
    )
    assert week_response.status_code == 200
    week_payload = week_response.json()
    assert week_payload["meta"]["bar_count"] == 2
    assert week_payload["bars"][0]["close"] == "21.0000"
    assert week_payload["bars"][1]["close"] == "22.0000"

    month_response = app_client.get(
        "/api/v1/quote/detail/kline",
        params={
            "ts_code": "002245.SZ",
            "security_type": "stock",
            "period": "month",
            "adjustment": "none",
        },
    )
    assert month_response.status_code == 200
    month_payload = month_response.json()
    assert month_payload["meta"]["bar_count"] == 1
    assert month_payload["bars"][0]["trade_date"] == "2026-03-31"
    assert month_payload["bars"][0]["close"] == "10.8000"


def test_quote_page_init_supports_symbol_market_identifier(app_client, db_session) -> None:
    _ensure_quote_tables(db_session)
    db_session.add(
        Security(
            ts_code="300750.SZ",
            symbol="300750",
            name="宁德时代",
            exchange="SZSE",
            industry="锂电池",
            list_status="L",
            security_type="EQUITY",
            source="tushare",
        )
    )
    db_session.add(
        EquityDailyBar(
            ts_code="300750.SZ",
            trade_date=date(2026, 4, 2),
            open=Decimal("100.0000"),
            high=Decimal("102.0000"),
            low=Decimal("99.0000"),
            close=Decimal("101.0000"),
            pre_close=Decimal("99.5000"),
            change_amount=Decimal("1.5000"),
            pct_chg=Decimal("1.5075"),
            vol=Decimal("1000.0000"),
            amount=Decimal("100000.0000"),
            source="api",
        )
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/quote/detail/page-init",
        params={"symbol": "300750", "market": "SZ"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["instrument"]["ts_code"] == "300750.SZ"
    assert payload["instrument"]["symbol"] == "300750"


def test_quote_kline_rejects_invalid_date_range(app_client) -> None:
    response = app_client.get(
        "/api/v1/quote/detail/kline",
        params={
            "ts_code": "002245.SZ",
            "period": "day",
            "adjustment": "forward",
            "start_date": "2026-04-10",
            "end_date": "2026-04-01",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "INVALID_DATE_RANGE"


def test_quote_kline_etf_rejects_week_period(app_client, db_session) -> None:
    _ensure_quote_tables(db_session)
    db_session.add(
        EtfBasic(
            ts_code="510300.SH",
            csname="沪深300ETF",
            cname="沪深300ETF",
            list_status="L",
            exchange="SSE",
            etf_type="指数型",
        )
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/quote/detail/kline",
        params={
            "ts_code": "510300.SH",
            "security_type": "etf",
            "period": "week",
            "adjustment": "none",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "INVALID_ARGUMENT"


def test_quote_kline_limit_bounds_are_respected(app_client, db_session) -> None:
    _ensure_quote_tables(db_session)
    db_session.add(
        Security(
            ts_code="600000.SH",
            symbol="600000",
            name="浦发银行",
            exchange="SSE",
            industry="银行",
            list_status="L",
            security_type="EQUITY",
            source="tushare",
        )
    )
    db_session.add_all(
        [
            EquityDailyBar(
                ts_code="600000.SH",
                trade_date=date(2026, 4, 1),
                open=Decimal("10.0000"),
                high=Decimal("10.5000"),
                low=Decimal("9.9000"),
                close=Decimal("10.2000"),
                pre_close=Decimal("10.0000"),
                change_amount=Decimal("0.2000"),
                pct_chg=Decimal("2.0000"),
                vol=Decimal("1000.0000"),
                amount=Decimal("10000.0000"),
                source="api",
            ),
            EquityDailyBar(
                ts_code="600000.SH",
                trade_date=date(2026, 4, 2),
                open=Decimal("10.2000"),
                high=Decimal("10.6000"),
                low=Decimal("10.1000"),
                close=Decimal("10.3000"),
                pre_close=Decimal("10.2000"),
                change_amount=Decimal("0.1000"),
                pct_chg=Decimal("0.9804"),
                vol=Decimal("1200.0000"),
                amount=Decimal("12000.0000"),
                source="api",
            ),
        ]
    )
    db_session.add_all(
        [
            EquityAdjFactor(ts_code="600000.SH", trade_date=date(2026, 4, 1), adj_factor=Decimal("1.00000000")),
            EquityAdjFactor(ts_code="600000.SH", trade_date=date(2026, 4, 2), adj_factor=Decimal("1.00000000")),
        ]
    )
    db_session.commit()

    low_limit_resp = app_client.get(
        "/api/v1/quote/detail/kline",
        params={
            "ts_code": "600000.SH",
            "period": "day",
            "adjustment": "forward",
            "limit": 1,
        },
    )
    assert low_limit_resp.status_code == 200
    low_payload = low_limit_resp.json()
    assert low_payload["meta"]["bar_count"] == 1
    assert len(low_payload["bars"]) == 1

    high_limit_resp = app_client.get(
        "/api/v1/quote/detail/kline",
        params={
            "ts_code": "600000.SH",
            "period": "day",
            "adjustment": "forward",
            "limit": 2000,
        },
    )
    assert high_limit_resp.status_code == 200
    high_payload = high_limit_resp.json()
    assert high_payload["meta"]["bar_count"] == 2
    assert len(high_payload["bars"]) == 2


def test_quote_kline_returns_empty_bars_when_instrument_has_no_market_data(app_client, db_session) -> None:
    _ensure_quote_tables(db_session)
    db_session.add(
        Security(
            ts_code="688888.SH",
            symbol="688888",
            name="测试标的",
            exchange="SSE",
            industry="测试",
            list_status="L",
            security_type="EQUITY",
            source="tushare",
        )
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/quote/detail/kline",
        params={
            "ts_code": "688888.SH",
            "period": "day",
            "adjustment": "forward",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["instrument"]["ts_code"] == "688888.SH"
    assert payload["bars"] == []
    assert payload["meta"]["bar_count"] == 0
    assert payload["meta"]["has_more_history"] is False
    assert payload["meta"]["next_start_date"] is None
