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
    WatchlistAddToGroupsRequest,
    WatchlistBatchActionResponseDto,
    WatchlistGroupColorRequest,
    WatchlistGroupCreateRequest,
    WatchlistGroupDeleteResponseDto,
    WatchlistGroupMutationResponseDto,
    WatchlistGroupsResponseDto,
    WatchlistMoveRequest,
    WatchlistPageResponseDto,
    WatchlistSearchResponseDto,
    WatchlistSelectionRequest,
    WatchlistStockGroupsReplaceRequest,
    WatchlistStockGroupsReplaceResponseDto,
    WatchlistStockGroupsResponseDto,
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
    DEFAULT_PAGE_SIZE,
    WatchlistError,
    WatchlistPolicy,
    WatchlistRequestError,
)

router = APIRouter(prefix="/wealth/market/watchlist", tags=["wealth-market"])
logger = logging.getLogger(__name__)
ResponseT = TypeVar("ResponseT")
ERROR_STATUS = {
    "WL_REQUEST_INVALID": 400,
    "WL_CURSOR_INVALID": 400,
    "WL_GROUP_NOT_FOUND": 404,
    "WL_GROUP_NAME_CONFLICT": 409,
    "WL_GROUP_LIMIT_REACHED": 409,
    "WL_DEFAULT_GROUP_IMMUTABLE": 409,
    "WL_SELECTION_STALE": 409,
    "WL_TARGET_GROUP_INVALID": 422,
    "WL_MEMBERSHIP_REQUIRED": 422,
    "WL_STOCK_NOT_ELIGIBLE": 422,
    "WL_QUERY_FAILED": 500,
    "WL_WRITE_FAILED": 500,
    "WL_WRITE_OUTCOME_UNKNOWN": 503,
}


def _respond(
    operation: Callable[[], ResponseT],
    *,
    action: str,
    user_id: int,
    group_id: str | None = None,
    count: int = 0,
    write: bool = False,
) -> ResponseT:
    def log_failure(code: str, exc: Exception) -> None:
        logger.log(
            logging.ERROR if ERROR_STATUS[code] >= 500 else logging.WARNING,
            "watchlist operation rejected",
            extra={
                "code": code,
                "action": action,
                "userId": user_id,
                "groupId": group_id,
                "count": count,
                "exceptionType": type(exc.__cause__ or exc).__name__,
            },
        )

    try:
        return operation()
    except WatchlistError as exc:
        log_failure(exc.code, exc)
        raise WebAppError(
            status_code=ERROR_STATUS[exc.code], code=exc.code, message=str(exc)
        ) from exc
    except StockSearchRequestError as exc:
        log_failure("WL_REQUEST_INVALID", exc)
        raise WebAppError(
            status_code=400, code="WL_REQUEST_INVALID", message=str(exc)
        ) from exc
    except Exception as exc:
        log_failure("WL_WRITE_FAILED" if write else "WL_QUERY_FAILED", exc)
        raise WebAppError(
            status_code=500,
            code="WL_WRITE_FAILED" if write else "WL_QUERY_FAILED",
            message="自选操作失败，请重试" if write else "自选数据暂不可用，请重试",
        ) from exc


def _integer(value: str, label: str) -> int:
    if not re.fullmatch(r"[0-9]{1,19}", value):
        raise WatchlistRequestError(f"{label}必须是有效正整数")
    return WatchlistPolicy().api_id(int(value))


def _trade_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError as exc:
        raise WatchlistRequestError("交易日期必须为有效的 YYYY-MM-DD 日期") from exc


@router.get("/groups", response_model=WatchlistGroupsResponseDto)
def get_groups(
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistQueryService().get_groups(session, user_id=user.id),
        action="GET_GROUPS",
        user_id=user.id,
    )


@router.post("/groups", response_model=WatchlistGroupMutationResponseDto)
def create_group(
    body: WatchlistGroupCreateRequest,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistCommandService().create_group(
            session, user_id=user.id, name=body.name, color=body.color
        ),
        write=True,
        action="CREATE_GROUP",
        user_id=user.id,
        count=1,
    )


@router.patch(
    "/groups/{group_id}/color", response_model=WatchlistGroupMutationResponseDto
)
def change_group_color(
    group_id: str,
    body: WatchlistGroupColorRequest,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistCommandService().change_color(
            session,
            user_id=user.id,
            group_id=_integer(group_id, "分组"),
            color=body.color,
        ),
        write=True,
        action="CHANGE_COLOR",
        user_id=user.id,
        group_id=group_id,
    )


@router.delete("/groups/{group_id}", response_model=WatchlistGroupDeleteResponseDto)
def delete_group(
    group_id: str,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistCommandService().delete_group(
            session, user_id=user.id, group_id=_integer(group_id, "分组")
        ),
        write=True,
        action="DELETE_GROUP",
        user_id=user.id,
        group_id=group_id,
    )


@router.get("/groups/{group_id}/items", response_model=WatchlistPageResponseDto)
def get_group_items(
    group_id: str,
    limit: str = Query(str(DEFAULT_PAGE_SIZE)),
    cursor: str | None = Query(None),
    trade_date: str | None = Query(None, alias="tradeDate"),
    sort_by: str | None = Query(None, alias="sortBy"),
    direction: str | None = Query(None),
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistQueryService().get_page(
            session,
            user_id=user.id,
            group_id=_integer(group_id, "分组"),
            requested_trade_date=_trade_date(trade_date),
            limit=_integer(limit, "每批数量"),
            cursor=cursor,
            sort_by=sort_by,
            direction=direction,
        ),
        action="GET_ITEMS",
        user_id=user.id,
        group_id=group_id,
    )


@router.get("/groups/{group_id}/search", response_model=WatchlistSearchResponseDto)
def search_group(
    group_id: str,
    keyword: str = Query(""),
    limit: str = Query(str(DEFAULT_STOCK_SEARCH_LIMIT)),
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistQueryService().search(
            session,
            user_id=user.id,
            group_id=_integer(group_id, "分组"),
            keyword=keyword,
            limit=_integer(limit, "搜索数量"),
        ),
        action="SEARCH",
        user_id=user.id,
        group_id=group_id,
    )


@router.put(
    "/groups/{group_id}/items/{ts_code}", response_model=WatchlistAddResponseDto
)
def add_group_item(
    group_id: str,
    ts_code: str,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistCommandService().add_item(
            session,
            user_id=user.id,
            group_id=_integer(group_id, "分组"),
            ts_code=ts_code,
        ),
        write=True,
        action="ADD_ITEM",
        user_id=user.id,
        group_id=group_id,
        count=1,
    )


@router.post(
    "/groups/{group_id}/actions/move", response_model=WatchlistBatchActionResponseDto
)
def move_group_items(
    group_id: str,
    body: WatchlistMoveRequest,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistCommandService().batch(
            session,
            user_id=user.id,
            group_id=_integer(group_id, "分组"),
            action="MOVE",
            membership_ids=body.membershipIds,
            target_group_ids=[body.targetGroupId],
        ),
        write=True,
        action="MOVE",
        user_id=user.id,
        group_id=group_id,
        count=len(body.membershipIds),
    )


@router.post(
    "/groups/{group_id}/actions/add-to-groups",
    response_model=WatchlistBatchActionResponseDto,
)
def add_to_groups(
    group_id: str,
    body: WatchlistAddToGroupsRequest,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistCommandService().batch(
            session,
            user_id=user.id,
            group_id=_integer(group_id, "分组"),
            action="ADD_TO_GROUPS",
            membership_ids=body.membershipIds,
            target_group_ids=body.targetGroupIds,
        ),
        write=True,
        action="ADD_TO_GROUPS",
        user_id=user.id,
        group_id=group_id,
        count=len(body.membershipIds),
    )


@router.post(
    "/groups/{group_id}/actions/remove", response_model=WatchlistBatchActionResponseDto
)
def remove_group_items(
    group_id: str,
    body: WatchlistSelectionRequest,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistCommandService().batch(
            session,
            user_id=user.id,
            group_id=_integer(group_id, "分组"),
            action="REMOVE",
            membership_ids=body.membershipIds,
        ),
        write=True,
        action="REMOVE",
        user_id=user.id,
        group_id=group_id,
        count=len(body.membershipIds),
    )


@router.post(
    "/groups/{group_id}/actions/pin", response_model=WatchlistBatchActionResponseDto
)
def pin_group_items(
    group_id: str,
    body: WatchlistSelectionRequest,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistCommandService().batch(
            session,
            user_id=user.id,
            group_id=_integer(group_id, "分组"),
            action="PIN",
            membership_ids=body.membershipIds,
        ),
        write=True,
        action="PIN",
        user_id=user.id,
        group_id=group_id,
        count=len(body.membershipIds),
    )


@router.post(
    "/groups/{group_id}/actions/unpin", response_model=WatchlistBatchActionResponseDto
)
def unpin_group_items(
    group_id: str,
    body: WatchlistSelectionRequest,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistCommandService().batch(
            session,
            user_id=user.id,
            group_id=_integer(group_id, "分组"),
            action="UNPIN",
            membership_ids=body.membershipIds,
        ),
        write=True,
        action="UNPIN",
        user_id=user.id,
        group_id=group_id,
        count=len(body.membershipIds),
    )


@router.get("/stocks/{ts_code}/groups", response_model=WatchlistStockGroupsResponseDto)
def get_stock_groups(
    ts_code: str,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistQueryService().get_stock_groups(
            session, user_id=user.id, ts_code=ts_code
        ),
        action="GET_STOCK_GROUPS",
        user_id=user.id,
        count=1,
    )


@router.put(
    "/stocks/{ts_code}/groups", response_model=WatchlistStockGroupsReplaceResponseDto
)
def replace_stock_groups(
    ts_code: str,
    body: WatchlistStockGroupsReplaceRequest,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistCommandService().replace_stock_groups(
            session, user_id=user.id, ts_code=ts_code, group_ids=body.groupIds
        ),
        write=True,
        action="REPLACE_STOCK_GROUPS",
        user_id=user.id,
        count=len(body.groupIds),
    )


@router.get("/summary", response_model=WatchlistSummaryResponseDto)
def get_watchlist_summary(
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    return _respond(
        lambda: WatchlistQueryService().get_summary(session, user_id=user.id),
        action="SUMMARY",
        user_id=user.id,
    )
