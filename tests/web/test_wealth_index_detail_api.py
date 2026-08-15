from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.biz.services.wealth.config import StrategyConfigValidationError, StrategyConfigService
from src.biz.queries.wealth.market.index_detail import index_detail_page_query_service
from src.foundation.config.local_minute_capability import LocalMinuteCapability
from src.foundation.config.settings import get_settings
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.index_daily_basic import IndexDailyBasic
from src.foundation.models.core.index_factor_pro import IndexFactorPro
from src.foundation.models.core.index_weight import IndexWeight
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core_serving.security_serving import Security


_INDEX_CODE = "000001.SH"
_TRADE_DATE = date(2026, 8, 10)
_INDEX_CODES = (
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000688.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "899050.BJ",
    "000510.SH",
    "000016.SH",
)


def _ensure_index_detail_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [
        TradeCalendar.__table__,
        IndexBasic.__table__,
        IndexDailyServing.__table__,
        IndexDailyBasic.__table__,
        IndexFactorPro.__table__,
        IndexWeight.__table__,
        EquityDailyBar.__table__,
        EquitySuspendD.__table__,
        Security.__table__,
    ]:
        table.create(bind, checkfirst=True)


def _factor_row(
    *,
    ts_code: str,
    trade_date: date,
    close: float,
    vol: float = 111111.0,
    amount: float = 222222.0,
    ma250: float | None = 99.0,
) -> IndexFactorPro:
    row = IndexFactorPro(ts_code=ts_code, trade_date=trade_date, source="tushare")
    values = {
        "open": close - 1.0,
        "high": close + 2.0,
        "low": close - 2.0,
        "close": close,
        "pre_close": close - 0.5,
        "change": 0.5,
        "pct_change": 0.05,
        "vol": vol,
        "amount": amount,
        "ma_bfq_5": close - 0.1,
        "ma_bfq_10": close - 0.2,
        "ma_bfq_20": close - 0.3,
        "ma_bfq_30": close - 0.4,
        "ma_bfq_60": close - 0.5,
        "ma_bfq_90": close - 0.6,
        "ma_bfq_250": ma250,
        "boll_upper_bfq": close + 3.0,
        "boll_mid_bfq": close,
        "boll_lower_bfq": close - 3.0,
        "macd_dif_bfq": 1.1,
        "macd_dea_bfq": 1.2,
        "macd_bfq": 1.3,
        "kdj_k_bfq": 44.0,
        "kdj_d_bfq": 55.0,
        "kdj_bfq": 66.0,
    }
    for field_name, value in values.items():
        setattr(row, field_name, value)
    return row


def _daily_row(*, trade_date: date, close: Decimal = Decimal("1000.0000")) -> IndexDailyServing:
    return IndexDailyServing(
        ts_code=_INDEX_CODE,
        trade_date=trade_date,
        open=Decimal("999.0000"),
        high=Decimal("1010.0000"),
        low=Decimal("990.0000"),
        close=close,
        pre_close=Decimal("1000.0000"),
        change_amount=Decimal("5.0000"),
        pct_chg=Decimal("0.5000"),
        vol=Decimal("999999999.0000"),
        amount=Decimal("888888888.0000"),
        source="tushare",
    )


def _equity_daily(*, ts_code: str, pct_chg: Decimal | None) -> EquityDailyBar:
    return EquityDailyBar(
        ts_code=ts_code,
        trade_date=_TRADE_DATE,
        open=Decimal("10.0000"),
        high=Decimal("11.0000"),
        low=Decimal("9.0000"),
        close=Decimal("10.5000"),
        pre_close=Decimal("10.0000"),
        change_amount=Decimal("0.5000") if pct_chg is not None else None,
        pct_chg=pct_chg,
        vol=Decimal("1000.0000"),
        amount=Decimal("10000.0000"),
        source="tushare",
    )


def _security(
    *,
    ts_code: str,
    name: str,
    exchange: str = "SSE",
    curr_type: str = "CNY",
) -> Security:
    return Security(
        ts_code=ts_code,
        name=name,
        security_type="EQUITY",
        exchange=exchange,
        curr_type=curr_type,
        source="tushare",
    )


def _suspend_row(*, row_id: int, ts_code: str) -> EquitySuspendD:
    return EquitySuspendD(
        id=row_id,
        row_key_hash=f"{ts_code}-{_TRADE_DATE.isoformat()}-S",
        ts_code=ts_code,
        trade_date=_TRADE_DATE,
        suspend_timing=None,
        suspend_type="S",
    )


def _seed_full_data(db_session) -> None:
    _ensure_index_detail_tables(db_session)
    db_session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 8, 7),
                is_open=True,
                pretrade_date=date(2026, 8, 6),
            ),
            TradeCalendar(
                exchange="SSE",
                trade_date=_TRADE_DATE,
                is_open=True,
                pretrade_date=date(2026, 8, 7),
            ),
            IndexBasic(
                ts_code=_INDEX_CODE,
                name="上证指数",
                market="SSE",
                category="综合指数",
                publisher="中证指数有限公司",
            ),
            _daily_row(trade_date=_TRADE_DATE),
            _factor_row(ts_code=_INDEX_CODE, trade_date=date(2026, 8, 7), close=100.0, vol=700.0, amount=7000.0),
            _factor_row(ts_code=_INDEX_CODE, trade_date=_TRADE_DATE, close=105.0, vol=123456.0, amount=654321.0),
            IndexDailyBasic(
                ts_code=_INDEX_CODE,
                trade_date=_TRADE_DATE,
                pe=Decimal("17.1600"),
                pe_ttm=Decimal("16.8800"),
                pb=Decimal("1.4900"),
                turnover_rate=Decimal("1.1000"),
                float_mv=Decimal("61120718611804.0200"),
                total_mv=Decimal("77487881305217.3300"),
            ),
            _security(ts_code="600001.SH", name="甲公司"),
            _security(ts_code="600002.SH", name="乙公司"),
            _security(ts_code="600003.SH", name="丙公司"),
            _security(ts_code="600004.SH", name="丁公司"),
            IndexWeight(
                index_code=_INDEX_CODE,
                trade_date=date(2026, 7, 31),
                con_code="600001.SH",
                weight=Decimal("30.00000000"),
            ),
            IndexWeight(
                index_code=_INDEX_CODE,
                trade_date=date(2026, 7, 31),
                con_code="600002.SH",
                weight=Decimal("20.00000000"),
            ),
            IndexWeight(
                index_code=_INDEX_CODE,
                trade_date=date(2026, 7, 31),
                con_code="600003.SH",
                weight=Decimal("10.00000000"),
            ),
            IndexWeight(
                index_code=_INDEX_CODE,
                trade_date=date(2026, 7, 31),
                con_code="600004.SH",
                weight=Decimal("5.00000000"),
            ),
            _equity_daily(ts_code="600001.SH", pct_chg=Decimal("2.0000")),
            _equity_daily(ts_code="600002.SH", pct_chg=Decimal("-1.0000")),
            _equity_daily(ts_code="600003.SH", pct_chg=Decimal("0.0000")),
        ]
    )
    db_session.commit()


def test_page_init_uses_daily_prices_factor_volume_and_complete_basic_contract(app_client, db_session) -> None:
    _seed_full_data(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/index-detail/page-init",
        params={"tsCode": " 000001.sh ", "tradeDate": "2026-08-10", "debug": "1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pageContext"]["tradeDate"] == "2026-08-10"
    assert payload["asOfTradeDate"] == "2026-08-10"
    assert payload["index"] == {
        "tsCode": _INDEX_CODE,
        "name": "上证指数",
        "market": "SSE",
        "category": "综合指数",
        "publisher": "中证指数有限公司",
        "tags": ["综合指数", "SSE"],
    }
    assert payload["quote"]["point"] == 1000.0
    assert payload["quote"]["vol"] == 123456.0
    assert payload["quote"]["amount"] == 654321.0
    assert payload["quote"]["vol"] != 999999999.0
    assert payload["dailyBasic"]["peTtm"] == 16.88
    assert payload["constituentBreadth"]["upCount"] == 1
    assert payload["constituentBreadth"]["flatCount"] == 1
    assert payload["constituentBreadth"]["downCount"] == 1
    assert payload["constituentBreadth"]["matchedCount"] == 3
    assert payload["constituentBreadth"]["missingCount"] == 1
    assert payload["constituentBreadth"]["totalConstituentCount"] == 4
    assert payload["dataStatus"]["status"] == "PARTIAL"
    assert payload["chartDefaults"]["availableMainOverlays"] == ["MA", "BOLL", "TREND_CHANNEL"]
    assert payload["capabilities"]["supportsTrendChannel"] is True
    assert payload["capabilities"]["supportsNineTurn"] is True
    assert payload["capabilities"]["nineTurnPeriods"] == ["day"]
    assert payload["debugInfo"]["modules"][0]["module"] == "pageInit"
    assert {item["code"] for item in payload["debugInfo"]["exceptions"]} == {
        "ID_BASIC_BREADTH_PARTIAL"
    }

    no_debug = app_client.get(
        "/api/v1/wealth/market/index-detail/page-init",
        params={"tsCode": _INDEX_CODE, "tradeDate": "2026-08-10"},
    )
    assert no_debug.status_code == 200
    assert no_debug.json()["debugInfo"] is None


def test_page_init_uses_the_index_nine_turn_router_capability_resolver(monkeypatch) -> None:
    enabled = LocalMinuteCapability(enabled=True, lake_root=None, reason_code=None)
    disabled = LocalMinuteCapability(enabled=False, lake_root=None, reason_code=None)
    monkeypatch.setattr(index_detail_page_query_service, "resolve_index_minute_capability", lambda _: disabled)
    monkeypatch.setattr(
        index_detail_page_query_service,
        "resolve_index_nine_turn_minute_capability",
        lambda _: enabled,
    )

    capabilities = index_detail_page_query_service.IndexDetailPageQueryService._build_capabilities(
        ts_code=_INDEX_CODE
    )

    assert capabilities.supportsMinute is False
    assert capabilities.supportsNineTurn is True
    assert capabilities.nineTurnPeriods == ["day", "5", "15", "30", "60", "90", "120"]


def test_page_init_keeps_factor_amount_null_and_never_falls_back_to_daily(app_client, db_session) -> None:
    _seed_full_data(db_session)
    factor = db_session.get(IndexFactorPro, (_INDEX_CODE, _TRADE_DATE))
    factor.amount = None
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/index-detail/page-init",
        params={"tsCode": _INDEX_CODE, "tradeDate": "2026-08-10", "debug": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["quote"]["amount"] is None
    assert payload["quote"]["vol"] == 123456.0
    assert payload["dataStatus"]["status"] == "PARTIAL"
    assert "ID_FACTOR_PARTIAL" in {item["code"] for item in payload["debugInfo"]["exceptions"]}


def test_all_ten_configured_indices_are_accepted_and_only_sse_composite_has_trend(app_client, db_session) -> None:
    _ensure_index_detail_tables(db_session)
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=_TRADE_DATE,
            is_open=True,
            pretrade_date=date(2026, 8, 7),
        )
    )
    for index, ts_code in enumerate(_INDEX_CODES):
        db_session.add(IndexBasic(ts_code=ts_code, name=f"指数{index}", market="CN_A"))
        daily = _daily_row(trade_date=_TRADE_DATE)
        daily.ts_code = ts_code
        db_session.add(daily)
        db_session.add(_factor_row(ts_code=ts_code, trade_date=_TRADE_DATE, close=100.0 + index))
    db_session.commit()

    for ts_code in _INDEX_CODES:
        response = app_client.get(
            "/api/v1/wealth/market/index-detail/page-init",
            params={"tsCode": ts_code, "tradeDate": "2026-08-10"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["index"]["tsCode"] == ts_code
        assert payload["capabilities"]["supportsTrendChannel"] is (ts_code == _INDEX_CODE)
        assert ("TREND_CHANNEL" in payload["chartDefaults"]["availableMainOverlays"]) is (
            ts_code == _INDEX_CODE
        )


def test_page_init_can_be_delayed_without_becoming_partial(app_client, db_session) -> None:
    _seed_full_data(db_session)
    db_session.add(_equity_daily(ts_code="600004.SH", pct_chg=Decimal("1.0000")))
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/index-detail/page-init",
        params={"tsCode": _INDEX_CODE, "tradeDate": "2026-08-11", "debug": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asOfTradeDate"] == "2026-08-10"
    assert payload["dataStatus"]["status"] == "DELAYED"
    assert {item["code"] for item in payload["debugInfo"]["exceptions"]} == {"ID_SOURCE_DELAYED"}


def test_page_init_without_daily_source_returns_empty_with_stable_identity(app_client, db_session) -> None:
    _ensure_index_detail_tables(db_session)
    db_session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=_TRADE_DATE,
                is_open=True,
                pretrade_date=date(2026, 8, 7),
            ),
            IndexBasic(ts_code=_INDEX_CODE, name="上证指数", market="SSE"),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/index-detail/page-init",
        params={"tsCode": _INDEX_CODE, "tradeDate": "2026-08-10", "debug": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["index"]["name"] == "上证指数"
    assert payload["asOfTradeDate"] is None
    assert payload["quote"] is None
    assert payload["dailyBasic"] is None
    assert payload["constituentBreadth"] is None
    assert payload["dataStatus"]["status"] == "EMPTY"
    assert payload["debugInfo"]["exceptions"][0]["code"] == "ID_SOURCE_EMPTY"


def test_kline_is_factor_only_ascending_and_has_no_adjustment_contract(app_client, db_session) -> None:
    _seed_full_data(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/index-detail/kline",
        params={"tsCode": _INDEX_CODE, "endDate": "2026-08-10", "limit": "300"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [bar["tradeDate"] for bar in payload["bars"]] == ["2026-08-07", "2026-08-10"]
    assert payload["bars"][-1]["close"] == 105.0
    assert payload["bars"][-1]["vol"] == 123456.0
    assert payload["bars"][-1]["amount"] == 654321.0
    assert payload["bars"][-1]["factors"]["kdj"]["j"] == 66.0
    assert "ma15" not in payload["bars"][-1]["factors"]["ma"]
    assert "ma120" not in payload["bars"][-1]["factors"]["ma"]
    assert payload["meta"] == {
        "count": 2,
        "limit": 300,
        "startDate": None,
        "endDate": "2026-08-10",
    }
    assert "adjustment" not in payload
    assert "sourceAdjustment" not in payload

    rejected = app_client.get(
        "/api/v1/wealth/market/index-detail/kline",
        params={"tsCode": _INDEX_CODE, "adjustment": "forward"},
    )
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "ID_REQUEST_INVALID"


def test_ma250_null_reclassifies_after_earlier_history_arrives(app_client, db_session) -> None:
    _ensure_index_detail_tables(db_session)
    db_session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=_TRADE_DATE,
                is_open=True,
                pretrade_date=date(2026, 8, 7),
            ),
            IndexBasic(ts_code=_INDEX_CODE, name="上证指数", market="SSE"),
            _daily_row(trade_date=_TRADE_DATE),
            _factor_row(ts_code=_INDEX_CODE, trade_date=_TRADE_DATE, close=105.0, ma250=None),
        ]
    )
    history_start = date(2024, 1, 1)
    for offset in range(248):
        history_row = IndexFactorPro(
            ts_code=_INDEX_CODE,
            trade_date=history_start + timedelta(days=offset),
            source="tushare",
        )
        history_row.close = 90.0
        db_session.add(history_row)
    db_session.commit()

    params = {
        "tsCode": _INDEX_CODE,
        "startDate": "2026-08-10",
        "endDate": "2026-08-10",
        "limit": 1,
        "debug": 1,
    }
    before_backfill = app_client.get("/api/v1/wealth/market/index-detail/kline", params=params)
    assert before_backfill.status_code == 200
    assert before_backfill.json()["bars"][0]["factors"]["ma"]["ma250"] is None
    assert before_backfill.json()["dataStatus"]["status"] == "READY"

    earlier_history = IndexFactorPro(
        ts_code=_INDEX_CODE,
        trade_date=date(2023, 12, 31),
        source="tushare",
    )
    earlier_history.close = 89.0
    db_session.add(earlier_history)
    db_session.commit()

    after_backfill = app_client.get("/api/v1/wealth/market/index-detail/kline", params=params)
    assert after_backfill.status_code == 200
    payload = after_backfill.json()
    assert payload["bars"][0]["factors"]["ma"]["ma250"] is None
    assert payload["dataStatus"]["status"] == "PARTIAL"
    assert "ID_FACTOR_PARTIAL" in {item["code"] for item in payload["debugInfo"]["exceptions"]}


def test_kline_distinguishes_source_delay_from_factor_lag(app_client, db_session) -> None:
    _seed_full_data(db_session)

    delayed = app_client.get(
        "/api/v1/wealth/market/index-detail/kline",
        params={"tsCode": _INDEX_CODE, "endDate": "2026-08-11", "debug": 1},
    )
    assert delayed.status_code == 200
    assert delayed.json()["dataStatus"]["status"] == "DELAYED"

    latest_factor = db_session.get(IndexFactorPro, (_INDEX_CODE, _TRADE_DATE))
    db_session.delete(latest_factor)
    db_session.commit()

    partial = app_client.get(
        "/api/v1/wealth/market/index-detail/kline",
        params={"tsCode": _INDEX_CODE, "endDate": "2026-08-10", "debug": 1},
    )
    assert partial.status_code == 200
    payload = partial.json()
    assert payload["dataStatus"]["status"] == "PARTIAL"
    assert {item["code"] for item in payload["debugInfo"]["exceptions"]} == {
        "ID_FACTOR_PARTIAL",
        "ID_SOURCE_DELAYED",
    }


def test_page_and_weights_use_a_shares_with_daily_first_and_suspension_fallback(
    app_client,
    db_session,
) -> None:
    _seed_full_data(db_session)
    db_session.add_all(
        [
            _equity_daily(ts_code="600004.SH", pct_chg=Decimal("1.0000")),
            _security(ts_code="600005.SH", name="停牌公司"),
            _security(ts_code="600006.SH", name="日线优先公司"),
            _security(ts_code="900901.SH", name="B股公司", curr_type="USD"),
            IndexWeight(
                index_code=_INDEX_CODE,
                trade_date=date(2026, 7, 31),
                con_code="600005.SH",
                weight=Decimal("4.00000000"),
            ),
            IndexWeight(
                index_code=_INDEX_CODE,
                trade_date=date(2026, 7, 31),
                con_code="600006.SH",
                weight=Decimal("3.00000000"),
            ),
            IndexWeight(
                index_code=_INDEX_CODE,
                trade_date=date(2026, 7, 31),
                con_code="900901.SH",
                weight=Decimal("99.00000000"),
            ),
            _equity_daily(ts_code="600006.SH", pct_chg=Decimal("3.0000")),
            _suspend_row(row_id=1, ts_code="600005.SH"),
            _suspend_row(row_id=2, ts_code="600006.SH"),
        ]
    )
    db_session.commit()

    page_response = app_client.get(
        "/api/v1/wealth/market/index-detail/page-init",
        params={"tsCode": _INDEX_CODE, "tradeDate": "2026-08-10", "debug": 1},
    )

    assert page_response.status_code == 200
    page_payload = page_response.json()
    assert page_payload["constituentBreadth"] == {
        "tradeDate": "2026-08-10",
        "weightTradeDate": "2026-07-31",
        "upCount": 3,
        "flatCount": 2,
        "downCount": 1,
        "totalConstituentCount": 6,
        "matchedCount": 6,
        "missingCount": 0,
        "dataStatus": {
            "status": "READY",
            "expectedTradeDate": "2026-08-10",
            "observedTradeDate": "2026-08-10",
        },
    }
    assert page_payload["dataStatus"]["status"] == "READY"
    assert page_payload["debugInfo"]["exceptions"] == []

    weights_response = app_client.get(
        "/api/v1/wealth/market/index-detail/weights",
        params={"tsCode": _INDEX_CODE, "tradeDate": "2026-08-10", "debug": 1},
    )

    assert weights_response.status_code == 200
    weights_payload = weights_response.json()
    codes = [row["conCode"] for row in weights_payload["rows"]]
    assert codes == [
        "600001.SH",
        "600002.SH",
        "600003.SH",
        "600004.SH",
        "600005.SH",
        "600006.SH",
    ]
    assert "900901.SH" not in codes
    rows_by_code = {row["conCode"]: row for row in weights_payload["rows"]}
    assert rows_by_code["600005.SH"]["changePct"] == 0.0
    assert rows_by_code["600005.SH"]["direction"] == "FLAT"
    assert rows_by_code["600005.SH"]["contributionPoint"] == 0.0
    assert rows_by_code["600006.SH"]["changePct"] == 3.0
    assert rows_by_code["600006.SH"]["direction"] == "UP"
    assert rows_by_code["600006.SH"]["contributionPoint"] == 0.9
    assert weights_payload["coverage"] == {
        "totalCount": 6,
        "returnedCount": 6,
        "contributionAvailableCount": 6,
        "contributionMissingCount": 0,
        "isTruncated": False,
    }
    assert weights_payload["dataStatus"]["status"] == "READY"
    assert weights_payload["debugInfo"]["exceptions"] == []


def test_weights_return_complete_batch_stable_sort_and_frozen_contribution(app_client, db_session) -> None:
    _seed_full_data(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/index-detail/weights",
        params={"tsCode": _INDEX_CODE, "tradeDate": "2026-08-10", "debug": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["weightTradeDate"] == "2026-07-31"
    assert [row["conCode"] for row in payload["rows"]] == [
        "600001.SH",
        "600002.SH",
        "600003.SH",
        "600004.SH",
    ]
    assert [row["contributionPoint"] for row in payload["rows"]] == [6.0, -2.0, 0.0, None]
    assert payload["rows"][-1]["name"] == "丁公司"
    assert payload["rows"][-1]["direction"] == "UNKNOWN"
    assert payload["coverage"] == {
        "totalCount": 4,
        "returnedCount": 4,
        "contributionAvailableCount": 3,
        "contributionMissingCount": 1,
        "isTruncated": False,
    }
    assert payload["dataStatus"]["status"] == "PARTIAL"
    assert payload["note"] == "基于最新月度权重估算，非指数公司官方归因"
    assert "ID_WEIGHT_CONTRIBUTION_PARTIAL" in {
        item["code"] for item in payload["debugInfo"]["exceptions"]
    }


def test_weights_without_batch_return_empty_instead_of_fake_zero_rows(app_client, db_session) -> None:
    _ensure_index_detail_tables(db_session)
    db_session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=_TRADE_DATE,
                is_open=True,
                pretrade_date=date(2026, 8, 7),
            ),
            IndexBasic(ts_code=_INDEX_CODE, name="上证指数", market="SSE"),
            _daily_row(trade_date=_TRADE_DATE),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/index-detail/weights",
        params={"tsCode": _INDEX_CODE, "tradeDate": "2026-08-10", "debug": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataStatus"]["status"] == "EMPTY"
    assert payload["weightTradeDate"] is None
    assert payload["rows"] == []
    assert payload["coverage"]["totalCount"] == 0
    assert payload["debugInfo"]["exceptions"][0]["code"] == "ID_WEIGHT_EMPTY"


def test_weights_reject_incomplete_batch_instead_of_filtering_rows(app_client, db_session) -> None:
    _seed_full_data(db_session)
    weight = db_session.get(IndexWeight, (_INDEX_CODE, date(2026, 7, 31), "600004.SH"))
    weight.weight = None
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/index-detail/weights",
        params={"tsCode": _INDEX_CODE, "tradeDate": "2026-08-10"},
    )

    assert response.status_code == 500
    assert response.json()["code"] == "ID_QUERY_FAILED"


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("page-init", {"tsCode": "bad"}),
        ("page-init", {"tsCode": _INDEX_CODE, "tradeDate": "2026-02-30"}),
        ("page-init", {"tsCode": _INDEX_CODE, "debug": "2"}),
        ("kline", {"tsCode": _INDEX_CODE, "period": "week"}),
        ("kline", {"tsCode": _INDEX_CODE, "limit": "0"}),
        ("kline", {"tsCode": _INDEX_CODE, "startDate": "2026-08-11", "endDate": "2026-08-10"}),
        ("weights", {"tsCode": _INDEX_CODE, "limit": "10"}),
    ],
)
def test_all_index_detail_request_errors_use_frozen_400_code(app_client, path, params) -> None:
    response = app_client.get(f"/api/v1/wealth/market/index-detail/{path}", params=params)

    assert response.status_code == 400
    assert response.json()["code"] == "ID_REQUEST_INVALID"


def test_non_member_and_missing_identity_both_use_frozen_404_code(app_client, db_session) -> None:
    _ensure_index_detail_tables(db_session)

    non_member = app_client.get(
        "/api/v1/wealth/market/index-detail/page-init",
        params={"tsCode": "000002.SH"},
    )
    assert non_member.status_code == 404
    assert non_member.json()["code"] == "ID_NOT_FOUND"

    missing_identity = app_client.get(
        "/api/v1/wealth/market/index-detail/page-init",
        params={"tsCode": _INDEX_CODE},
    )
    assert missing_identity.status_code == 404
    assert missing_identity.json()["code"] == "ID_NOT_FOUND"


def test_invalid_universe_config_fails_closed_with_query_error(app_client, monkeypatch) -> None:
    def fail_config(*_args, **_kwargs):
        raise StrategyConfigValidationError("broken config details must not leak")

    monkeypatch.setattr(StrategyConfigService, "get_config", fail_config)

    response = app_client.get(
        "/api/v1/wealth/market/index-detail/page-init",
        params={"tsCode": _INDEX_CODE},
    )

    assert response.status_code == 500
    assert response.json()["code"] == "ID_QUERY_FAILED"
    assert "broken config" not in response.json()["message"]


def test_index_detail_reuses_quote_authentication(app_client, monkeypatch) -> None:
    monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        response = app_client.get(
            "/api/v1/wealth/market/index-detail/page-init",
            params={"tsCode": _INDEX_CODE},
        )
        assert response.status_code == 401
        assert response.json()["code"] == "auth_required"
    finally:
        monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "false")
        get_settings.cache_clear()
