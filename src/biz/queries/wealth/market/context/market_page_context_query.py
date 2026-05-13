from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar


_CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
_SESSION_OPEN = time(hour=9, minute=30)
_SESSION_MORNING_CLOSE = time(hour=11, minute=30)
_SESSION_AFTERNOON_OPEN = time(hour=13, minute=0)
_SESSION_CLOSE = time(hour=15, minute=0)
_EOD_EXPECTED_SWITCH_HOUR = 20


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

        local_now = datetime.now(_CN_TIMEZONE)
        source = "explicit" if requested_trade_date is not None else "default"
        resolved_trade_date = requested_trade_date or self._resolve_default_trade_date(session, local_now=local_now)
        trade_calendar_row = session.scalar(
            select(TradeCalendar).where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.trade_date == resolved_trade_date,
            )
        )
        if trade_calendar_row is not None:
            prev_trade_date = trade_calendar_row.pretrade_date
            is_trading_day = bool(trade_calendar_row.is_open)
        else:
            prev_trade_date = session.scalar(
                select(func.max(TradeCalendar.trade_date)).where(
                    TradeCalendar.exchange == "SSE",
                    TradeCalendar.is_open.is_(True),
                    TradeCalendar.trade_date < resolved_trade_date,
                )
            )
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

    def _resolve_default_trade_date(self, session: Session, *, local_now: datetime) -> date:
        latest_open = session.scalar(
            select(func.max(TradeCalendar.trade_date)).where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= local_now.date(),
            )
        )
        if latest_open is None:
            return local_now.date()

        if local_now.hour >= _EOD_EXPECTED_SWITCH_HOUR:
            return latest_open

        current_day_open = session.scalar(
            select(TradeCalendar.is_open).where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.trade_date == local_now.date(),
            )
        )
        if current_day_open:
            prev_open = session.scalar(
                select(func.max(TradeCalendar.trade_date)).where(
                    TradeCalendar.exchange == "SSE",
                    TradeCalendar.is_open.is_(True),
                    TradeCalendar.trade_date < local_now.date(),
                )
            )
            if prev_open is not None:
                return prev_open
        return latest_open
