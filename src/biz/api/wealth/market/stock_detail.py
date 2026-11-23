from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.stock_detail.stock_detail_query_service import (
    StockDetailNotFoundError,
    StockDetailQueryService,
)
from src.biz.schemas.wealth.market.stock_detail import (
    LocalStockDetailFirstKlineResponseDto,
    LocalStockDetailPagedKlineResponseDto,
    LocalStockDetailPageInitResponseDto,
    StockDetailKlineResponseDto,
    StockDetailPageInitResponseDto,
    StockDetailPeriodKlineResponseDto,
)
from src.biz.api.wealth.market.stock_detail_dependencies import (
    StockDailyKlineBackend, get_stock_daily_kline_backend,
)
from src.biz.services.wealth.market.stock_detail.stock_daily_kline_contracts import StockDailyKlineRequest
from src.foundation.clients.reference_data import ReferenceDataReadError


def _stock_period_capabilities(request: Request):
    runtime = getattr(request.app.state, "technical_indicator_runtime", None)
    if runtime is None:
        return ()
    config = runtime.config
    return tuple(period for period in ("week", "month")
                 if "qfq" in config.enabled_adjustments(config.market_dataset_id("stock", period)))


def get_stock_detail_page_init(
    request: Request,
    ts_code: str = Query(alias="tsCode"),
    trade_date: date | None = Query(default=None, alias="tradeDate"),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> StockDetailPageInitResponseDto:
    try:
        return StockDetailQueryService(period_capabilities=_stock_period_capabilities(request)).build_page_init(
            session,
            ts_code=ts_code.strip().upper(),
            trade_date=trade_date,
            debug=bool(debug),
        )
    except StockDetailNotFoundError as exc:
        raise WebAppError(status_code=404, code="404001", message=str(exc)) from exc
    except ValueError as exc:
        raise WebAppError(status_code=400, code="400001", message=str(exc)) from exc


def get_local_stock_detail_page_init(
    request: Request,
    ts_code: str = Query(alias="tsCode"),
    trade_date: date | None = Query(default=None, alias="tradeDate"),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
) -> LocalStockDetailPageInitResponseDto:
    try:
        return StockDetailQueryService(request.app.state.reference_data,
                                       period_capabilities=_stock_period_capabilities(request)).build_local_page_init(
            ts_code=ts_code.strip().upper(), trade_date=trade_date, debug=bool(debug),
        )
    except StockDetailNotFoundError as exc:
        raise WebAppError(status_code=404, code="404001", message=str(exc)) from exc
    except ReferenceDataReadError as exc:
        raise WebAppError(
            status_code=500, code="internal_error", message=f"读取数据失败：{exc}",
        ) from exc
    except ValueError as exc:
        raise WebAppError(status_code=400, code="400001", message=str(exc)) from exc


async def get_stock_detail_kline(
    request: Request,
    ts_code: str = Query(alias="tsCode"),
    period: str = Query(default="day"),
    adjustment: str = Query(default="forward"),
    trade_date: date | None = Query(default=None, alias="tradeDate"),
    start_date: date | None = Query(default=None, alias="startDate"),
    end_date: date | None = Query(default=None, alias="endDate"),
    limit: int | None = Query(default=None),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    backend: StockDailyKlineBackend = Depends(get_stock_daily_kline_backend),
) -> Response:
    return backend.response(StockDailyKlineRequest(
        ts_code.strip().upper(), period, adjustment, trade_date, start_date, end_date,
        limit if limit is not None else (100 if period == "week" else 500), bool(debug),
    ), arrived_at=request.state.stock_daily_arrived_at)


def build_router(*, local: bool) -> APIRouter:
    router = APIRouter(prefix="/wealth/market/stock-detail", tags=["wealth-market"])
    router.add_api_route(
        "/page-init", get_local_stock_detail_page_init if local else get_stock_detail_page_init,
        methods=["GET"],
        response_model=LocalStockDetailPageInitResponseDto if local else StockDetailPageInitResponseDto,
    )
    router.add_api_route(
        "/kline", get_stock_detail_kline, methods=["GET"], response_class=JSONResponse,
        response_model=(LocalStockDetailFirstKlineResponseDto | LocalStockDetailPagedKlineResponseDto
                        | StockDetailKlineResponseDto | StockDetailPeriodKlineResponseDto
                        if local else StockDetailKlineResponseDto | StockDetailPeriodKlineResponseDto),
    )
    return router
