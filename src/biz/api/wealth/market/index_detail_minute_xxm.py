from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.biz.api.wealth.market.index_detail_xxm import parse_parameters
from src.biz.queries.wealth.market.index_detail_xxm.query_service import IndexDetailXxmQueryService, XxmQueryError
from src.biz.schemas.wealth.market.index_detail_xxm import XxmResponseDto


def build_router(*, db_dependency: Callable, auth_dependency: Callable, lake_dependency: Callable,
                 error_factory: Callable) -> APIRouter:
    router = APIRouter(prefix="/wealth/market/index-detail", tags=["wealth-market"])

    @router.get("/minute-xxm-signals", response_model=XxmResponseDto)
    def get_index_minute_xxm(request: Request, ts_code: str | None = Query(None, alias="tsCode"),
                             freq: str | None = Query(None), start_date: str | None = Query(None, alias="startDate"),
                             end_date: str | None = Query(None, alias="endDate"), limit: str | None = Query(None),
                             _user=Depends(auth_dependency), session: Session = Depends(db_dependency),
                             lake_root: Path = Depends(lake_dependency)) -> XxmResponseDto:
        try:
            return IndexDetailXxmQueryService(lake_root=lake_root).build(session, **parse_parameters(request, minute=True))
        except XxmQueryError as exc:
            raise error_factory(status_code=exc.status, code=exc.code, message=str(exc)) from exc

    return router
