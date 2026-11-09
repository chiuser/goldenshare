from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from src.biz.api.wealth.market.index_detail_xxm import parse_parameters
from src.biz.queries.wealth.market.index_detail_xxm.query_service import XxmQueryError
from src.biz.queries.wealth.market.index_detail_xxm.gold_query import build_gold_history
from src.biz.schemas.wealth.market.index_detail_xxm_gold import GoldXxmResponseDto
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader


def build_router(
    *, db_dependency: Callable, auth_dependency: Callable, lake_dependency: Callable,
    error_factory: Callable, daily_lake: IndexDailyLakeReader | None = None,
    path: str = "/minute-xxm-signals", load=None, response_model=GoldXxmResponseDto,
) -> APIRouter:
    router = APIRouter(prefix="/wealth/market/index-detail", tags=["wealth-market"])

    @router.get(path, response_model=response_model)
    def get_index_minute_xxm(request: Request, ts_code: str | None = Query(None, alias="tsCode"),
                             freq: str | None = Query(None), start_date: str | None = Query(None, alias="startDate"),
                             end_date: str | None = Query(None, alias="endDate"), limit: str | None = Query(None),
                             _user=Depends(auth_dependency), session: Session = Depends(db_dependency),
                             lake_root: Path = Depends(lake_dependency)) -> Response:
        try:
            params = parse_parameters(request, minute=True)
            body = (build_gold_history(daily_lake=daily_lake, lake_root=lake_root, **params)
                    if load is None else load(session, lake_root=lake_root, **params))
            return Response(content=body, media_type="application/json", headers={"Cache-Control": "no-store"})
        except XxmQueryError as exc:
            raise error_factory(status_code=exc.status, code=exc.code, message=str(exc)) from exc

    return router
