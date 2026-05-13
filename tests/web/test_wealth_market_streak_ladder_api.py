from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.foundation.models.core.equity_limit_list import EquityLimitList
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


def _ensure_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [TradeCalendar.__table__, EquityLimitList.__table__, EquityDailyBar.__table__]:
        table.create(bind, checkfirst=True)


def _add_calendar_row(db_session, *, trade_date: date, prev_trade_date: date | None) -> None:
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=trade_date,
            is_open=True,
            pretrade_date=prev_trade_date,
        )
    )


def _add_limit_up_row(
    db_session,
    *,
    trade_date: date,
    ts_code: str,
    board_count: int | None,
    close: Decimal | None,
    pct_chg: Decimal | None,
    fd_amount: Decimal | None = Decimal("127000000"),
    open_times: int | None = 0,
    first_time: str | None = None,
    industry: str | None = "机器人",
    name: str | None = None,
) -> None:
    db_session.add(
        EquityLimitList(
            ts_code=ts_code,
            trade_date=trade_date,
            limit_type="U",
            industry=industry,
            name=name or ts_code,
            close=close,
            pct_chg=pct_chg,
            amount=None,
            limit_amount=None,
            float_mv=None,
            total_mv=None,
            turnover_ratio=None,
            fd_amount=fd_amount,
            first_time=first_time,
            last_time=None,
            open_times=open_times,
            up_stat=None,
            limit_times=board_count,
        )
    )


def _add_daily_bar_row(
    db_session,
    *,
    trade_date: date,
    ts_code: str,
    close: Decimal | None,
    pct_chg: Decimal | None,
) -> None:
    db_session.add(
        EquityDailyBar(
            ts_code=ts_code,
            trade_date=trade_date,
            open=None,
            high=None,
            low=None,
            close=close,
            pre_close=None,
            change_amount=None,
            pct_chg=pct_chg,
            vol=None,
            amount=None,
            source="tushare",
        )
    )


def test_streak_ladder_ready_with_promotions(app_client, db_session) -> None:
    _ensure_tables(db_session)
    today = date(2026, 4, 28)
    prev = date(2026, 4, 27)
    pre_prev = date(2026, 4, 26)
    _add_calendar_row(db_session, trade_date=pre_prev, prev_trade_date=None)
    _add_calendar_row(db_session, trade_date=prev, prev_trade_date=pre_prev)
    _add_calendar_row(db_session, trade_date=today, prev_trade_date=prev)

    # today rows
    _add_limit_up_row(db_session, trade_date=today, ts_code="A.SZ", board_count=6, close=Decimal("10.00"), pct_chg=Decimal("10.00"))
    _add_limit_up_row(db_session, trade_date=today, ts_code="B.SZ", board_count=5, close=Decimal("9.00"), pct_chg=Decimal("9.00"))
    _add_limit_up_row(db_session, trade_date=today, ts_code="C.SZ", board_count=4, close=Decimal("8.00"), pct_chg=Decimal("8.00"))
    _add_limit_up_row(db_session, trade_date=today, ts_code="D.SZ", board_count=2, close=Decimal("7.00"), pct_chg=Decimal("7.00"))
    _add_limit_up_row(db_session, trade_date=today, ts_code="E.SZ", board_count=1, close=Decimal("6.00"), pct_chg=Decimal("6.00"))

    # previous rows
    _add_limit_up_row(db_session, trade_date=prev, ts_code="B.SZ", board_count=4, close=Decimal("8.90"), pct_chg=Decimal("3.00"))
    _add_limit_up_row(db_session, trade_date=prev, ts_code="C.SZ", board_count=3, close=Decimal("7.90"), pct_chg=Decimal("2.00"))
    _add_limit_up_row(db_session, trade_date=prev, ts_code="X.SZ", board_count=3, close=Decimal("7.10"), pct_chg=Decimal("1.00"))
    _add_limit_up_row(db_session, trade_date=prev, ts_code="D.SZ", board_count=1, close=Decimal("6.90"), pct_chg=Decimal("1.50"))
    _add_limit_up_row(db_session, trade_date=prev, ts_code="Y.SZ", board_count=1, close=Decimal("5.50"), pct_chg=Decimal("0.80"))
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/streak-ladder",
        params={"tradeDate": "2026-04-28", "debug": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pageStatus"]["status"] == "READY"
    ladder = payload["streakLadderV5"]
    assert ladder["highestStreakLevel"] == 6
    assert [item["stockCode"] for item in ladder["aboveFive"]] == ["A.SZ"]
    assert ladder["aboveFive"][0]["limitAmount"] == 127000000.0
    assert ladder["aboveFive"][0]["limitAmountDisplayText"] == "1.27亿"
    assert ladder["aboveFive"][0]["limitAmountLabel"] == "封单金额"
    assert ladder["aboveFive"][0]["streakText"] == "6板"
    assert [item["stockCode"] for item in ladder["firstBoard"]] == ["E.SZ"]
    assert ladder["firstBoard"][0]["streakText"] == "首板"

    promotion_4 = ladder["promotions"]["4"]
    previous_codes = [item["stockCode"] for item in promotion_4["previousStocks"]]
    assert previous_codes == ["C.SZ", "X.SZ"]
    x_row = next(item for item in promotion_4["previousStocks"] if item["stockCode"] == "X.SZ")
    assert x_row["advanced"] is False
    assert x_row["currentStreakLevel"] == 0
    assert x_row["streakText"] == "昨日三板"
    current_codes = [item["stockCode"] for item in promotion_4["currentStocks"]]
    assert current_codes == ["C.SZ"]
    assert promotion_4["currentStocks"][0]["streakText"] == "4连板"


def test_streak_ladder_delayed_status(app_client, db_session) -> None:
    _ensure_tables(db_session)
    trade_day = date(2026, 4, 28)
    _add_calendar_row(db_session, trade_date=date(2026, 4, 27), prev_trade_date=date(2026, 4, 26))
    _add_calendar_row(db_session, trade_date=trade_day, prev_trade_date=date(2026, 4, 27))
    _add_limit_up_row(
        db_session,
        trade_date=trade_day,
        ts_code="A.SZ",
        board_count=2,
        close=Decimal("8.88"),
        pct_chg=Decimal("10.00"),
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/streak-ladder",
        params={"tradeDate": "2026-04-29", "debug": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pageStatus"]["status"] == "PARTIAL"
    assert payload["debugInfo"]["modules"][0]["status"] == "DELAYED"
    assert payload["debugInfo"]["exceptions"][0]["code"] == "SL_SOURCE_DELAYED"


def test_streak_ladder_partial_on_invalid_board_count(app_client, db_session) -> None:
    _ensure_tables(db_session)
    trade_day = date(2026, 4, 28)
    prev_day = date(2026, 4, 27)
    _add_calendar_row(db_session, trade_date=prev_day, prev_trade_date=date(2026, 4, 26))
    _add_calendar_row(db_session, trade_date=trade_day, prev_trade_date=prev_day)
    _add_limit_up_row(
        db_session,
        trade_date=trade_day,
        ts_code="A.SZ",
        board_count=2,
        close=Decimal("8.88"),
        pct_chg=Decimal("10.00"),
    )
    _add_limit_up_row(
        db_session,
        trade_date=trade_day,
        ts_code="BROKEN.SZ",
        board_count=None,
        close=Decimal("6.66"),
        pct_chg=Decimal("3.33"),
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/streak-ladder",
        params={"tradeDate": "2026-04-28", "debug": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pageStatus"]["status"] == "PARTIAL"
    codes = {item["code"] for item in payload["debugInfo"]["exceptions"]}
    assert "SL_INVALID_BOARD_COUNT" in codes


def test_streak_ladder_drops_invalid_price_metrics_when_fallback_still_invalid(app_client, db_session) -> None:
    _ensure_tables(db_session)
    trade_day = date(2026, 4, 28)
    prev_day = date(2026, 4, 27)
    _add_calendar_row(db_session, trade_date=prev_day, prev_trade_date=date(2026, 4, 26))
    _add_calendar_row(db_session, trade_date=trade_day, prev_trade_date=prev_day)
    _add_limit_up_row(
        db_session,
        trade_date=trade_day,
        ts_code="GOOD.SZ",
        board_count=1,
        close=Decimal("9.99"),
        pct_chg=Decimal("10.00"),
    )
    _add_limit_up_row(
        db_session,
        trade_date=trade_day,
        ts_code="DIRTY.SZ",
        board_count=1,
        close=Decimal("0"),
        pct_chg=Decimal("-100"),
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/streak-ladder",
        params={"tradeDate": "2026-04-28", "debug": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    first_board_codes = [item["stockCode"] for item in payload["streakLadderV5"]["firstBoard"]]
    assert first_board_codes == ["GOOD.SZ"]


def test_streak_ladder_uses_daily_bar_fallback_for_invalid_source_metrics(app_client, db_session) -> None:
    _ensure_tables(db_session)
    trade_day = date(2026, 4, 28)
    prev_day = date(2026, 4, 27)
    _add_calendar_row(db_session, trade_date=prev_day, prev_trade_date=date(2026, 4, 26))
    _add_calendar_row(db_session, trade_date=trade_day, prev_trade_date=prev_day)
    _add_limit_up_row(
        db_session,
        trade_date=trade_day,
        ts_code="DIRTY.SZ",
        board_count=1,
        close=Decimal("0"),
        pct_chg=Decimal("-100"),
    )
    _add_daily_bar_row(
        db_session,
        trade_date=trade_day,
        ts_code="DIRTY.SZ",
        close=Decimal("12.34"),
        pct_chg=Decimal("10.01"),
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/streak-ladder",
        params={"tradeDate": "2026-04-28", "debug": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    first_board = payload["streakLadderV5"]["firstBoard"]
    assert len(first_board) == 1
    assert first_board[0]["stockCode"] == "DIRTY.SZ"
    assert first_board[0]["latestPrice"] == 12.34
    assert first_board[0]["changePct"] == 10.01


def test_streak_ladder_marks_partial_when_limit_amount_missing(app_client, db_session) -> None:
    _ensure_tables(db_session)
    trade_day = date(2026, 4, 28)
    prev_day = date(2026, 4, 27)
    _add_calendar_row(db_session, trade_date=prev_day, prev_trade_date=date(2026, 4, 26))
    _add_calendar_row(db_session, trade_date=trade_day, prev_trade_date=prev_day)
    _add_limit_up_row(
        db_session,
        trade_date=trade_day,
        ts_code="MISS.SZ",
        board_count=1,
        close=Decimal("9.99"),
        pct_chg=Decimal("10.00"),
        fd_amount=None,
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/streak-ladder",
        params={"tradeDate": "2026-04-28", "debug": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pageStatus"]["status"] == "PARTIAL"
    first_board = payload["streakLadderV5"]["firstBoard"]
    assert first_board[0]["limitAmount"] is None
    assert first_board[0]["limitAmountDisplayText"] == "--"
    assert first_board[0]["limitAmountLabel"] == "封单金额"
    assert "SL_JOIN_METRIC_MISSING" in {item["code"] for item in payload["debugInfo"]["exceptions"]}
