from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, literal, select, true
from sqlalchemy.orm import Session, aliased

from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader
from src.foundation.models.core.trade_calendar import TradeCalendar


_CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
_SESSION_OPEN = time(hour=9, minute=30)
_SESSION_MORNING_CLOSE = time(hour=11, minute=30)
_SESSION_AFTERNOON_OPEN = time(hour=13, minute=0)
_SESSION_CLOSE = time(hour=15, minute=0)
_EOD_EXPECTED_SWITCH_HOUR = 20
CalendarRow = tuple[date, bool, date | None]


def _now_cn() -> datetime:
    return datetime.now(_CN_TIMEZONE)


@dataclass(frozen=True, slots=True)
class MarketPageContext:
    market: str
    trade_date: date
    prev_trade_date: date | None
    is_trading_day: bool
    session_status: str
    generated_at: datetime
    source: str


class MarketPageContextQuery:
    """Resolve the page-level trading date anchor for wealth market pages."""

    def resolve_context(
        self,
        session: Session,
        *,
        market: str,
        requested_trade_date: date | None,
        now: datetime | None = None,
    ) -> MarketPageContext:
        if market != "CN_A":
            raise ValueError(f"unsupported market: {market}")

        local_now = (now or _now_cn()).astimezone(_CN_TIMEZONE)
        row = session.execute(self._context_statement(requested_trade_date, local_now)).one()
        return self._context_from_row(row, market, requested_trade_date, local_now)

    def resolve_sse_kline_context(
        self, session: Session, *, requested_trade_date: date | None, start: date, limit: int,
    ) -> tuple[MarketPageContext, tuple[CalendarRow, ...]]:
        local_now = _now_cn()
        anchor = self._context_statement(requested_trade_date, local_now).cte("sse_kline_context")
        expected_end = case(
            (anchor.c.calendar_is_open.is_(True), anchor.c.resolved_trade_date),
            (anchor.c.calendar_trade_date.is_not(None), anchor.c.calendar_pretrade_date),
            else_=anchor.c.previous_open_fallback,
        )
        window = (
            select(TradeCalendar.trade_date.label("window_date"), TradeCalendar.pretrade_date.label("window_prev"))
            .select_from(TradeCalendar).join(anchor, true())
            .where(TradeCalendar.exchange == "SSE", TradeCalendar.is_open.is_(True),
                   TradeCalendar.trade_date.between(start, expected_end))
            .order_by(TradeCalendar.trade_date.desc()).limit(limit).cte("sse_kline_window")
        )
        rows = session.execute(
            select(*anchor.c, *window.c).select_from(anchor.outerjoin(window, true()))
            .order_by(window.c.window_date)
        ).all()
        context = self._context_from_row(rows[0], "CN_A", requested_trade_date, local_now)
        return context, tuple((row.window_date, True, row.window_prev) for row in rows if row.window_date is not None)

    @staticmethod
    def load_sse_preceding_dates(session: Session, *, before: date, start: date, limit: int) -> tuple[date, ...]:
        dates = session.scalars(
            select(TradeCalendar.trade_date)
            .where(TradeCalendar.exchange == "SSE", TradeCalendar.is_open.is_(True),
                   TradeCalendar.trade_date >= start, TradeCalendar.trade_date < before)
            .order_by(TradeCalendar.trade_date.desc()).limit(limit)
        ).all()
        return tuple(reversed(dates))

    @staticmethod
    def _context_statement(requested_trade_date: date | None, local_now: datetime):

        latest_open_date = (
            select(func.max(TradeCalendar.trade_date))
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= local_now.date(),
            )
            .scalar_subquery()
        )
        today_is_open = (
            select(TradeCalendar.is_open)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.trade_date == local_now.date(),
            )
            .scalar_subquery()
        )
        previous_open_before_today = (
            select(func.max(TradeCalendar.trade_date))
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date < local_now.date(),
            )
            .scalar_subquery()
        )
        calendar_facts = select(
            latest_open_date.label("latest_open_date"),
            today_is_open.label("today_is_open"),
            previous_open_before_today.label("previous_open_before_today"),
        ).cte("market_calendar_facts")

        if requested_trade_date is not None:
            resolved_trade_date_expression = literal(requested_trade_date)
        else:
            resolved_trade_date_expression = case(
                (
                    and_(
                        literal(local_now.hour < _EOD_EXPECTED_SWITCH_HOUR).is_(True),
                        calendar_facts.c.today_is_open.is_(True),
                        calendar_facts.c.previous_open_before_today.is_not(None),
                    ),
                    calendar_facts.c.previous_open_before_today,
                ),
                else_=func.coalesce(calendar_facts.c.latest_open_date, literal(local_now.date())),
            )
        resolved_anchor = (
            select(resolved_trade_date_expression.label("resolved_trade_date"))
            .select_from(calendar_facts)
            .cte("resolved_market_date")
        )

        resolved_calendar = aliased(TradeCalendar)
        previous_open_fallback = (
            select(func.max(TradeCalendar.trade_date))
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date < resolved_anchor.c.resolved_trade_date,
            )
            .correlate(resolved_anchor)
            .scalar_subquery()
        )
        return (
            select(
                resolved_anchor.c.resolved_trade_date,
                resolved_calendar.trade_date.label("calendar_trade_date"),
                resolved_calendar.is_open.label("calendar_is_open"),
                resolved_calendar.pretrade_date.label("calendar_pretrade_date"),
                previous_open_fallback.label("previous_open_fallback"),
            )
            .select_from(resolved_anchor)
            .outerjoin(
                resolved_calendar,
                and_(
                    resolved_calendar.exchange == "SSE",
                    resolved_calendar.trade_date == resolved_anchor.c.resolved_trade_date,
                ),
            )
        )

    def _context_from_row(self, row, market: str, requested_trade_date: date | None, local_now: datetime):
        resolved_trade_date = row.resolved_trade_date
        if row.calendar_trade_date is not None:
            prev_trade_date = row.calendar_pretrade_date
            is_trading_day = bool(row.calendar_is_open)
        else:
            prev_trade_date = row.previous_open_fallback
            is_trading_day = False

        return MarketPageContext(
            market=market,
            trade_date=resolved_trade_date,
            prev_trade_date=prev_trade_date,
            is_trading_day=is_trading_day,
            session_status=self._resolve_session_status(local_now=local_now, is_trading_day=is_trading_day),
            generated_at=local_now,
            source="explicit" if requested_trade_date is not None else "default",
        )

    def resolve_local_context(
        self,
        reader: IndexDailyLakeReader,
        *,
        market: str,
        requested_trade_date: date | None,
        now: datetime | None = None,
        calendar_rows: tuple[CalendarRow, ...] | None = None,
    ) -> MarketPageContext:
        if market != "CN_A":
            raise ValueError(f"unsupported market: {market}")
        local_now = (now or _now_cn()).astimezone(_CN_TIMEZONE)
        today = local_now.date()
        if calendar_rows is None:
            calendar_rows = reader.calendar_rows(end=requested_trade_date or today, recent_open_days=2)
        resolved = requested_trade_date
        if resolved is None:
            before_switch = local_now.hour < _EOD_EXPECTED_SWITCH_HOUR
            latest_open = next((day for day, opened, _ in reversed(calendar_rows)
                                if opened and day <= today and (day != today or not before_switch)), None)
            if latest_open is None:
                # The bounded window can start on today's first recorded open date.
                latest_open = next((day for day, opened, _ in reversed(calendar_rows) if opened and day <= today), None)
            resolved = latest_open or today
        selected = next((row for row in reversed(calendar_rows) if row[0] == resolved), None)
        if selected is None:
            prev_trade_date = next((day for day, opened, _ in reversed(calendar_rows) if opened and day < resolved), None)
            is_trading_day = False
        else:
            _, is_trading_day, prev_trade_date = selected
        return MarketPageContext(
            market=market,
            trade_date=resolved,
            prev_trade_date=prev_trade_date,
            is_trading_day=is_trading_day,
            session_status=self._resolve_session_status(local_now=local_now, is_trading_day=is_trading_day),
            generated_at=local_now,
            source="explicit" if requested_trade_date is not None else "default",
        )

    @staticmethod
    def _resolve_session_status(*, local_now: datetime, is_trading_day: bool) -> str:
        if not is_trading_day:
            return "CLOSED"

        current_time = local_now.timetz().replace(tzinfo=None)
        if current_time < _SESSION_OPEN:
            return "PRE_OPEN"
        if _SESSION_OPEN <= current_time < _SESSION_MORNING_CLOSE:
            return "TRADING"
        if _SESSION_MORNING_CLOSE <= current_time < _SESSION_AFTERNOON_OPEN:
            return "BREAK"
        if _SESSION_AFTERNOON_OPEN <= current_time < _SESSION_CLOSE:
            return "TRADING"
        return "CLOSED"
