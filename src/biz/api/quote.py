from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.biz.queries.quote_query_service import (
    SUPPORTED_ADJUSTMENTS,
    SUPPORTED_PERIODS,
    UNSUPPORTED_MINUTE_PERIODS,
    QuoteQueryService,
)
from src.biz.schemas.quote import (
    QuoteAnnouncementsResponse,
    QuoteKlineResponse,
    QuotePageInitResponse,
    QuoteRelatedInfoResponse,
)
from src.platform.auth.dependencies import require_quote_access
from src.platform.auth.domain import AuthenticatedUser
from src.platform.dependencies import get_db_session
from src.platform.exceptions import WebAppError


router = APIRouter(prefix="/quote", tags=["quote"])


@router.get("/detail/page-init", response_model=QuotePageInitResponse)
def get_quote_detail_page_init(
    ts_code: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    market: str | None = Query(default=None),
    security_type: str | None = Query(default=None),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> QuotePageInitResponse:
    query_service = QuoteQueryService()
    try:
        instrument = query_service.resolve_instrument(
            session,
            ts_code=ts_code,
            symbol=symbol,
            market=market,
            security_type=security_type,
        )
    except ValueError as exc:
        raise WebAppError(status_code=400, code="INVALID_SYMBOL", message=str(exc)) from exc
    return query_service.build_page_init(session, instrument=instrument)


@router.get("/detail/kline", response_model=QuoteKlineResponse)
def get_quote_detail_kline(
    ts_code: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    market: str | None = Query(default=None),
    security_type: str | None = Query(default=None),
    period: str = Query(...),
    adjustment: str = Query(default="forward"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(default=300, ge=1, le=2000),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> QuoteKlineResponse:
    normalized_period = period.strip().lower()
    normalized_adjustment = adjustment.strip().lower()
    if normalized_period in UNSUPPORTED_MINUTE_PERIODS:
        raise WebAppError(
            status_code=501,
            code="UNSUPPORTED_PERIOD",
            message="当前数据基座尚未提供分钟级行情，请使用日/周/月周期",
        )
    if normalized_period not in SUPPORTED_PERIODS:
        raise WebAppError(status_code=400, code="UNSUPPORTED_PERIOD", message=f"不支持的周期：{period}")
    if normalized_adjustment not in SUPPORTED_ADJUSTMENTS:
        raise WebAppError(status_code=400, code="INVALID_ADJUSTMENT", message=f"不支持的复权类型：{adjustment}")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise WebAppError(status_code=400, code="INVALID_DATE_RANGE", message="起始日期不能晚于结束日期")

    query_service = QuoteQueryService()
    try:
        instrument = query_service.resolve_instrument(
            session,
            ts_code=ts_code,
            symbol=symbol,
            market=market,
            security_type=security_type,
        )
    except ValueError as exc:
        raise WebAppError(status_code=400, code="INVALID_SYMBOL", message=str(exc)) from exc

    if instrument.security_type in {"index", "etf"} and normalized_adjustment != "none":
        raise WebAppError(
            status_code=400,
            code="UNSUPPORTED_ADJUSTMENT",
            message="指数和 ETF 暂不支持复权参数，请使用 adjustment=none",
        )

    try:
        return query_service.build_kline(
            session,
            instrument=instrument,
            period=normalized_period,
            adjustment=normalized_adjustment,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    except ValueError as exc:
        raise WebAppError(status_code=400, code="INVALID_ARGUMENT", message=str(exc)) from exc


@router.get("/detail/related-info", response_model=QuoteRelatedInfoResponse)
def get_quote_detail_related_info(
    ts_code: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    market: str | None = Query(default=None),
    security_type: str | None = Query(default=None),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> QuoteRelatedInfoResponse:
    query_service = QuoteQueryService()
    try:
        instrument = query_service.resolve_instrument(
            session,
            ts_code=ts_code,
            symbol=symbol,
            market=market,
            security_type=security_type,
        )
    except ValueError as exc:
        raise WebAppError(status_code=400, code="INVALID_SYMBOL", message=str(exc)) from exc
    return query_service.build_related_info(session, instrument=instrument)


@router.get("/detail/announcements", response_model=QuoteAnnouncementsResponse)
def get_quote_detail_announcements(
    _user: AuthenticatedUser | None = Depends(require_quote_access),
) -> QuoteAnnouncementsResponse:
    return QuoteQueryService().build_announcements_placeholder()
