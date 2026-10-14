from __future__ import annotations

from datetime import date
import re
from typing import Callable

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.index_detail_xxm.query_service import IndexDetailXxmQueryService, XxmQueryError
from src.biz.schemas.wealth.market.index_detail_xxm import XxmResponseDto
from src.biz.services.wealth.market.index_detail_xxm.runtime import BUDGET


def parse_parameters(request: Request, *, minute: bool) -> dict:
    allowed = {"tsCode", "freq" if minute else "period", "startDate", "endDate", "limit"}
    supplied = [key for key, _value in request.query_params.multi_items()]
    if set(supplied) - allowed or len(supplied) != len(set(supplied)):
        raise XxmQueryError("XXM_REQUEST_INVALID", "研究指标参数未知或重复。", 400)
    code = (request.query_params.get("tsCode") or "").strip().upper()
    if not re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", code):
        raise XxmQueryError("XXM_REQUEST_INVALID", "tsCode 必须是六位代码及市场后缀。", 400)
    if code != "000001.SH":
        raise XxmQueryError("XXM_NOT_SUPPORTED", "研究指标 V0.1 仅支持上证指数。", 404)
    if minute:
        raw = request.query_params.get("freq", "")
        if raw not in ("60", "90", "120"):
            raise XxmQueryError("XXM_REQUEST_INVALID", "研究指标分钟周期只支持 60／90／120。", 400)
        period = f"m{raw}"
    else:
        period = request.query_params.get("period", "day")
        if period != "day":
            raise XxmQueryError("XXM_REQUEST_INVALID", "此研究接口只支持日线。", 400)
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
    return {"period": period, "start_date": dates["startDate"], "end_date": dates["endDate"], "limit": int(raw_limit)}


def build_router(*, db_dependency: Callable, auth_dependency: Callable, error_factory: Callable) -> APIRouter:
    """App supplies infrastructure dependencies; Biz never imports App."""
    router = APIRouter(prefix="/wealth/market/index-detail", tags=["wealth-market"])

    @router.get("/xxm-signals", response_model=XxmResponseDto)
    def get_index_xxm(request: Request, ts_code: str | None = Query(None, alias="tsCode"),
                      period: str | None = Query(None), start_date: str | None = Query(None, alias="startDate"),
                      end_date: str | None = Query(None, alias="endDate"), limit: str | None = Query(None),
                      _user=Depends(auth_dependency), session: Session = Depends(db_dependency)) -> XxmResponseDto:
        try:
            return IndexDetailXxmQueryService().build(session, **parse_parameters(request, minute=False))
        except XxmQueryError as exc:
            raise error_factory(status_code=exc.status, code=exc.code, message=str(exc)) from exc

    return router
