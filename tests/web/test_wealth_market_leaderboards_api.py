from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.foundation.models.core.dc_hot import DcHot
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.security_serving import Security


def _ensure_leaderboards_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [
        TradeCalendar.__table__,
        Security.__table__,
        EquityDailyBar.__table__,
        EquityDailyBasic.__table__,
        DcHot.__table__,
    ]:
        table.create(bind, checkfirst=True)


def _seed_security_rows(db_session) -> None:
    db_session.add_all(
        [
            Security(
                ts_code="000001.SZ",
                name="平安银行",
                exchange="SZSE",
                list_status="L",
                list_date=date(1991, 4, 3),
                security_type="EQUITY",
            ),
            Security(
                ts_code="000002.SZ",
                name="万 科Ａ",
                exchange="SZSE",
                list_status="L",
                list_date=date(1991, 1, 29),
                security_type="EQUITY",
            ),
            Security(
                ts_code="000003.SZ",
                name="国农科技",
                exchange="SZSE",
                list_status="L",
                list_date=date(1992, 2, 20),
                security_type="EQUITY",
            ),
        ]
    )


def _seed_equity_rows(db_session) -> None:
    trade_day = date(2026, 5, 8)
    db_session.add_all(
        [
            EquityDailyBar(
                ts_code="000001.SZ",
                trade_date=trade_day,
                open=Decimal("10.0000"),
                high=Decimal("10.6000"),
                low=Decimal("9.9000"),
                close=Decimal("10.5000"),
                pre_close=Decimal("10.0000"),
                change_amount=Decimal("0.5000"),
                pct_chg=Decimal("5.0000"),
                vol=Decimal("1200000.0000"),
                amount=Decimal("100000000.0000"),
                source="tushare",
            ),
            EquityDailyBar(
                ts_code="000002.SZ",
                trade_date=trade_day,
                open=Decimal("20.0000"),
                high=Decimal("20.1000"),
                low=Decimal("19.2000"),
                close=Decimal("19.2000"),
                pre_close=Decimal("20.0000"),
                change_amount=Decimal("-0.8000"),
                pct_chg=Decimal("-4.0000"),
                vol=Decimal("800000.0000"),
                amount=Decimal("90000000.0000"),
                source="tushare",
            ),
            EquityDailyBar(
                ts_code="000003.SZ",
                trade_date=trade_day,
                open=Decimal("5.0000"),
                high=Decimal("5.3000"),
                low=Decimal("4.9000"),
                close=Decimal("5.2000"),
                pre_close=Decimal("5.0000"),
                change_amount=Decimal("0.2000"),
                pct_chg=Decimal("4.0000"),
                vol=Decimal("1500000.0000"),
                amount=Decimal("120000000.0000"),
                source="tushare",
            ),
        ]
    )
    db_session.add_all(
        [
            EquityDailyBasic(
                ts_code="000001.SZ",
                trade_date=trade_day,
                turnover_rate=Decimal("4.3200"),
                volume_ratio=Decimal("1.2000"),
            ),
            EquityDailyBasic(
                ts_code="000002.SZ",
                trade_date=trade_day,
                turnover_rate=Decimal("7.5600"),
                volume_ratio=Decimal("3.8000"),
            ),
            EquityDailyBasic(
                ts_code="000003.SZ",
                trade_date=trade_day,
                turnover_rate=Decimal("6.1100"),
                volume_ratio=Decimal("2.6000"),
            ),
        ]
    )


def _seed_dc_hot_rows(db_session, *, trade_day: date) -> None:
    db_session.add_all(
        [
            DcHot(
                trade_date=trade_day,
                data_type="A股市场",
                ts_code="000001.SZ",
                rank_time="15:00:00",
                query_market="A股市场",
                query_hot_type="人气榜",
                query_is_new="N",
                ts_name="平安银行",
                rank=1,
                pct_change=Decimal("5.0000"),
                current_price=Decimal("10.5000"),
                hot=Decimal("99.9000"),
            ),
            DcHot(
                trade_date=trade_day,
                data_type="A股市场",
                ts_code="000003.SZ",
                rank_time="15:00:00",
                query_market="A股市场",
                query_hot_type="人气榜",
                query_is_new="N",
                ts_name="国农科技",
                rank=2,
                pct_change=Decimal("4.0000"),
                current_price=Decimal("5.2000"),
                hot=Decimal("88.8000"),
            ),
            DcHot(
                trade_date=trade_day,
                data_type="A股市场",
                ts_code="000003.SZ",
                rank_time="15:00:00",
                query_market="A股市场",
                query_hot_type="飙升榜",
                query_is_new="N",
                ts_name="国农科技",
                rank=1,
                pct_change=Decimal("4.0000"),
                current_price=Decimal("5.2000"),
                hot=Decimal("77.7000"),
            ),
            DcHot(
                trade_date=trade_day,
                data_type="A股市场",
                ts_code="000001.SZ",
                rank_time="15:00:00",
                query_market="A股市场",
                query_hot_type="飙升榜",
                query_is_new="N",
                ts_name="平安银行",
                rank=2,
                pct_change=Decimal("5.0000"),
                current_price=Decimal("10.5000"),
                hot=Decimal("66.6000"),
            ),
        ]
    )


def test_market_leaderboards_endpoint_returns_7_boards(app_client, db_session) -> None:
    _ensure_leaderboards_tables(db_session)
    db_session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 5, 7),
                is_open=True,
                pretrade_date=date(2026, 5, 6),
            ),
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 5, 8),
                is_open=True,
                pretrade_date=date(2026, 5, 7),
            ),
        ]
    )
    _seed_security_rows(db_session)
    _seed_equity_rows(db_session)
    _seed_dc_hot_rows(db_session, trade_day=date(2026, 5, 8))
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/leaderboards", params={"tradeDate": "2026-05-08", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["tradingDay"]["tradeDate"] == "2026-05-08"
    assert payload["pageStatus"]["status"] == "READY"
    assert [item["boardKey"] for item in payload["definitions"]] == [
        "gainers",
        "losers",
        "amount",
        "turnover",
        "volumeRatio",
        "popularity",
        "surge",
    ]
    boards_by_key = {board["boardKey"]: board for board in payload["boards"]}
    assert len(boards_by_key) == 7
    assert boards_by_key["gainers"]["rows"][0]["subject"]["subjectCode"] == "000001.SZ"
    assert boards_by_key["losers"]["rows"][0]["subject"]["subjectCode"] == "000002.SZ"
    assert boards_by_key["amount"]["rows"][0]["subject"]["subjectCode"] == "000003.SZ"
    assert boards_by_key["popularity"]["rows"][0]["rank"] == 1
    assert boards_by_key["surge"]["rows"][0]["rank"] == 1
    assert boards_by_key["popularity"]["rows"][0]["metrics"]["turnoverRate"] is not None
    assert boards_by_key["popularity"]["rows"][0]["metrics"]["volumeRatio"] is not None
    assert boards_by_key["popularity"]["rows"][0]["metrics"]["volume"] is not None
    assert boards_by_key["popularity"]["rows"][0]["metrics"]["amount"] is not None
    assert boards_by_key["surge"]["rows"][0]["metrics"]["turnoverRate"] is not None
    assert boards_by_key["surge"]["rows"][0]["metrics"]["volumeRatio"] is not None
    assert boards_by_key["surge"]["rows"][0]["metrics"]["volume"] is not None
    assert boards_by_key["surge"]["rows"][0]["metrics"]["amount"] is not None
    assert payload["debugInfo"]["modules"][0]["moduleKey"] == "leaderboards"


def test_market_leaderboards_strict_hot_date_returns_delayed_empty_hot_boards(app_client, db_session) -> None:
    _ensure_leaderboards_tables(db_session)
    db_session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 5, 7),
                is_open=True,
                pretrade_date=date(2026, 5, 6),
            ),
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 5, 8),
                is_open=True,
                pretrade_date=date(2026, 5, 7),
            ),
        ]
    )
    _seed_security_rows(db_session)
    _seed_equity_rows(db_session)
    _seed_dc_hot_rows(db_session, trade_day=date(2026, 5, 7))
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/leaderboards", params={"tradeDate": "2026-05-08", "debug": 1})
    assert response.status_code == 200
    payload = response.json()
    boards_by_key = {board["boardKey"]: board for board in payload["boards"]}

    assert boards_by_key["popularity"]["status"] == "DELAYED"
    assert boards_by_key["surge"]["status"] == "DELAYED"
    assert boards_by_key["popularity"]["rows"] == []
    assert boards_by_key["surge"]["rows"] == []
    assert payload["pageStatus"]["status"] == "PARTIAL"


def test_market_leaderboards_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/leaderboards", params={"market": "US"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"


def test_market_leaderboards_rejects_board_keys_query_param(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/leaderboards", params={"boardKeys": "gainers"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"


def test_market_leaderboards_dc_hot_filters_non_a_market_rows(app_client, db_session) -> None:
    _ensure_leaderboards_tables(db_session)
    trade_day = date(2026, 5, 8)
    db_session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 5, 7),
                is_open=True,
                pretrade_date=date(2026, 5, 6),
            ),
            TradeCalendar(
                exchange="SSE",
                trade_date=trade_day,
                is_open=True,
                pretrade_date=date(2026, 5, 7),
            ),
        ]
    )
    _seed_security_rows(db_session)
    _seed_equity_rows(db_session)
    db_session.add_all(
        [
            DcHot(
                trade_date=trade_day,
                data_type="A股市场",
                ts_code="000001.SZ",
                rank_time="15:00:00",
                query_market="A股市场",
                query_hot_type="人气榜",
                query_is_new="N",
                ts_name="平安银行",
                rank=1,
                pct_change=Decimal("5.0000"),
                current_price=Decimal("10.5000"),
                hot=Decimal("99.9000"),
            ),
            DcHot(
                trade_date=trade_day,
                data_type="A股市场",
                ts_code="000002.SZ",
                rank_time="15:00:00",
                query_market="A股市场",
                query_hot_type="人气榜",
                query_is_new="N",
                ts_name="万 科Ａ",
                rank=2,
                pct_change=Decimal("-4.0000"),
                current_price=Decimal("19.2000"),
                hot=Decimal("88.8000"),
            ),
            DcHot(
                trade_date=trade_day,
                data_type="港股市场",
                ts_code="900901.SH",
                rank_time="15:00:00",
                query_market="港股市场",
                query_hot_type="人气榜",
                query_is_new="N",
                ts_name="港股样本",
                rank=0,
                pct_change=Decimal("1.0000"),
                current_price=Decimal("3.2100"),
                hot=Decimal("77.7000"),
            ),
            DcHot(
                trade_date=trade_day,
                data_type="ETF基金",
                ts_code="000300.SH",
                rank_time="15:00:00",
                query_market="ETF基金",
                query_hot_type="人气榜",
                query_is_new="N",
                ts_name="沪深300",
                rank=0,
                pct_change=Decimal("0.5000"),
                current_price=Decimal("3726.8400"),
                hot=Decimal("66.6000"),
            ),
        ]
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/leaderboards", params={"tradeDate": "2026-05-08"})
    assert response.status_code == 200
    payload = response.json()
    boards_by_key = {board["boardKey"]: board for board in payload["boards"]}
    popularity_codes = [row["subject"]["subjectCode"] for row in boards_by_key["popularity"]["rows"]]

    assert popularity_codes == ["000001.SZ", "000002.SZ"]


def test_market_leaderboards_dc_hot_rank_time_sort_and_invalid_pruned(app_client, db_session) -> None:
    _ensure_leaderboards_tables(db_session)
    trade_day = date(2026, 5, 8)
    db_session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 5, 7),
                is_open=True,
                pretrade_date=date(2026, 5, 6),
            ),
            TradeCalendar(
                exchange="SSE",
                trade_date=trade_day,
                is_open=True,
                pretrade_date=date(2026, 5, 7),
            ),
        ]
    )
    _seed_security_rows(db_session)
    _seed_equity_rows(db_session)
    db_session.add_all(
        [
            DcHot(
                trade_date=trade_day,
                data_type="A股市场",
                ts_code="000001.SZ",
                rank_time="09:30:00",
                query_market="A股市场",
                query_hot_type="人气榜",
                query_is_new="N",
                ts_name="平安银行",
                rank=1,
                pct_change=Decimal("5.0000"),
                current_price=Decimal("10.5000"),
                hot=Decimal("99.9000"),
            ),
            DcHot(
                trade_date=trade_day,
                data_type="A股市场",
                ts_code="000002.SZ",
                rank_time="15:00:00",
                query_market="A股市场",
                query_hot_type="人气榜",
                query_is_new="N",
                ts_name="万 科Ａ",
                rank=1,
                pct_change=Decimal("-4.0000"),
                current_price=Decimal("19.2000"),
                hot=Decimal("88.8000"),
            ),
            DcHot(
                trade_date=trade_day,
                data_type="A股市场",
                ts_code="000003.SZ",
                rank_time="14:30:00",
                query_market="A股市场",
                query_hot_type="人气榜",
                query_is_new="N",
                ts_name="国农科技",
                rank=None,
                pct_change=Decimal("4.0000"),
                current_price=Decimal("5.2000"),
                hot=Decimal("77.7000"),
            ),
            DcHot(
                trade_date=trade_day,
                data_type="A股市场",
                ts_code="000005.SZ",
                rank_time="10:30:00",
                query_market="A股市场",
                query_hot_type="人气榜",
                query_is_new="N",
                ts_name="世纪星源",
                rank=None,
                pct_change=Decimal("1.0000"),
                current_price=Decimal("2.7000"),
                hot=Decimal("55.5000"),
            ),
            DcHot(
                trade_date=trade_day,
                data_type="A股市场",
                ts_code="000006.SZ",
                rank_time="",
                query_market="A股市场",
                query_hot_type="人气榜",
                query_is_new="N",
                ts_name="深振业A",
                rank=None,
                pct_change=Decimal("0.5000"),
                current_price=Decimal("7.1000"),
                hot=Decimal("44.4000"),
            ),
        ]
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/leaderboards", params={"tradeDate": "2026-05-08"})
    assert response.status_code == 200
    payload = response.json()
    boards_by_key = {board["boardKey"]: board for board in payload["boards"]}
    popularity_rows = boards_by_key["popularity"]["rows"]
    popularity_codes = [row["subject"]["subjectCode"] for row in popularity_rows]
    popularity_ranks = [row["rank"] for row in popularity_rows]

    assert popularity_codes == ["000002.SZ", "000001.SZ", "000003.SZ", "000005.SZ"]
    assert popularity_ranks == [1, 1, 3, 4]
    assert "000006.SZ" not in popularity_codes
