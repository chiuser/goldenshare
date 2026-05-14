from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery


@dataclass(frozen=True, slots=True)
class NewsTradingDayContext:
    market: str
    expected_trade_date: date
    prev_trade_date: date | None
    is_trading_day: bool
    session_status: str
    as_of_time: datetime


class NewsStateQuery:
    """Resolve expected trading day context for market news panels."""

    def __init__(self) -> None:
        self._context_query = MarketPageContextQuery()

    def resolve_trading_day(
        self,
        session: Session,
        *,
        market: str,
        requested_trade_date: date | None,
    ) -> NewsTradingDayContext:
        context = self._context_query.resolve_context(
            session,
            market=market,
            requested_trade_date=requested_trade_date,
        )
        return NewsTradingDayContext(
            market=context.market,
            expected_trade_date=context.trade_date,
            prev_trade_date=context.prev_trade_date,
            is_trading_day=context.is_trading_day,
            session_status=context.session_status,
            as_of_time=context.generated_at,
        )
