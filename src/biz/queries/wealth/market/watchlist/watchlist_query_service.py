from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.stock_search.stock_search_query import (
    StockSearchQuery,
)
from src.biz.queries.wealth.market.watchlist.watchlist_group_query import (
    WatchlistGroupQuery,
    group_dto,
)
from src.biz.queries.wealth.market.watchlist.watchlist_item_query import (
    WatchlistItemQuery,
    WatchlistSortSpec,
)
from src.biz.schemas.wealth.market.context import MarketPageContextDto
from src.biz.schemas.wealth.market.watchlist import (
    WatchlistGroupRulesDto,
    WatchlistGroupsResponseDto,
    WatchlistPageResponseDto,
    WatchlistSearchItemDto,
    WatchlistSearchResponseDto,
    WatchlistStockGroupsResponseDto,
    WatchlistSummaryResponseDto,
)
from src.biz.services.wealth.market.stock_search import StockSearchPolicy
from src.biz.services.wealth.market.watchlist.watchlist_cursor import WatchlistCursor
from src.biz.services.wealth.market.watchlist.watchlist_field_mapper import (
    build_watchlist_item,
    build_watchlist_status,
)
from src.biz.services.wealth.market.watchlist.watchlist_policy import (
    DEFAULT_PAGE_SIZE,
    MAX_BATCH_MEMBERSHIPS,
    MAX_CUSTOM_GROUPS,
    MAX_GROUP_NAME_CHARS,
    MAX_GROUP_NAME_UTF8_BYTES,
    MAX_GROUPS,
    PALETTE,
    WatchlistPolicy,
)


class WatchlistQueryService:
    def __init__(self) -> None:
        self._groups = WatchlistGroupQuery()
        self._items = WatchlistItemQuery()
        self._policy = WatchlistPolicy()

    def get_groups(
        self, session: Session, *, user_id: int
    ) -> WatchlistGroupsResponseDto:
        return WatchlistGroupsResponseDto(
            groups=self._groups.list_groups(session, user_id=user_id),
            rules=WatchlistGroupRulesDto(
                maxGroups=MAX_GROUPS,
                maxCustomGroups=MAX_CUSTOM_GROUPS,
                nameMaxVisibleChars=MAX_GROUP_NAME_CHARS,
                nameMaxUtf8Bytes=MAX_GROUP_NAME_UTF8_BYTES,
                maxBatchMemberships=MAX_BATCH_MEMBERSHIPS,
                palette=list(PALETTE),
            ),
        )

    def get_page(
        self,
        session: Session,
        *,
        user_id: int,
        group_id: int,
        requested_trade_date: date | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
        sort_by: str | None = None,
        direction: str | None = None,
    ) -> WatchlistPageResponseDto:
        request = self._policy.normalize_page(
            limit=limit, sort_by=sort_by, direction=direction
        )
        group = self._groups.get_owned_group(
            session, user_id=user_id, group_id=group_id
        )
        total = self._groups.count_memberships(session, [group_id])[group_id]
        context = MarketPageContextQuery().resolve_context(
            session, market="CN_A", requested_trade_date=requested_trade_date
        )
        observed = (
            self._items.resolve_observed_trade_date(
                session, expected_trade_date=context.trade_date
            )
            if total
            else None
        )
        decoded = (
            WatchlistCursor.decode(
                cursor,
                group_id=group_id,
                sort_by=sort_by,
                direction=direction,
                observed=observed,
            )
            if cursor is not None
            else None
        )
        sort = WatchlistSortSpec(request.sort_by, request.direction)
        rows = (
            self._items.page(
                session,
                group_id=group_id,
                observed=observed,
                sort=sort,
                cursor=decoded,
                limit=request.limit,
            )
            if total
            else []
        )
        page = rows[: request.limit]
        marks = self._items.group_marks(
            session, user_id=user_id, ts_codes=[row["ts_code"] for row in page]
        )
        items = [
            build_watchlist_item(row, marks.get(row["ts_code"], [])) for row in page
        ]
        return WatchlistPageResponseDto(
            group=group_dto(group, total),
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
            nextCursor=sort.cursor(page[-1], group_id=group_id, observed=observed)
            if len(rows) > request.limit
            else None,
        )

    def get_summary(
        self, session: Session, *, user_id: int
    ) -> WatchlistSummaryResponseDto:
        group = self._groups.get_default_group(session, user_id=user_id)
        return WatchlistSummaryResponseDto(
            totalCount=self._groups.count_memberships(session, [group.id])[group.id]
        )

    def get_stock_groups(
        self, session: Session, *, user_id: int, ts_code: str
    ) -> WatchlistStockGroupsResponseDto:
        code = self._policy.normalize_ts_code(ts_code)
        groups = self._groups.list_stock_groups(session, user_id=user_id, ts_code=code)
        return WatchlistStockGroupsResponseDto(
            tsCode=code, isAdded=any(g.selected for g in groups), groups=groups
        )

    def search(
        self, session: Session, *, user_id: int, group_id: int, keyword: str, limit: int
    ) -> WatchlistSearchResponseDto:
        self._groups.get_owned_group(session, user_id=user_id, group_id=group_id)
        request = StockSearchPolicy().normalize(keyword=keyword, limit=limit)
        rows = StockSearchQuery().search(
            session,
            keyword=request.keyword,
            escaped_prefix=request.escaped_prefix,
            limit=request.limit,
        )
        added = self._items.load_added_codes(
            session, group_id=group_id, ts_codes=[row.ts_code for row in rows]
        )
        return WatchlistSearchResponseDto(
            groupId=group_id,
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
