from __future__ import annotations

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.stock_search.stock_search_query import (
    StockSearchQuery,
)
from src.biz.schemas.wealth.market.stock_search import (
    StockSearchItemDto,
    StockSearchResponseDto,
)
from src.biz.services.wealth.market.stock_search import (
    DEFAULT_STOCK_SEARCH_LIMIT,
    StockSearchPolicy,
)


class StockSearchQueryService:
    def __init__(
        self,
        *,
        policy: StockSearchPolicy | None = None,
        query: StockSearchQuery | None = None,
    ) -> None:
        self._policy = policy or StockSearchPolicy()
        self._query = query or StockSearchQuery()

    def search(
        self,
        session: Session,
        *,
        keyword: str,
        limit: int = DEFAULT_STOCK_SEARCH_LIMIT,
    ) -> StockSearchResponseDto:
        request = self._policy.normalize(keyword=keyword, limit=limit)
        rows = self._query.search(
            session,
            keyword=request.keyword,
            escaped_prefix=request.escaped_prefix,
            limit=request.limit,
        )
        return StockSearchResponseDto(
            keyword=request.keyword,
            items=[
                StockSearchItemDto(tsCode=row.ts_code, name=row.name)
                for row in rows
            ],
        )
