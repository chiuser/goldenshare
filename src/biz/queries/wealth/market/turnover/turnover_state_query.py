from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.raw.raw_stk_mins import RawStkMins


_CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
_SESSION_OPEN = time(hour=9, minute=30)
_SESSION_MORNING_CLOSE = time(hour=11, minute=30)
_SESSION_AFTERNOON_OPEN = time(hour=13, minute=0)
_SESSION_CLOSE = time(hour=15, minute=0)
_EOD_EXPECTED_SWITCH_HOUR = 20


@dataclass(frozen=True, slots=True)
class TurnoverTradingDayContext:
    market: str
    expected_trade_date: date
    prev_trade_date: date | None
    is_trading_day: bool
    session_status: str
    as_of_time: datetime


@dataclass(frozen=True, slots=True)
class TurnoverSourceState:
    daily_source_date: date | None
    intraday_source_date: date | None

    @property
    def observed_trade_date(self) -> date | None:
        if self.daily_source_date is not None:
            return self.daily_source_date
        return self.intraday_source_date


class TurnoverStateQuery:
    """Resolve expected trading day context and source observed dates."""

    def resolve_trading_day(
        self,
        session: Session,
        *,
        market: str,
        requested_trade_date: date | None,
    ) -> TurnoverTradingDayContext:
        if market != "CN_A":
            raise ValueError(f"unsupported market: {market}")

        local_now = datetime.now(_CN_TIMEZONE)
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

        session_status = self._resolve_session_status(local_now=local_now, is_trading_day=is_trading_day)
        return TurnoverTradingDayContext(
            market=market,
            expected_trade_date=resolved_trade_date,
            prev_trade_date=prev_trade_date,
            is_trading_day=is_trading_day,
            session_status=session_status,
            as_of_time=local_now,
        )

    def load_source_state(self, session: Session) -> TurnoverSourceState:
        daily_source_date = session.scalar(select(func.max(EquityDailyBar.trade_date)))
        intraday_trade_time = session.scalar(
            select(func.max(RawStkMins.trade_time)).where(RawStkMins.freq == 30)
        )
        intraday_source_date = intraday_trade_time.date() if intraday_trade_time is not None else None
        return TurnoverSourceState(
            daily_source_date=daily_source_date,
            intraday_source_date=intraday_source_date,
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
