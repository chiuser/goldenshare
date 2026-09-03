from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.stock_search.stock_search_query import (
    StockSearchQuery,
)
from src.biz.queries.wealth.market.watchlist.watchlist_query import WatchlistQuery
from src.biz.schemas.wealth.market.context import MarketPageContextDto
from src.biz.schemas.wealth.market.watchlist import (
    WatchlistMembershipResponseDto,
    WatchlistPageResponseDto,
    WatchlistSearchItemDto,
    WatchlistSearchResponseDto,
    WatchlistSummaryResponseDto,
)
from src.biz.services.wealth.market.stock_search import StockSearchPolicy
from src.biz.services.wealth.market.watchlist.watchlist_field_mapper import (
    build_watchlist_item,
    build_watchlist_status,
)
from src.biz.services.wealth.market.watchlist.watchlist_policy import (
    DEFAULT_WATCHLIST_PAGE_SIZE,
    WatchlistPolicy,
)


class WatchlistQueryService:
    def __init__(self) -> None:
        self._query = WatchlistQuery()
        self._policy = WatchlistPolicy()

    def get_page(
        self,
        session: Session,
        *,
        user_id: int,
        requested_trade_date: date | None = None,
        limit: int = DEFAULT_WATCHLIST_PAGE_SIZE,
        after_id: int | None = None,
    ) -> WatchlistPageResponseDto:
        request = self._policy.normalize_page(limit=limit, after_id=after_id)
        context = MarketPageContextQuery().resolve_context(
            session, market="CN_A", requested_trade_date=requested_trade_date
        )
        total = self._query.count(session, user_id=user_id)
        memberships = (
            self._query.list_memberships(
                session, user_id=user_id, limit=request.limit, after_id=request.after_id
            )
            if total
            else []
        )
        observed = (
            self._query.resolve_observed_trade_date(
                session, expected_trade_date=context.trade_date
            )
            if total
            else None
        )
        rows = self._query.load_snapshot(
            session,
            user_id=user_id,
            memberships=memberships[: request.limit],
            observed_trade_date=observed,
        )
        items = [build_watchlist_item(row) for row in rows]
        return WatchlistPageResponseDto(
            pageContext=MarketPageContextDto(
                market=context.market,
                tradeDate=context.trade_date,
                prevTradeDate=context.prev_trade_date,
                isTradingDay=context.is_trading_day,
                sessionStatus=context.session_status,
                timezone="Asia/Shanghai",
                generatedAt=context.generated_at,
                source=context.source,
            ),
            dataStatus=build_watchlist_status(
                total_count=total,
                items=items,
                expected_trade_date=context.trade_date,
                observed_trade_date=observed,
            ),
            items=items,
            totalCount=total,
            nextCursor=memberships[request.limit - 1].id
            if len(memberships) > request.limit
            else None,
        )

    def get_summary(
        self, session: Session, *, user_id: int
    ) -> WatchlistSummaryResponseDto:
        return WatchlistSummaryResponseDto(
            totalCount=self._query.count(session, user_id=user_id)
        )

    def get_membership(
        self, session: Session, *, user_id: int, ts_code: str
    ) -> WatchlistMembershipResponseDto:
        code = self._policy.normalize_ts_code(ts_code)
        return WatchlistMembershipResponseDto(
            tsCode=code,
            isAdded=self._query.contains(session, user_id=user_id, ts_code=code),
        )

    def search(
        self, session: Session, *, user_id: int, keyword: str, limit: int
    ) -> WatchlistSearchResponseDto:
        request = StockSearchPolicy().normalize(keyword=keyword, limit=limit)
        rows = StockSearchQuery().search(
            session,
            keyword=request.keyword,
            escaped_prefix=request.escaped_prefix,
            limit=request.limit,
        )
        added = self._query.load_added_codes(
            session, user_id=user_id, ts_codes=[row.ts_code for row in rows]
        )
        return WatchlistSearchResponseDto(
            keyword=request.keyword,
            items=[
                WatchlistSearchItemDto(
                    tsCode=row.ts_code,
                    name=row.name,
                    status="ADDED" if row.ts_code in added else "AVAILABLE",
                )
                for row in rows
            ],
        )
