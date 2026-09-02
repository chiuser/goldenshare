from __future__ import annotations

# FastAPI dependency declarations intentionally use Query/Depends in signatures.
# ruff: noqa: B008
import gc
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from threading import Lock

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.app.web.logging import get_web_logger
from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.index_turnover_insight.index_turnover_insight_calculator import (
    IndexTurnoverInsightCalculator,
)
from src.biz.queries.wealth.market.index_turnover_insight.index_turnover_insight_calendar_query import (
    IndexTurnoverInsightCalendarQuery,
)
from src.biz.queries.wealth.market.index_turnover_insight.index_turnover_insight_query_service import (
    IndexTurnoverInsightQueryService,
)
from src.biz.schemas.wealth.market.index_turnover_insight import (
    IndexTurnoverInsightResponseDto,
)
from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_exception_builder import (
    IndexTurnoverInsightExceptionBuilder,
)
from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_status_resolver import (
    IndexTurnoverInsightStatusResolver,
)
from src.foundation.clients.local_lake.major_index_turnover_reader import (
    MajorIndexTurnoverLakeReader,
)
from src.foundation.config.local_minute_capability import (
    LocalMinuteCapabilityError,
    resolve_index_minute_capability,
)
from src.foundation.config.settings import get_settings


router = APIRouter(prefix="/wealth/market", tags=["wealth-market"])
_DEBUG_ENVIRONMENTS = frozenset({"local", "dev", "test"})
_ALLOWED_QUERY_PARAMS = frozenset({"market", "tradeDate", "debug"})
_RESPONSE_BUILD_LOCK = Lock()


@contextmanager
def _bounded_response_build() -> Iterator[None]:
    # This local-only endpoint creates 57,840 short-lived immutable row objects.
    # Their lifetime is acyclic and bounded, so ref-counting is sufficient while
    # the response is built; pausing cyclic GC removes non-deterministic P95 spikes.
    with _RESPONSE_BUILD_LOCK:
        gc_was_enabled = gc.isenabled()
        if gc_was_enabled:
            gc.disable()
        try:
            yield
        finally:
            if gc_was_enabled:
                gc.enable()


def _service() -> IndexTurnoverInsightQueryService:
    try:
        capability = resolve_index_minute_capability(get_settings())
    except LocalMinuteCapabilityError as exc:
        raise WebAppError(status_code=503, code=exc.code, message=exc.message) from exc
    if not capability.enabled or capability.lake_root is None:
        raise WebAppError(
            status_code=503,
            code="ITI_SOURCE_NOT_READY",
            message="本地指数成交额分钟能力未启用。",
        )
    return IndexTurnoverInsightQueryService(
        context_query=MarketPageContextQuery(),
        calendar_query=IndexTurnoverInsightCalendarQuery(),
        reader=MajorIndexTurnoverLakeReader(capability.lake_root),
        calculator=IndexTurnoverInsightCalculator(),
        status_resolver=IndexTurnoverInsightStatusResolver(),
        exception_builder=IndexTurnoverInsightExceptionBuilder(),
    )


@router.get(
    "/turnover-insight/indices",
    response_model=IndexTurnoverInsightResponseDto,
)
def get_index_turnover_insight(
    request: Request,
    market: str = Query(default="CN_A"),
    trade_date: date | None = Query(default=None, alias="tradeDate"),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> Response:
    _validate_query_shape(request)
    normalized_market = market.strip().upper()
    if normalized_market != "CN_A":
        raise WebAppError(
            status_code=400,
            code="400001",
            message=f"不支持的市场：{market}",
        )
    effective_debug = (
        debug == 1
        and get_settings().app_env.strip().lower() in _DEBUG_ENVIRONMENTS
    )
    try:
        with _bounded_response_build():
            response = _service().build_index_turnover_insight(
                session,
                market=normalized_market,
                trade_date=trade_date,
                debug=True,
            )
            debug_info = response.debugInfo
            if not effective_debug:
                response = response.model_copy(update={"debugInfo": None})
            content = response.model_dump_json()
        get_web_logger().info(
            "request_id=%s feature=index_turnover_insight observed_date=%s "
            "status=%s scanned_file_count=%s scanned_row_count=%s",
            getattr(request.state, "request_id", None),
            response.tradingDay.observedTradeDate,
            response.status,
            debug_info.scannedFileCount if debug_info is not None else 0,
            debug_info.scannedRowCount if debug_info is not None else 0,
        )
        return Response(
            content=content,
            media_type="application/json",
        )
    except WebAppError:
        raise
    except ValueError as exc:
        raise WebAppError(
            status_code=400,
            code="400001",
            message=str(exc),
        ) from exc


def _validate_query_shape(request: Request) -> None:
    supplied = [key for key, _value in request.query_params.multi_items()]
    unknown = sorted(set(supplied).difference(_ALLOWED_QUERY_PARAMS))
    if unknown:
        raise WebAppError(
            status_code=400,
            code="400001",
            message=f"不支持的查询参数：{', '.join(unknown)}",
        )
    duplicated = sorted(key for key in set(supplied) if supplied.count(key) > 1)
    if duplicated:
        raise WebAppError(
            status_code=400,
            code="400001",
            message=f"查询参数不能重复：{', '.join(duplicated)}",
        )
