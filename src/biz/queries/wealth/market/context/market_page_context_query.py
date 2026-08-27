from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, literal, select
from sqlalchemy.orm import Session, aliased

from src.foundation.models.core.trade_calendar import TradeCalendar


_CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
_SESSION_OPEN = time(hour=9, minute=30)
_SESSION_MORNING_CLOSE = time(hour=11, minute=30)
_SESSION_AFTERNOON_OPEN = time(hour=13, minute=0)
_SESSION_CLOSE = time(hour=15, minute=0)
_EOD_EXPECTED_SWITCH_HOUR = 20


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
    ) -> MarketPageContext:
        if market != "CN_A":
            raise ValueError(f"unsupported market: {market}")

        local_now = _now_cn()
        source = "explicit" if requested_trade_date is not None else "default"

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
        row = session.execute(
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
        ).one()

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
            source=source,
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
