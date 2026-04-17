from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.ops.queries.review_center_query_service import ReviewCenterQueryService
from src.ops.schemas.review_center import (
    ReviewActiveIndexListResponse,
    ReviewDcBoardListResponse,
    ReviewEquityBoardMembershipListResponse,
    ReviewEquitySuggestResponse,
    ReviewThsBoardListResponse,
)
from src.platform.auth.dependencies import require_admin
from src.platform.auth.domain import AuthenticatedUser
from src.platform.dependencies import get_db_session


router = APIRouter(tags=["ops"])


@router.get("/ops/review/index/active", response_model=ReviewActiveIndexListResponse)
def list_active_indexes(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    resource: str = Query("index_daily"),
    keyword: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> ReviewActiveIndexListResponse:
    return ReviewCenterQueryService().list_active_indexes(
        session,
        resource=resource,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


@router.get("/ops/review/board/ths", response_model=ReviewThsBoardListResponse)
def list_ths_boards(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    board_type: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    min_constituent_count: int = Query(0, ge=0),
    include_members: bool = Query(default=True),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=200),
) -> ReviewThsBoardListResponse:
    return ReviewCenterQueryService().list_ths_boards(
        session,
        board_type=board_type,
        keyword=keyword,
        min_constituent_count=min_constituent_count,
        include_members=include_members,
        page=page,
        page_size=page_size,
    )


@router.get("/ops/review/board/dc", response_model=ReviewDcBoardListResponse)
def list_dc_boards(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    trade_date: date | None = Query(default=None),
    idx_type: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    min_constituent_count: int = Query(0, ge=0),
    include_members: bool = Query(default=True),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=200),
) -> ReviewDcBoardListResponse:
    return ReviewCenterQueryService().list_dc_boards(
        session,
        trade_date=trade_date,
        idx_type=idx_type,
        keyword=keyword,
        min_constituent_count=min_constituent_count,
        include_members=include_members,
        page=page,
        page_size=page_size,
    )


@router.get("/ops/review/board/equity-membership", response_model=ReviewEquityBoardMembershipListResponse)
def list_equity_board_membership(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    trade_date: date | None = Query(default=None),
    keyword: str | None = Query(default=None),
    min_board_count: int = Query(0, ge=0),
    provider: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=200),
) -> ReviewEquityBoardMembershipListResponse:
    return ReviewCenterQueryService().list_equity_membership(
        session,
        trade_date=trade_date,
        keyword=keyword,
        min_board_count=min_board_count,
        provider=provider,
        page=page,
        page_size=page_size,
    )


@router.get("/ops/review/board/equity-suggest", response_model=ReviewEquitySuggestResponse)
def suggest_equities_for_review(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    keyword: str = Query(min_length=1),
    limit: int = Query(20, ge=1, le=50),
) -> ReviewEquitySuggestResponse:
    return ReviewCenterQueryService().suggest_equities(
        session,
        keyword=keyword,
        limit=limit,
    )
