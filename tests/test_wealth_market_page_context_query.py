from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.biz.queries.wealth.market.context.market_page_context_query as context_query_module
from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery
from src.foundation.models.core.trade_calendar import TradeCalendar


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


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
        TradeCalendar.__table__.create(connection)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _calendar_row(
    trade_date: date,
    *,
    is_open: bool,
    pretrade_date: date | None,
) -> TradeCalendar:
    return TradeCalendar(
        exchange="SSE",
        trade_date=trade_date,
        is_open=is_open,
        pretrade_date=pretrade_date,
    )


def _resolve_with_statement_count(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    *,
    local_now: datetime,
    requested_trade_date: date | None,
):
    now_call_count = 0

    def fixed_now() -> datetime:
        nonlocal now_call_count
        now_call_count += 1
        return local_now

    monkeypatch.setattr(context_query_module, "_now_cn", fixed_now)
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        result = MarketPageContextQuery().resolve_context(
            db_session,
            market="CN_A",
            requested_trade_date=requested_trade_date,
        )
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    assert len(statements) == 1
    assert statements[0].lstrip().upper().startswith(("SELECT", "WITH"))
    assert now_call_count == 1
    return result


def _seed_standard_calendar(db_session: Session) -> None:
    db_session.add_all(
        [
            _calendar_row(date(2026, 8, 25), is_open=True, pretrade_date=date(2026, 8, 24)),
            _calendar_row(date(2026, 8, 26), is_open=True, pretrade_date=date(2026, 8, 25)),
            _calendar_row(date(2026, 8, 27), is_open=True, pretrade_date=date(2026, 8, 26)),
            _calendar_row(date(2026, 8, 28), is_open=True, pretrade_date=date(2026, 8, 27)),
            _calendar_row(date(2026, 8, 29), is_open=False, pretrade_date=date(2026, 8, 28)),
        ]
    )
    db_session.commit()


def test_default_before_20_uses_previous_open_day_in_one_statement(db_session, monkeypatch) -> None:
    _seed_standard_calendar(db_session)
    local_now = datetime(2026, 8, 27, 19, 59, tzinfo=CN_TIMEZONE)

    result = _resolve_with_statement_count(
        db_session,
        monkeypatch,
        local_now=local_now,
        requested_trade_date=None,
    )

    assert result.trade_date == date(2026, 8, 26)
    assert result.prev_trade_date == date(2026, 8, 25)
    assert result.is_trading_day is True
    assert result.session_status == "CLOSED"
    assert result.generated_at == local_now
    assert result.source == "default"


def test_default_at_20_uses_latest_open_day_in_one_statement(db_session, monkeypatch) -> None:
    _seed_standard_calendar(db_session)
    local_now = datetime(2026, 8, 27, 20, 0, tzinfo=CN_TIMEZONE)

    result = _resolve_with_statement_count(
        db_session,
        monkeypatch,
        local_now=local_now,
        requested_trade_date=None,
    )

    assert result.trade_date == date(2026, 8, 27)
    assert result.prev_trade_date == date(2026, 8, 26)
    assert result.is_trading_day is True
    assert result.session_status == "CLOSED"


def test_default_weekend_keeps_latest_open_day_semantics(db_session, monkeypatch) -> None:
    _seed_standard_calendar(db_session)
    local_now = datetime(2026, 8, 29, 10, 0, tzinfo=CN_TIMEZONE)

    result = _resolve_with_statement_count(
        db_session,
        monkeypatch,
        local_now=local_now,
        requested_trade_date=None,
    )

    assert result.trade_date == date(2026, 8, 28)
    assert result.prev_trade_date == date(2026, 8, 27)
    assert result.is_trading_day is True
    assert result.session_status == "TRADING"


def test_default_holiday_keeps_latest_open_day_semantics(db_session, monkeypatch) -> None:
    db_session.add_all(
        [
            _calendar_row(date(2026, 9, 30), is_open=True, pretrade_date=date(2026, 9, 29)),
            _calendar_row(date(2026, 10, 1), is_open=False, pretrade_date=date(2026, 9, 30)),
        ]
    )
    db_session.commit()
    local_now = datetime(2026, 10, 1, 10, 0, tzinfo=CN_TIMEZONE)

    result = _resolve_with_statement_count(
        db_session,
        monkeypatch,
        local_now=local_now,
        requested_trade_date=None,
    )

    assert result.trade_date == date(2026, 9, 30)
    assert result.prev_trade_date == date(2026, 9, 29)
    assert result.is_trading_day is True
    assert result.session_status == "TRADING"


@pytest.mark.parametrize(
    ("requested_trade_date", "expected_is_open", "expected_previous"),
    [
        (date(2026, 8, 27), True, date(2026, 8, 26)),
        (date(2026, 8, 29), False, date(2026, 8, 28)),
        (date(2026, 8, 30), False, date(2026, 8, 28)),
    ],
)
def test_explicit_open_closed_and_missing_dates_keep_existing_semantics(
    db_session,
    monkeypatch,
    requested_trade_date,
    expected_is_open,
    expected_previous,
) -> None:
    _seed_standard_calendar(db_session)
    local_now = datetime(2026, 8, 30, 10, 0, tzinfo=CN_TIMEZONE)

    result = _resolve_with_statement_count(
        db_session,
        monkeypatch,
        local_now=local_now,
        requested_trade_date=requested_trade_date,
    )

    assert result.trade_date == requested_trade_date
    assert result.prev_trade_date == expected_previous
    assert result.is_trading_day is expected_is_open
    assert result.session_status == ("TRADING" if expected_is_open else "CLOSED")
    assert result.source == "explicit"


def test_default_empty_calendar_returns_local_date_without_fabricating_history(db_session, monkeypatch) -> None:
    local_now = datetime(2026, 8, 27, 10, 0, tzinfo=CN_TIMEZONE)

    result = _resolve_with_statement_count(
        db_session,
        monkeypatch,
        local_now=local_now,
        requested_trade_date=None,
    )

    assert result.trade_date == date(2026, 8, 27)
    assert result.prev_trade_date is None
    assert result.is_trading_day is False
    assert result.session_status == "CLOSED"


def test_default_without_open_days_still_uses_local_calendar_row(db_session, monkeypatch) -> None:
    db_session.add(
        _calendar_row(date(2026, 8, 27), is_open=False, pretrade_date=date(2026, 8, 26))
    )
    db_session.commit()
    local_now = datetime(2026, 8, 27, 10, 0, tzinfo=CN_TIMEZONE)

    result = _resolve_with_statement_count(
        db_session,
        monkeypatch,
        local_now=local_now,
        requested_trade_date=None,
    )

    assert result.trade_date == date(2026, 8, 27)
    assert result.prev_trade_date == date(2026, 8, 26)
    assert result.is_trading_day is False


def test_default_before_20_keeps_today_when_no_previous_open_day(db_session, monkeypatch) -> None:
    db_session.add(_calendar_row(date(2026, 8, 27), is_open=True, pretrade_date=None))
    db_session.commit()
    local_now = datetime(2026, 8, 27, 19, 59, tzinfo=CN_TIMEZONE)

    result = _resolve_with_statement_count(
        db_session,
        monkeypatch,
        local_now=local_now,
        requested_trade_date=None,
    )

    assert result.trade_date == date(2026, 8, 27)
    assert result.prev_trade_date is None
    assert result.is_trading_day is True


def test_unsupported_market_fails_before_any_statement(db_session) -> None:
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        with pytest.raises(ValueError, match="unsupported market: US"):
            MarketPageContextQuery().resolve_context(
                db_session,
                market="US",
                requested_trade_date=None,
            )
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    assert statements == []
