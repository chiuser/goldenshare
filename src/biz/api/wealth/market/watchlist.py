from __future__ import annotations

from collections.abc import Callable
from datetime import date
import logging
import re
from typing import TypeVar

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_authenticated
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.watchlist.watchlist_query_service import (
    WatchlistQueryService,
)
from src.biz.schemas.wealth.market.watchlist import (
    WatchlistAddResponseDto,
    WatchlistMembershipResponseDto,
    WatchlistPageResponseDto,
    WatchlistRemoveResponseDto,
    WatchlistSearchResponseDto,
    WatchlistSummaryResponseDto,
)
from src.biz.services.wealth.market.stock_search import (
    DEFAULT_STOCK_SEARCH_LIMIT,
    StockSearchRequestError,
)
from src.biz.services.wealth.market.watchlist.watchlist_command_service import (
    WatchlistCommandService,
)
from src.biz.services.wealth.market.watchlist.watchlist_policy import (
    DEFAULT_WATCHLIST_PAGE_SIZE,
    WatchlistRequestError,
    WatchlistStockNotEligibleError,
)

router = APIRouter(prefix="/wealth/market/watchlist", tags=["wealth-market"])
logger = logging.getLogger(__name__)
ResponseT = TypeVar("ResponseT")


def _respond(operation: Callable[[], ResponseT], *, write: bool = False) -> ResponseT:
    try:
        return operation()
    except (WatchlistRequestError, StockSearchRequestError) as exc:
        raise WebAppError(
            status_code=400, code="WL_REQUEST_INVALID", message=str(exc)
        ) from exc
    except WatchlistStockNotEligibleError as exc:
        raise WebAppError(
            status_code=422, code="WL_STOCK_NOT_ELIGIBLE", message=str(exc)
        ) from exc
    except WebAppError:
        raise
    except Exception as exc:
        logger.exception("watchlist %s failed", "write" if write else "query")
        raise WebAppError(
            status_code=500,
            code="WL_WRITE_FAILED" if write else "WL_QUERY_FAILED",
            message="自选操作失败，请重试" if write else "自选数据暂不可用，请重试",
        ) from exc


def _integer(value: str, label: str) -> int:
    if not re.fullmatch(r"[0-9]{1,19}", value):
        raise WatchlistRequestError(f"{label}必须是有效正整数")
    return int(value)


def _trade_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError as exc:
        raise WatchlistRequestError("交易日期必须为有效的 YYYY-MM-DD 日期") from exc


@router.get("", response_model=WatchlistPageResponseDto)
def get_watchlist(
    limit: str = Query(str(DEFAULT_WATCHLIST_PAGE_SIZE)),
    after_id: str | None = Query(None, alias="afterId"),
    trade_date: str | None = Query(None, alias="tradeDate"),
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
) -> WatchlistPageResponseDto:
    return _respond(
        lambda: WatchlistQueryService().get_page(
            session,
            user_id=user.id,
            requested_trade_date=_trade_date(trade_date),
            limit=_integer(limit, "每批数量"),
            after_id=_integer(after_id, "分页游标") if after_id is not None else None,
        )
    )


@router.get("/summary", response_model=WatchlistSummaryResponseDto)
def get_watchlist_summary(
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
) -> WatchlistSummaryResponseDto:
    return _respond(
        lambda: WatchlistQueryService().get_summary(session, user_id=user.id)
    )


@router.get("/search", response_model=WatchlistSearchResponseDto)
def search_watchlist(
    keyword: str = Query(""),
    limit: str = Query(str(DEFAULT_STOCK_SEARCH_LIMIT)),
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
) -> WatchlistSearchResponseDto:
    return _respond(
        lambda: WatchlistQueryService().search(
            session, user_id=user.id, keyword=keyword, limit=_integer(limit, "搜索数量")
        )
    )


@router.get("/items/{ts_code}", response_model=WatchlistMembershipResponseDto)
def get_watchlist_membership(
    ts_code: str,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
) -> WatchlistMembershipResponseDto:
    return _respond(
        lambda: WatchlistQueryService().get_membership(
            session, user_id=user.id, ts_code=ts_code
        )
    )


@router.put("/items/{ts_code}", response_model=WatchlistAddResponseDto)
def add_watchlist_item(
    ts_code: str,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
) -> WatchlistAddResponseDto:
    return _respond(
        lambda: WatchlistCommandService().add(
            session, user_id=user.id, ts_code=ts_code
        ),
        write=True,
    )


@router.delete("/items/{ts_code}", response_model=WatchlistRemoveResponseDto)
def remove_watchlist_item(
    ts_code: str,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
) -> WatchlistRemoveResponseDto:
    return _respond(
        lambda: WatchlistCommandService().remove(
            session, user_id=user.id, ts_code=ts_code
        ),
        write=True,
    )
