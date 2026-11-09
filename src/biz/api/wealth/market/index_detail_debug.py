from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.api.wealth.market.index_detail import (
    _normalize_ts_code, _parse_date, _raise_http_error, _validate_query_shape, query_kline_response,
)
from src.biz.queries.wealth.market.index_detail.index_detail_page_query_service import IndexDetailPageQueryService
from src.biz.queries.wealth.market.index_detail.index_detail_weights_query_service import IndexDetailWeightsQueryService
from src.biz.schemas.wealth.market.index_detail_daily_wave import DailyWaveEmptyDto, DailyWaveReadyDto
from src.biz.services.wealth.market.index_detail_daily_wave.spec import DEFAULT_SPEC


def _json(response):
    return Response(content=response.model_dump_json(), media_type="application/json")


def _date_params(request, ts_code, trade_date):
    _validate_query_shape(request, allowed={"tsCode", "tradeDate"})
    return {"ts_code": _normalize_ts_code(ts_code), "trade_date": _parse_date(trade_date, field_name="tradeDate")}


def build_router(*, daily_lake=None, run_sse_kline=None) -> APIRouter:
    router = APIRouter(prefix="/wealth/market/index-detail/debug", tags=["wealth-market"])

    @router.get("/page-init")
    def page_init(request: Request, ts_code: str | None = Query(None, alias="tsCode"),
                  trade_date: str | None = Query(None, alias="tradeDate"),
                  _user=Depends(require_quote_access), session: Session = Depends(get_db_session)):
        try:
            params = _date_params(request, ts_code, trade_date)
            from src.biz.queries.wealth.market.index_detail.debug_response import page_init_response

            return _json(page_init_response(*IndexDetailPageQueryService().query_page_init(session, **params)))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get("/kline")
    async def kline(request: Request, ts_code: str | None = Query(None, alias="tsCode"),
                    period: str | None = Query(None), start_date: str | None = Query(None, alias="startDate"),
                    end_date: str | None = Query(None, alias="endDate"), limit: str | None = Query(None),
                    _user=Depends(require_quote_access), session: Session = Depends(get_db_session)):
        def project(*facts):
            from src.biz.queries.wealth.market.index_detail.debug_response import kline_response

            return kline_response(*facts)

        response = await query_kline_response(
            request, session, ts_code=ts_code, period=period, start_date=start_date, end_date=end_date,
            limit=limit, daily_lake=daily_lake, run_sse_kline=run_sse_kline, project=project,
        )
        return response if isinstance(response, Response) else _json(response)

    @router.get("/weights")
    def weights(request: Request, ts_code: str | None = Query(None, alias="tsCode"),
                trade_date: str | None = Query(None, alias="tradeDate"),
                _user=Depends(require_quote_access), session: Session = Depends(get_db_session)):
        try:
            params = _date_params(request, ts_code, trade_date)
            from src.biz.queries.wealth.market.index_detail.debug_response import weights_response

            return _json(weights_response(*IndexDetailWeightsQueryService().query_weights(session, **params)))
        except Exception as exc:
            _raise_http_error(exc)

    return router


def build_daily_wave_router(*, session_factory, auth_dependency=require_quote_access,
                            error_factory=WebAppError) -> APIRouter:
    router = APIRouter(prefix="/wealth/market/index-detail/debug", tags=["wealth-market"])

    @router.get("/daily-waves", response_model=DailyWaveReadyDto | DailyWaveEmptyDto)
    async def daily_waves(request: Request, _ts_code: str | None = Query(None, alias="tsCode"),
                          _user=Depends(auth_dependency)) -> Response:
        if request.query_params.multi_items() != [("tsCode", DEFAULT_SPEC.ts_code)]:
            raise error_factory(status_code=422, code="DAILY_WAVE_INVALID_REQUEST",
                message="波段核对仅支持唯一的上证指数代码，请检查参数。")
        from src.biz.api.wealth.market.index_detail_daily_wave import get_daily_waves

        return await get_daily_waves(session_factory=session_factory, error_factory=error_factory)

    return router


def build_xxm_router(*, daily_lake, lake_dependency, minute_enabled) -> APIRouter:
    from src.biz.api.wealth.market import index_detail_xxm, index_detail_xxm_forecast

    router = APIRouter()
    dependencies = dict(db_dependency=get_db_session, auth_dependency=require_quote_access,
                        error_factory=WebAppError, daily_lake=daily_lake)

    def load_signal(session, *, lake_root=None, **params):
        from src.biz.queries.wealth.market.index_detail_xxm.query_service import IndexDetailXxmQueryService
        from src.biz.services.wealth.market.index_detail_xxm.debug_projection import project_debug_signal

        service = IndexDetailXxmQueryService(lake_root=lake_root, daily_lake=daily_lake, entry_scope="debug")
        return service.build(session, project=project_debug_signal, **params)

    def load_forecast(session, *, lake_root, **params):
        from src.biz.queries.wealth.market.index_detail_xxm.forecast_query_service import IndexDetailXxmForecastQueryService
        from src.biz.services.wealth.market.index_detail_xxm.debug_projection import project_debug_forecast

        service = IndexDetailXxmForecastQueryService(lake_root=lake_root, daily_lake=daily_lake, entry_scope="debug")
        return service.build(session, project=project_debug_forecast, **params)

    router.include_router(index_detail_xxm.build_router(
        **dependencies, path="/debug/xxm-signals", load=load_signal, response_model=None,
    ))
    router.include_router(index_detail_xxm_forecast.build_router(
        **dependencies, lake_dependency=lake_dependency, path="/debug/xxm-key-point-forecast",
        load=load_forecast, response_model=None,
    ))
    if minute_enabled:
        from src.biz.api.wealth.market import index_detail_minute_xxm

        router.include_router(index_detail_minute_xxm.build_router(
            **dependencies, lake_dependency=lake_dependency, path="/debug/minute-xxm-signals",
            load=load_signal, response_model=None,
        ))
    return router


def add_openapi_responses(schema):
    """Keep debug validation imports off the request and application startup paths."""
    from src.biz.schemas.wealth.market.index_detail_debug import (
        IndexDetailKlineDebugResponseDto, IndexDetailPageInitDebugResponseDto, IndexDetailWeightsDebugResponseDto,
    )
    from src.biz.schemas.wealth.market.index_detail_xxm_debug import XxmDebugResponseDto
    from src.biz.schemas.wealth.market.index_detail_xxm_forecast_debug import ForecastDebugResponseDto

    models = {
        "page-init": IndexDetailPageInitDebugResponseDto, "kline": IndexDetailKlineDebugResponseDto,
        "weights": IndexDetailWeightsDebugResponseDto, "xxm-signals": XxmDebugResponseDto,
        "minute-xxm-signals": XxmDebugResponseDto, "xxm-key-point-forecast": ForecastDebugResponseDto,
    }
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for endpoint, model in models.items():
        path = f"/api/v1/wealth/market/index-detail/debug/{endpoint}"
        if path in schema["paths"]:
            response = model.model_json_schema(ref_template="#/components/schemas/{model}", mode="serialization")
            for name, definition in response.pop("$defs", {}).items():
                components.setdefault(name, definition)
            components[model.__name__] = response
            content = schema["paths"][path]["get"]["responses"]["200"]["content"]
            content["application/json"]["schema"] = {"$ref": f"#/components/schemas/{model.__name__}"}
