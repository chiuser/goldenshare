from datetime import date, datetime
import re
from fastapi import APIRouter, Depends, Query, Request
from .index_detail_xxm import XxmQueryError
from src.biz.queries.wealth.market.index_detail_xxm.forecast_query_service import IndexDetailXxmForecastQueryService
from src.biz.queries.wealth.market.index_detail_xxm.source import ENDPOINTS
from src.biz.schemas.wealth.market.index_detail_xxm_forecast import ForecastResponseDto


def parse_parameters(request):
    keys = [k for k, v in request.query_params.multi_items()]
    if set(keys) - {"tsCode", "period", "asOf"} or len(keys) != len(set(keys)):
        raise XxmQueryError("XXM_REQUEST_INVALID", "预测参数未知或重复。", 400)
    code = request.query_params.get("tsCode", "")
    if not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", code):
        raise XxmQueryError("XXM_REQUEST_INVALID", "tsCode 格式不合法。", 400)
    if code != "000001.SH":
        raise XxmQueryError("XXM_NOT_SUPPORTED", "预测第一版仅支持上证指数。", 404)
    period = request.query_params.get("period")
    if period not in ("day", "m60", "m90", "m120"):
        raise XxmQueryError("XXM_REQUEST_INVALID", "预测周期不合法。", 400)
    as_of = request.query_params.get("asOf")
    if as_of is not None:
        try:
            if period == "day":
                if date.fromisoformat(as_of).isoformat() != as_of:
                    raise ValueError()
            else:
                stamp = datetime.fromisoformat(as_of)
                if stamp.isoformat() != as_of or not as_of.endswith("+08:00") or stamp.time().replace(tzinfo=None) not in ENDPOINTS[int(period[1:])]:
                    raise ValueError()
        except ValueError:
            raise XxmQueryError("XXM_REQUEST_INVALID", "asOf 必须是该周期标准完成端点。", 400) from None
    return period, as_of


def build_router(*, db_dependency, auth_dependency, lake_dependency, error_factory):
    router = APIRouter(prefix="/wealth/market/index-detail", tags=["wealth-market"])
    @router.get("/xxm-key-point-forecast", response_model=ForecastResponseDto)
    def get_forecast(request: Request, tsCode: str | None = Query(None), period: str | None = Query(None),
                     asOf: str | None = Query(None), user=Depends(auth_dependency), session=Depends(db_dependency)):
        try:
            selected, as_of = parse_parameters(request)
            root = lake_dependency() if selected != "day" else None
            if selected != "day" and root is None:
                raise XxmQueryError("XXM_NOT_SUPPORTED", "当前环境未开放分钟预判。", 404)
            return IndexDetailXxmForecastQueryService(lake_root=root).build(session, period=selected, as_of=as_of)
        except XxmQueryError as exc:
            code = exc.code.replace("XXM_", "XXMF_", 1)
            raise error_factory(status_code=exc.status, code=code, message=str(exc)) from exc
    return router
