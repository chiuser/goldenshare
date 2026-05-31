from __future__ import annotations

from datetime import date

from src.foundation.models.core.equity_factor_pro import EquityFactorPro
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.security_serving import Security


def _ensure_stock_detail_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [
        TradeCalendar.__table__,
        Security.__table__,
        EquityFactorPro.__table__,
    ]:
        table.create(bind, checkfirst=True)


def _factor_row(*, ts_code: str, trade_date: date, close: float, kdj_j: float) -> EquityFactorPro:
    row = EquityFactorPro(ts_code=ts_code, trade_date=trade_date, source="tushare")
    values = {
        "open": close - 0.5,
        "high": close + 0.8,
        "low": close - 1.0,
        "close": close,
        "pre_close": close - 0.2,
        "change": 0.2,
        "pct_chg": 1.25,
        "vol": 123456.0,
        "amount": 2345678.0,
        "turnover_rate": 1.23,
        "volume_ratio": 1.11,
        "ma_qfq_5": close - 0.1,
        "ma_qfq_10": close - 0.2,
        "ma_qfq_20": close - 0.3,
        "ma_qfq_30": close - 0.4,
        "ma_qfq_60": close - 0.5,
        "ma_qfq_90": close - 0.6,
        "ma_qfq_250": close - 0.7,
        "boll_upper_qfq": close + 1.2,
        "boll_mid_qfq": close,
        "boll_lower_qfq": close - 1.2,
        "macd_dif_qfq": 0.11,
        "macd_dea_qfq": 0.22,
        "macd_qfq": 0.33,
        "kdj_k_qfq": 44.4,
        "kdj_d_qfq": 55.5,
        "kdj_qfq": kdj_j,
    }
    for key, value in values.items():
        setattr(row, key, value)
    return row


def _seed_stock_detail_data(db_session) -> None:
    _ensure_stock_detail_tables(db_session)
    db_session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 5, 28),
                is_open=True,
                pretrade_date=date(2026, 5, 27),
            ),
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 5, 29),
                is_open=True,
                pretrade_date=date(2026, 5, 28),
            ),
            Security(
                ts_code="603806.SH",
                symbol="603806",
                name="福斯特",
                market="主板",
                exchange="SSE",
                industry="光伏设备",
                area="浙江",
                list_status="L",
                security_type="EQUITY",
                source="tushare",
            ),
            _factor_row(ts_code="603806.SH", trade_date=date(2026, 5, 28), close=18.5, kdj_j=66.6),
            _factor_row(ts_code="603806.SH", trade_date=date(2026, 5, 29), close=19.1, kdj_j=77.7),
        ]
    )
    db_session.commit()


def test_stock_detail_page_init_returns_context_stock_quote_and_defaults(app_client, db_session) -> None:
    _seed_stock_detail_data(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/page-init",
        params={"tsCode": "603806.SH", "tradeDate": "2026-05-29", "debug": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pageContext"]["tradeDate"] == "2026-05-29"
    assert payload["stock"]["tsCode"] == "603806.SH"
    assert payload["stock"]["name"] == "福斯特"
    assert payload["quote"]["tradeDate"] == "2026-05-29"
    assert payload["quote"]["price"] == 19.1
    assert payload["chartDefaults"]["defaultAdjustment"] == "forward"
    assert payload["chartDefaults"]["sourceAdjustment"] == "qfq"
    assert payload["chartDefaults"]["availablePeriods"] == ["day"]
    assert payload["dataStatus"]["status"] == "READY"
    assert payload["debugInfo"]["sourceTables"] == [
        "core_serving.security_serving",
        "core_serving.equity_factor_pro",
    ]


def test_stock_detail_kline_returns_day_forward_bars_without_forbidden_ma(app_client, db_session) -> None:
    _seed_stock_detail_data(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/kline",
        params={"tsCode": "603806.SH", "period": "day", "adjustment": "forward", "endDate": "2026-05-29"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["period"] == "day"
    assert payload["adjustment"] == "forward"
    assert payload["sourceAdjustment"] == "qfq"
    assert payload["meta"]["count"] == 2
    assert [bar["tradeDate"] for bar in payload["bars"]] == ["2026-05-28", "2026-05-29"]
    latest = payload["bars"][-1]
    ma = latest["factors"]["ma"]
    assert ma["ma5"] == 19.0
    assert ma["ma10"] == 18.9
    assert ma["ma20"] == 18.8
    assert ma["ma90"] == 18.5
    assert "ma15" not in ma
    assert "ma120" not in ma
    assert latest["factors"]["kdj"]["j"] == 77.7


def test_stock_detail_kline_rejects_unsupported_period_and_adjustment(app_client, db_session) -> None:
    _seed_stock_detail_data(db_session)

    period_response = app_client.get(
        "/api/v1/wealth/market/stock-detail/kline",
        params={"tsCode": "603806.SH", "period": "week", "adjustment": "forward"},
    )
    assert period_response.status_code == 400
    assert period_response.json()["code"] == "400001"

    adjustment_response = app_client.get(
        "/api/v1/wealth/market/stock-detail/kline",
        params={"tsCode": "603806.SH", "period": "day", "adjustment": "qfq"},
    )
    assert adjustment_response.status_code == 400
    assert adjustment_response.json()["code"] == "400001"


def test_stock_detail_returns_404_for_unknown_stock(app_client, db_session) -> None:
    _ensure_stock_detail_tables(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/page-init",
        params={"tsCode": "000000.SH", "tradeDate": "2026-05-29"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "404001"
