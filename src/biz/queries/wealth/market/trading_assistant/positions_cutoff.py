"""Stable server business phase and confirmed calendar, never a client clock."""
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsUnavailable
from src.biz.services.wealth.market.trading_assistant.valuation_clock import valuation_cutoff


@dataclass(frozen=True, slots=True)
class PositionsCutoff:
    today: date
    through: datetime
    valuation_date: date | None
    is_open: bool | None
    reason: str | None


def resolve_positions_cutoff(session, *, market, deadline) -> PositionsCutoff:
    now = session.scalar(select(func.clock_timestamp())).astimezone(ZoneInfo("Asia/Shanghai"))
    midnight = datetime.combine(now.date(), time(), now.tzinfo)
    try:
        day = market.read_calendar(session, "SSE", now.date(), now.date(), deadline).days[0]
    except MarketFactsUnavailable:
        return PositionsCutoff(now.date(), midnight, None, None, "交易日历暂不可用，不能确认可卖数量与估值日期")
    if day.is_open and now.time() >= time(15):
        through = valuation_cutoff(now.date(), is_open=True, observed_at=now)
        return PositionsCutoff(now.date(), through, now.date(), True, None)
    # A civil-day boundary is retained even when the last close was Friday.
    # It invalidates yesterday's daily-profit context without inventing prices.
    return PositionsCutoff(now.date(), midnight, day.previous_trade_date, day.is_open,
                           None if day.previous_trade_date else "交易日历缺少上一交易日")
