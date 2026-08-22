from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.biz.queries.wealth.market.turnover_common.turnover_daily_average_query import (
    TurnoverDailyAverageQuery,
)
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _ensure_tables(db_session) -> None:
    bind = db_session.get_bind()
    TradeCalendar.__table__.create(bind, checkfirst=True)
    EquityDailyBar.__table__.create(bind, checkfirst=True)


def _seed_open_days(db_session, *, end_date: date, count: int = 20) -> list[date]:
    trade_dates = [end_date - timedelta(days=count - 1 - index) for index in range(count)]
    for index, trade_day in enumerate(trade_dates, start=1):
        db_session.add(
            TradeCalendar(
                exchange="SSE",
                trade_date=trade_day,
                is_open=True,
                pretrade_date=trade_dates[index - 2] if index > 1 else None,
            )
        )
        if index not in {2, 7}:
            db_session.add(
                EquityDailyBar(
                    ts_code="000001.SZ",
                    trade_date=trade_day,
                    open=Decimal("10"),
                    high=Decimal("10"),
                    low=Decimal("10"),
                    close=Decimal("10"),
                    pre_close=Decimal("10"),
                    change_amount=Decimal("0"),
                    pct_chg=Decimal("0"),
                    vol=Decimal("1"),
                    amount=Decimal(index * 100),
                    source="test",
                )
            )
    db_session.commit()
    return trade_dates


def test_daily_average_query_uses_two_bounded_queries_and_existing_values(db_session) -> None:
    _ensure_tables(db_session)
    end_date = date(2026, 8, 21)
    _seed_open_days(db_session, end_date=end_date)
    statements: list[str] = []

    def capture_select(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_select)
    try:
        result = TurnoverDailyAverageQuery().load(db_session, end_trade_date=end_date)
    finally:
        event.remove(bind, "before_cursor_execute", capture_select)

    assert len(statements) == 2
    assert result.end_trade_date == end_date
    assert result.available5d_count == 5
    assert result.available20d_count == 18
    assert result.avg5d_amount == Decimal("1800")
    assert result.avg20d_amount == Decimal("1116.666666666666666666666667")


def test_daily_average_query_returns_none_when_no_daily_amount_exists(db_session) -> None:
    _ensure_tables(db_session)
    end_date = date(2026, 8, 21)
    trade_dates = [end_date - timedelta(days=offset) for offset in range(4, -1, -1)]
    for index, trade_day in enumerate(trade_dates):
        db_session.add(
            TradeCalendar(
                exchange="SSE",
                trade_date=trade_day,
                is_open=True,
                pretrade_date=trade_dates[index - 1] if index else None,
            )
        )
    db_session.commit()

    result = TurnoverDailyAverageQuery().load(db_session, end_trade_date=end_date)

    assert result.available5d_count == 0
    assert result.available20d_count == 0
    assert result.avg5d_amount is None
    assert result.avg20d_amount is None
