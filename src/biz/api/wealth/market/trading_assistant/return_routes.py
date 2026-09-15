"""Approved return read endpoints; no calculation or mutation on GET."""
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import Depends, Request

from src.biz.schemas.wealth.market.trading_assistant.returns import DayDetail, CurveResponse, CalendarResponse, DayContributions
from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountReadQuery, CurveQuery, CalendarQuery, DayContributionsQuery
from src.biz.schemas.wealth.market.trading_assistant.value_types import BusinessDate, EntityId, StockCode, Month
from src.biz.schemas.wealth.market.trading_assistant.records import RoundDetailResponse, CompletedRoundsResponse
from src.biz.schemas.wealth.market.trading_assistant.scopes import RangeRecordsQuery
from src.biz.schemas.wealth.market.trading_assistant.scopes import RangeQuery
from src.biz.schemas.wealth.market.trading_assistant.returns import ReviewResponse
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .dependencies import TradingAssistantDependencies
from .record_routes import parse_record_query


def register_return_routes(router, *, auth_dependency, dependencies_dependency):
    auth, services = Depends(auth_dependency), Depends(dependencies_dependency)

    @router.get("/returns/review", response_model=ReviewResponse)
    async def review(request: Request, accountMode: Literal["ALL", "SINGLE"], stockMode: Literal["ALL", "SINGLE"],
                     requestedStartDate: BusinessDate, requestedEndDate: BusinessDate,
                     accountId: EntityId | None = None, tsCode: StockCode | None = None,
                     readContext: str | None = None, owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read_return_review(owner_id=owner_id, query=parse_record_query(request, RangeQuery))

    @router.get("/holding-rounds/completed", response_model=CompletedRoundsResponse)
    async def completed_rounds(request: Request, accountMode: Literal["ALL", "SINGLE"], stockMode: Literal["ALL", "SINGLE"],
                               requestedStartDate: BusinessDate, requestedEndDate: BusinessDate,
                               accountId: EntityId | None = None, tsCode: StockCode | None = None,
                               limit: int = 20, cursor: str | None = None, readContext: str | None = None,
                               owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read_completed_rounds(owner_id=owner_id, query=parse_record_query(request, RangeRecordsQuery))

    @router.get("/accounts/{accountId}/holding-rounds/{roundId}", response_model=RoundDetailResponse)
    async def round_detail(accountId: EntityId, roundId: EntityId, request: Request,
                           readContext: str | None = None,
                           owner_id: int = auth, deps: TradingAssistantDependencies = services):
        pairs = list(request.query_params.multi_items())
        if len(pairs) != len(dict(pairs)) or any(key != "readContext" for key, _ in pairs):
            raise WriteProtocolConflict("TA_REQUEST_INVALID")
        return await deps.read_round_detail(owner_id=owner_id, account_id=UUID(accountId),
            round_id=UUID(roundId), context_token=readContext)

    @router.get("/returns/days/{day}/contributions", response_model=DayContributions)
    async def contributions(day: BusinessDate, request: Request, accountMode: Literal["ALL", "SINGLE"],
                            accountId: EntityId | None = None, readContext: str | None = None,
                            limit: int = 20, cursor: str | None = None,
                            owner_id: int = auth, deps: TradingAssistantDependencies = services):
        query = parse_record_query(request, DayContributionsQuery)
        return await deps.read_return_contributions(owner_id=owner_id, query=query, day=date.fromisoformat(day))

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
