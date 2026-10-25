"""One bounded, in-memory daily-wave response; App supplies infrastructure."""
from __future__ import annotations

import asyncio
import json
from typing import Callable

import psycopg
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from src.biz.queries.wealth.market.index_detail_daily_wave.query import DailyWaveSourceError
from src.biz.queries.wealth.market.index_detail_daily_wave.query_service import DailyWaveQueryService
from src.biz.schemas.wealth.market.index_detail_daily_wave import DailyWaveEmptyDto, DailyWaveReadyDto
from src.biz.services.wealth.market.index_detail_daily_wave.budget import (
    DailyWaveBudget,
    DailyWaveBudgetExceeded,
    DailyWaveCancelled,
    DailyWaveInputError,
)
from src.biz.services.wealth.market.index_detail_daily_wave.spec import DEFAULT_SPEC


def _build_response(result, *, budget: DailyWaveBudget) -> Response:
    """Validate and encode once, before the original deadline expires."""
    budget.check()
    payload = result.to_dict()
    if not isinstance(payload, dict):
        raise DailyWaveInputError("波段结果必须为约定字段对象")
    if payload.get("status") == "ready":
        if ("priceSegments" not in payload or "asofChanges" not in payload
                or "segments" in payload):
            raise DailyWaveInputError("波段结果缺少内部必需字段或包含重名字段")
        payload["segments"] = payload.pop("priceSegments")
        del payload["asofChanges"]
        dto_type = DailyWaveReadyDto
    else:
        dto_type = DailyWaveEmptyDto
    budget.check()
    dto = dto_type.model_validate(payload, strict=True)
    payload = dto.model_dump(mode="json")
    budget.check()
    try:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise DailyWaveInputError("波段结果无法编码为JSON") from error
    budget.check()
    if len(body) > DEFAULT_SPEC.max_response_bytes:
        raise DailyWaveBudgetExceeded("波段响应超过字节上限")
    response = Response(content=body, media_type="application/json",
                        headers={"Cache-Control": "no-store"})
    budget.check()
    return response


def build_router(*, session_factory: Callable, auth_dependency: Callable,
                 error_factory: Callable) -> APIRouter:
    """No App imports, synchronous business sessions, or alternative data reads."""
    router = APIRouter(prefix="/wealth/market/index-detail", tags=["wealth-market"])
    service = DailyWaveQueryService(session_factory)

    @router.get("/daily-waves", response_model=DailyWaveReadyDto | DailyWaveEmptyDto)
    async def get_daily_waves(request: Request,
                              _ts_code: str | None = Query(None, alias="tsCode"),
                              _user=Depends(auth_dependency)) -> Response:
        supplied = request.query_params.multi_items()
        if len(supplied) != 1 or supplied[0] != ("tsCode", DEFAULT_SPEC.ts_code):
            raise error_factory(status_code=422, code="DAILY_WAVE_INVALID_REQUEST",
                message="波段核对仅支持唯一的上证指数代码，请检查参数。")

        task = asyncio.current_task()

        def check_cancelled() -> bool:
            return task is not None and task.cancelling() > 0

        try:
            budget = DailyWaveBudget(DEFAULT_SPEC, check_cancelled=check_cancelled)
            budget.check()
            result = await service.build(spec=DEFAULT_SPEC, deadline=budget.deadline,
                                         check_cancelled=check_cancelled)
            return _build_response(result, budget=budget)
        except asyncio.CancelledError:
            raise
        except DailyWaveCancelled as error:
            raise asyncio.CancelledError() from error
        except DailyWaveBudgetExceeded as error:
            raise error_factory(status_code=503, code="DAILY_WAVE_BUDGET_EXCEEDED",
                message="波段划分处理超过限制，请重试。") from error
        except (DailyWaveSourceError, SQLAlchemyError, psycopg.Error) as error:
            raise error_factory(status_code=503, code="DAILY_WAVE_SOURCE_INVALID",
                message="波段划分所需行情或日历暂不可用。") from error
        except (DailyWaveInputError, ValidationError) as error:
            raise error_factory(status_code=503, code="DAILY_WAVE_CALCULATION_FAILED",
                message="波段划分结果校验或响应生成失败。") from error

    return router
