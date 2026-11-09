from __future__ import annotations

from datetime import date
import re
from typing import Callable

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.index_detail_xxm.query_service import XxmQueryError
from src.biz.queries.wealth.market.index_detail_xxm.gold_query import build_gold_history
from src.biz.schemas.wealth.market.index_detail_xxm_gold import GoldXxmResponseDto
from src.biz.services.wealth.market.index_detail_xxm.runtime import BUDGET
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader


def parse_parameters(request: Request, *, minute: bool) -> dict:
    allowed = {"tsCode", "freq" if minute else "period", "startDate", "endDate", "limit"}
    supplied = [key for key, _value in request.query_params.multi_items()]
    if set(supplied) - allowed or len(supplied) != len(set(supplied)):
        raise XxmQueryError("XXM_REQUEST_INVALID", "顶底识别参数未知或重复。", 400)
    code = (request.query_params.get("tsCode") or "").strip().upper()
    if not re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", code):
        raise XxmQueryError("XXM_REQUEST_INVALID", "tsCode 必须是六位代码及市场后缀。", 400)
    if minute:
        raw = request.query_params.get("freq", "")
        if raw not in ("30", "60", "90", "120"):
            raise XxmQueryError("XXM_REQUEST_INVALID", "顶底识别分钟周期只支持 30／60／90／120。", 400)
        period = f"m{raw}"
    else:
        period = request.query_params.get("period", "day")
        if period != "day":
            raise XxmQueryError("XXM_REQUEST_INVALID", "此识别接口只支持日线。", 400)
    dates = {}
    for name in ("startDate", "endDate"):
        raw = request.query_params.get(name)
        try:
            if raw is not None and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
                raise ValueError("date format")
            dates[name] = date.fromisoformat(raw) if raw is not None else None
        except ValueError as exc:
            raise XxmQueryError("XXM_REQUEST_INVALID", f"{name} 必须是有效 YYYY-MM-DD 日期。", 400) from exc
    if dates["startDate"] and dates["endDate"] and dates["startDate"] > dates["endDate"]:
        raise XxmQueryError("XXM_REQUEST_INVALID", "startDate 不能晚于 endDate。", 400)
    default = BUDGET.response_default_minute if minute else BUDGET.response_default_day
    raw_limit = request.query_params.get("limit", str(default))
    if not re.fullmatch(r"[0-9]{1,4}", raw_limit) or not 1 <= int(raw_limit) <= BUDGET.max_response_rows:
        raise XxmQueryError("XXM_REQUEST_INVALID", "limit 必须在 1～2000 之间。", 400)
    return {"ts_code": code, "period": period, "start_date": dates["startDate"], "end_date": dates["endDate"], "limit": int(raw_limit)}


def build_router(
    *, db_dependency: Callable, auth_dependency: Callable, error_factory: Callable,
    daily_lake: IndexDailyLakeReader | None = None,
    path: str = "/xxm-signals", load=None, response_model=GoldXxmResponseDto,
) -> APIRouter:
    """App supplies infrastructure dependencies; Biz never imports App."""
    router = APIRouter(prefix="/wealth/market/index-detail", tags=["wealth-market"])

    @router.get(path, response_model=response_model)
    def get_index_xxm(request: Request, ts_code: str | None = Query(None, alias="tsCode"),
                      period: str | None = Query(None), start_date: str | None = Query(None, alias="startDate"),
                      end_date: str | None = Query(None, alias="endDate"), limit: str | None = Query(None),
                      _user=Depends(auth_dependency), session: Session = Depends(db_dependency)) -> Response:
        try:
            params = parse_parameters(request, minute=False)
            body = (build_gold_history(daily_lake=daily_lake, **params)
                    if load is None else load(session, **params))
            return Response(content=body, media_type="application/json", headers={"Cache-Control": "no-store"})
        except XxmQueryError as exc:
            raise error_factory(status_code=exc.status, code=exc.code, message=str(exc)) from exc

    return router
