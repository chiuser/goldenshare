"""Approved return read endpoints; no calculation or mutation on GET."""
from datetime import date
from typing import Literal

from fastapi import Depends, Request

from src.biz.schemas.wealth.market.trading_assistant.returns import DayDetail, CurveResponse, CalendarResponse
from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountReadQuery, CurveQuery, CalendarQuery
from src.biz.schemas.wealth.market.trading_assistant.value_types import BusinessDate, EntityId, StockCode, Month
from .dependencies import TradingAssistantDependencies
from .record_routes import parse_record_query


def register_return_routes(router, *, auth_dependency, dependencies_dependency):
    auth, services = Depends(auth_dependency), Depends(dependencies_dependency)

    @router.get("/returns/calendar", response_model=CalendarResponse)
    async def calendar(request: Request, accountMode: Literal["ALL", "SINGLE"], month: Month,
                       accountId: EntityId | None = None, readContext: str | None = None,
                       owner_id: int = auth, deps: TradingAssistantDependencies = services):
        query = parse_record_query(request, CalendarQuery)
        return await deps.read_return_calendar(owner_id=owner_id, query=query)

    @router.get("/returns/curve", response_model=CurveResponse)
    async def curve(request: Request, accountMode: Literal["ALL", "SINGLE"], stockMode: Literal["ALL", "SINGLE"],
                    requestedStartDate: BusinessDate, requestedEndDate: BusinessDate,
                    granularity: Literal["DAY", "WEEK", "MONTH"], accountId: EntityId | None = None,
                    tsCode: StockCode | None = None, readContext: str | None = None,
                    owner_id: int = auth, deps: TradingAssistantDependencies = services):
        query = parse_record_query(request, CurveQuery)
        return await deps.read_return_curve(owner_id=owner_id, query=query)

    @router.get("/returns/days/{day}", response_model=DayDetail)
    async def detail(day: BusinessDate, request: Request, accountMode: Literal["ALL", "SINGLE"],
                     accountId: EntityId | None = None, readContext: str | None = None,
                     owner_id: int = auth, deps: TradingAssistantDependencies = services):
        query = parse_record_query(request, AccountReadQuery)
        return await deps.read_return_day(owner_id=owner_id, query=query, day=date.fromisoformat(day))
