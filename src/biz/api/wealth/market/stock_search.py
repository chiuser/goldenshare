from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.stock_search.stock_search_query_service import (
    StockSearchQueryService,
)
from src.biz.schemas.wealth.market.stock_search import StockSearchResponseDto
from src.biz.services.wealth.market.stock_search import (
    DEFAULT_STOCK_SEARCH_LIMIT,
    StockSearchRequestError,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/wealth/market", tags=["wealth-market"])


@router.get("/stock-search", response_model=StockSearchResponseDto)
def get_stock_search(
    keyword: str = Query(...),
    limit: int = Query(DEFAULT_STOCK_SEARCH_LIMIT),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> StockSearchResponseDto:
    try:
        return StockSearchQueryService().search(
            session,
            keyword=keyword,
            limit=limit,
        )
    except StockSearchRequestError as exc:
        raise WebAppError(
            status_code=400,
            code="SS_REQUEST_INVALID",
            message=str(exc),
        ) from exc
    except WebAppError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("stock search query failed")
        raise WebAppError(
            status_code=500,
            code="SS_QUERY_FAILED",
            message="股票搜索暂不可用",
        ) from exc
