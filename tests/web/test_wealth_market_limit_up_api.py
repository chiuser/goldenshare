from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from src.foundation.models.core.equity_stock_st import EquityStockSt
from src.foundation.models.core.limit_cpt_list import LimitCptList
from src.foundation.models.core.limit_list_ths import LimitListThs
from src.foundation.models.core.limit_step import LimitStep
from src.foundation.models.core.ths_member import ThsMember
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


def _ensure_limit_up_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [
        TradeCalendar.__table__,
        LimitListThs.__table__,
        EquityStockSt.__table__,
        LimitStep.__table__,
        LimitCptList.__table__,
        ThsMember.__table__,
        EquityDailyBar.__table__,
    ]:
        table.create(bind, checkfirst=True)


def _add_limit_row(
    db_session,
    *,
    trade_day: date,
    ts_code: str,
    limit_type: str | None,
    query_limit_type: str,
    name: str,
    lu_desc: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    price: Decimal | None = None,
    pct_chg: Decimal | None = None,
    open_num: int | None = None,
    first_lu_time: str | None = None,
    limit_amount: Decimal | None = None,
) -> None:
    db_session.add(
        LimitListThs(
            trade_date=trade_day,
            ts_code=ts_code,
            query_limit_type=query_limit_type,
            query_market="A股市场",
            limit_type=limit_type,
            name=name,
            lu_desc=lu_desc,
            tag=tag,
            status=status,
            price=price,
            pct_chg=pct_chg,
            open_num=open_num,
            first_lu_time=first_lu_time,
            limit_amount=limit_amount,
        )
    )


def _seed_trade_calendar_and_history_rows(db_session, *, target_date: date, days: int = 62) -> None:
    trade_dates = [target_date - timedelta(days=days - 1 - index) for index in range(days)]
    prev_day = None
    for idx, trade_day in enumerate(trade_dates):
        db_session.add(
            TradeCalendar(
                exchange="SSE",
                trade_date=trade_day,
                is_open=True,
                pretrade_date=prev_day,
            )
        )
        prev_day = trade_day
        if trade_day == target_date:
            continue
        _add_limit_row(
            db_session,
            trade_day=trade_day,
            ts_code=f"HUP{idx:04d}.SZ",
            limit_type="涨停池",
            query_limit_type="涨停池",
            name=f"历史涨停{idx:04d}",
            price=Decimal("10.0000"),
            pct_chg=Decimal("9.9900"),
        )
        _add_limit_row(
            db_session,
            trade_day=trade_day,
            ts_code=f"HDN{idx:04d}.SZ",
            limit_type="跌停池",
            query_limit_type="跌停池",
            name=f"历史跌停{idx:04d}",
            price=Decimal("8.0000"),
            pct_chg=Decimal("-9.9800"),
        )


def _seed_limit_up_full_case(db_session, *, target_date: date) -> None:
    _seed_trade_calendar_and_history_rows(db_session, target_date=target_date, days=62)
    prev_day = target_date - timedelta(days=1)

    _add_limit_row(
        db_session,
        trade_day=target_date,
        ts_code="000001.SZ",
        limit_type="涨停池",
        query_limit_type="涨停池",
        name="非ST涨停A",
        price=Decimal("10.5000"),
        pct_chg=Decimal("10.0200"),
        open_num=0,
        first_lu_time="09:35:00",
        limit_amount=Decimal("580000000.0000"),
    )
    _add_limit_row(
        db_session,
        trade_day=target_date,
        ts_code="000002.SZ",
        limit_type="涨停池",
        query_limit_type="涨停池",
        name="ST涨停B",
        price=Decimal("5.2000"),
        pct_chg=Decimal("5.0100"),
        open_num=1,
        first_lu_time="10:10:00",
        limit_amount=Decimal("80000000.0000"),
    )
    _add_limit_row(
        db_session,
        trade_day=target_date,
        ts_code="000003.SZ",
        limit_type="跌停池",
        query_limit_type="跌停池",
        name="非ST跌停C",
        price=Decimal("7.1000"),
        pct_chg=Decimal("-10.0100"),
    )
    _add_limit_row(
        db_session,
        trade_day=target_date,
        ts_code="000004.SZ",
        limit_type="跌停池",
        query_limit_type="跌停池",
        name="ST跌停D",
        price=Decimal("4.8000"),
        pct_chg=Decimal("-5.0000"),
    )
    _add_limit_row(
        db_session,
        trade_day=target_date,
        ts_code="000005.SZ",
        limit_type="炸板池",
        query_limit_type="炸板池",
        name="非ST炸板E",
        price=Decimal("12.3000"),
        pct_chg=Decimal("3.2200"),
    )
    _add_limit_row(
        db_session,
        trade_day=target_date,
        ts_code="000006.SZ",
        limit_type="炸板池",
        query_limit_type="炸板池",
        name="ST炸板F",
        price=Decimal("3.5000"),
        pct_chg=Decimal("-1.1200"),
    )
    _add_limit_row(
        db_session,
        trade_day=target_date,
        ts_code="000007.SZ",
        limit_type="观察池",
        query_limit_type="观察池",
        name="天地板样本",
        lu_desc="天地板",
    )
    _add_limit_row(
        db_session,
        trade_day=target_date,
        ts_code="000008.SZ",
        limit_type="观察池",
        query_limit_type="观察池",
        name="地天板样本",
        lu_desc="地天板",
    )
    _add_limit_row(
        db_session,
        trade_day=target_date,
        ts_code="000009.SZ",
        limit_type="观察池",
        query_limit_type="观察池",
        name="天地天板样本",
        lu_desc="天地天板",
    )
    _add_limit_row(
        db_session,
        trade_day=target_date,
        ts_code="000010.SZ",
        limit_type="观察池",
        query_limit_type="观察池",
        name="昨日地天板描述",
        lu_desc="昨日地天板",
    )

    db_session.add_all(
        [
            EquityStockSt(ts_code="000002.SZ", trade_date=target_date, type="ST", name="ST涨停B", type_name="ST"),
            EquityStockSt(ts_code="000004.SZ", trade_date=target_date, type="ST", name="ST跌停D", type_name="ST"),
            EquityStockSt(ts_code="000006.SZ", trade_date=target_date, type="ST", name="ST炸板F", type_name="ST"),
        ]
    )

    db_session.add_all(
        [
            LimitStep(ts_code="000001.SZ", trade_date=target_date, nums="3", name="非ST涨停A"),
            LimitStep(ts_code="000002.SZ", trade_date=target_date, nums="6", name="ST涨停B"),
            LimitStep(ts_code="000011.SZ", trade_date=target_date, nums="2", name="板块成分G"),
            LimitStep(ts_code="000012.SZ", trade_date=target_date, nums="1", name="板块成分H"),
            LimitStep(ts_code="000013.SZ", trade_date=target_date, nums="5", name="板块成分I"),
        ]
    )

    db_session.add_all(
        [
            LimitCptList(ts_code="885699.TI", trade_date=target_date, name="ST板块", up_nums=99, rank="1"),
            LimitCptList(ts_code="BK1001", trade_date=target_date, name="机器人", up_nums=12, rank="2"),
            LimitCptList(ts_code="BK1002", trade_date=target_date, name="固态电池", up_nums=8, rank="3"),
            LimitCptList(ts_code="BK1003", trade_date=target_date, name="低空经济", up_nums=6, rank="4"),
            LimitCptList(ts_code="BK1004", trade_date=target_date, name="算力设备", up_nums=5, rank="5"),
            LimitCptList(ts_code="BK1005", trade_date=target_date, name="军工电子", up_nums=4, rank="6"),
            LimitCptList(ts_code="BK2001", trade_date=prev_day, name="前一日板块A", up_nums=10, rank="1"),
            LimitCptList(ts_code="BK2002", trade_date=prev_day, name="前一日板块B", up_nums=7, rank="2"),
        ]
    )

    db_session.add_all(
        [
            ThsMember(ts_code="BK1001", con_code="000001.SZ", con_name="非ST涨停A", in_date=target_date - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK1001", con_code="000011.SZ", con_name="板块成分G", in_date=target_date - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK1001", con_code="000012.SZ", con_name="板块成分H", in_date=target_date - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK1002", con_code="000013.SZ", con_name="板块成分I", in_date=target_date - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK1002", con_code="000014.SZ", con_name="板块成分J", in_date=target_date - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK1002", con_code="000015.SZ", con_name="板块成分K", in_date=target_date - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK1003", con_code="000016.SZ", con_name="板块成分L", in_date=target_date - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK1004", con_code="000017.SZ", con_name="板块成分M", in_date=target_date - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK1005", con_code="000018.SZ", con_name="板块成分N", in_date=target_date - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK2001", con_code="000021.SZ", con_name="前一日成分A", in_date=prev_day - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK2001", con_code="000022.SZ", con_name="前一日成分B", in_date=prev_day - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK2001", con_code="000023.SZ", con_name="前一日成分C", in_date=prev_day - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK2002", con_code="000024.SZ", con_name="前一日成分D", in_date=prev_day - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK2002", con_code="000025.SZ", con_name="前一日成分E", in_date=prev_day - timedelta(days=20), out_date=None),
            ThsMember(ts_code="BK2002", con_code="000026.SZ", con_name="前一日成分F", in_date=prev_day - timedelta(days=20), out_date=None),
        ]
    )

    db_session.add_all(
        [
            EquityDailyBar(
                ts_code="000011.SZ",
                trade_date=target_date,
                open=Decimal("8.0000"),
                high=Decimal("8.5000"),
                low=Decimal("7.9000"),
                close=Decimal("8.3000"),
                pre_close=Decimal("8.0000"),
                change_amount=Decimal("0.3000"),
                pct_chg=Decimal("3.7500"),
                vol=Decimal("1200000.0000"),
                amount=Decimal("93000000.0000"),
                source="tushare",
            ),
            EquityDailyBar(
                ts_code="000012.SZ",
                trade_date=target_date,
                open=Decimal("6.0000"),
                high=Decimal("6.3000"),
                low=Decimal("5.9000"),
                close=Decimal("6.1000"),
                pre_close=Decimal("6.0000"),
                change_amount=Decimal("0.1000"),
                pct_chg=Decimal("1.6700"),
                vol=Decimal("1100000.0000"),
                amount=Decimal("68000000.0000"),
                source="tushare",
            ),
        ]
    )

    for trade_day in [target_date, prev_day]:
        _add_limit_row(
            db_session,
            trade_day=trade_day,
            ts_code="000013.SZ",
            limit_type="涨停池",
            query_limit_type=f"涨停池-{trade_day.isoformat()}",
            name="板块成分I",
            price=Decimal("9.1000"),
            pct_chg=Decimal("10.0000"),
            open_num=0,
            first_lu_time="09:40:00",
            limit_amount=Decimal("110000000.0000"),
        )

    db_session.commit()


def test_limit_up_summary_ready(app_client, db_session) -> None:
    _ensure_limit_up_tables(db_session)
    target_date = date(2026, 4, 28)
    _seed_limit_up_full_case(db_session, target_date=target_date)

    response = app_client.get("/api/v1/wealth/market/limit-up/summary", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["tradingDay"]["tradeDate"] == "2026-04-28"
    assert payload["pageStatus"]["status"] == "READY"
    summary_cards = {item["key"]: item for item in payload["limitUp"]["summaryCards"]}
    assert summary_cards["limitUpCount"]["value"] == "3/1"
    assert summary_cards["limitDownCount"]["value"] == "2/1"
    assert summary_cards["brokenLimitCount"]["value"] == "2/1"
    assert summary_cards["sealingRate"]["value"] == 66.7
    assert summary_cards["skyToFloorCount"]["value"] == 2
    assert summary_cards["floorToSkyCount"]["value"] == 2

    sectors = payload["limitUp"]["todayStructure"]["sectors"]
    assert len(sectors) == 5
    assert all(item["sectorCode"] != "885699.TI" for item in sectors)
    first_sector_code = payload["limitUp"]["todayStructure"]["selectedSectorCode"]
    assert first_sector_code == sectors[0]["sectorCode"]
    assert len(payload["limitUp"]["todayStructure"]["leaderStocks"][first_sector_code]) == 3
    assert all(
        not row["stockName"].startswith("ST")
        for row in payload["limitUp"]["todayStructure"]["leaderStocks"][first_sector_code]
        if row["stockName"]
    )
    assert len(payload["limitUp"]["historyPoints"]["oneMonth"]) == 22
    assert len(payload["limitUp"]["historyPoints"]["threeMonth"]) == 62
    assert payload["debugInfo"]["modules"][0]["moduleKey"] == "limitUp"

    no_debug_response = app_client.get("/api/v1/wealth/market/limit-up/summary", params={"tradeDate": "2026-04-28"})
    assert no_debug_response.status_code == 200
    no_debug_payload = no_debug_response.json()
    assert "debugInfo" not in no_debug_payload or no_debug_payload["debugInfo"] is None


def test_limit_up_summary_partial_mapping_missing(app_client, db_session) -> None:
    _ensure_limit_up_tables(db_session)
    target_date = date(2026, 4, 28)
    _seed_trade_calendar_and_history_rows(db_session, target_date=target_date, days=62)
    _add_limit_row(
        db_session,
        trade_day=target_date,
        ts_code="000101.SZ",
        limit_type="涨停池",
        query_limit_type="涨停池",
        name="样本A",
        price=Decimal("10.0000"),
        pct_chg=Decimal("9.9900"),
    )
    _add_limit_row(
        db_session,
        trade_day=target_date,
        ts_code="000102.SZ",
        limit_type="跌停池",
        query_limit_type="跌停池",
        name="样本B",
        price=Decimal("8.0000"),
        pct_chg=Decimal("-9.9800"),
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/limit-up/summary", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["pageStatus"]["status"] == "PARTIAL"
    assert payload["limitUp"]["todayStructure"]["sectors"] == []
    exception_codes = {item["code"] for item in payload["debugInfo"]["exceptions"]}
    assert "LU_DISTRIBUTION_MAPPING_MISSING" in exception_codes


def test_limit_up_summary_delayed(app_client, db_session) -> None:
    _ensure_limit_up_tables(db_session)
    db_session.add_all(
        [
            TradeCalendar(exchange="SSE", trade_date=date(2026, 4, 27), is_open=True, pretrade_date=date(2026, 4, 26)),
            TradeCalendar(exchange="SSE", trade_date=date(2026, 4, 28), is_open=True, pretrade_date=date(2026, 4, 27)),
        ]
    )
    _add_limit_row(
        db_session,
        trade_day=date(2026, 4, 27),
        ts_code="000201.SZ",
        limit_type="涨停池",
        query_limit_type="涨停池",
        name="延迟样本A",
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/limit-up/summary", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["pageStatus"]["status"] == "PARTIAL"
    assert payload["debugInfo"]["modules"][0]["status"] == "DELAYED"
    exception_codes = {item["code"] for item in payload["debugInfo"]["exceptions"]}
    assert "LU_SOURCE_DELAYED" in exception_codes


def test_limit_up_summary_rule_st_exclusion(app_client, db_session) -> None:
    _ensure_limit_up_tables(db_session)
    target_date = date(2026, 4, 28)
    _seed_limit_up_full_case(db_session, target_date=target_date)

    response = app_client.get("/api/v1/wealth/market/limit-up/summary", params={"tradeDate": "2026-04-28"})
    assert response.status_code == 200
    payload = response.json()
    cards = {item["key"]: item for item in payload["limitUp"]["summaryCards"]}
    assert cards["limitUpCount"]["value"] == "3/1"
    assert cards["limitDownCount"]["value"] == "2/1"
    assert cards["brokenLimitCount"]["value"] == "2/1"
    assert cards["sealingRate"]["value"] == 66.7


def test_limit_up_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/limit-up/summary", params={"market": "US"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"
