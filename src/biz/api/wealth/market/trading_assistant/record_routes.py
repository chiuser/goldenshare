"""Typed paginated record routes; source selection stays in Biz queries."""
import re
from typing import Literal

from fastapi import Depends, Request
from pydantic import ValidationError

from src.biz.schemas.wealth.market.trading_assistant.records import (
    TradeRecordsResponse, CashRecordsResponse, TradeDayGroupsResponse, RecordsSummary, ClosedRecordsResponse,
)
from src.biz.schemas.wealth.market.trading_assistant.scopes import TradeRecordsQuery, CashRecordsQuery, RangeQuery, RangeRecordsQuery, RoundRecordsQuery
from src.biz.schemas.wealth.market.trading_assistant.value_types import EntityId, BusinessDate, StockCode
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .dependencies import TradingAssistantDependencies


def parse_record_query(request, model):
    pairs = list(request.query_params.multi_items())
    values = dict(pairs)
    if len(values) != len(pairs):
        raise WriteProtocolConflict("TA_REQUEST_INVALID")
    if "limit" in values:
        if not re.fullmatch(r"[1-9][0-9]{0,2}", values["limit"]):
            raise WriteProtocolConflict("TA_REQUEST_INVALID")
        values["limit"] = int(values["limit"])
    try:
        return model.model_validate(values)
    except ValidationError as error:
        raise WriteProtocolConflict("TA_REQUEST_INVALID") from error


def register_record_routes(router, *, auth_dependency, dependencies_dependency):
    auth, services = Depends(auth_dependency), Depends(dependencies_dependency)

    @router.get("/records/closed-trades", response_model=ClosedRecordsResponse)
    async def closed(request: Request, accountMode: Literal["ALL", "SINGLE"] | None = None,
                     stockMode: Literal["ALL", "SINGLE"] | None = None,
                     requestedStartDate: BusinessDate | None = None, requestedEndDate: BusinessDate | None = None,
                     accountId: EntityId | None = None, tsCode: StockCode | None = None, roundId: EntityId | None = None,
                     limit: int = 20, cursor: str | None = None, readContext: str | None = None,
                     owner_id: int = auth, deps: TradingAssistantDependencies = services):
        model = RoundRecordsQuery if "roundId" in request.query_params else RangeRecordsQuery
        return await deps.read_closed_records(owner_id=owner_id, query=parse_record_query(request, model))

    @router.get("/records/summary", response_model=RecordsSummary)
    async def summary(request: Request, accountMode: Literal["ALL", "SINGLE"], stockMode: Literal["ALL", "SINGLE"],
                      requestedStartDate: BusinessDate, requestedEndDate: BusinessDate,
                      accountId: EntityId | None = None, tsCode: StockCode | None = None,
                      readContext: str | None = None, owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read_records_summary(owner_id=owner_id, query=parse_record_query(request, RangeQuery))

    @router.get("/records/trades", response_model=TradeRecordsResponse)
    async def trades(request: Request, accountMode: Literal["ALL", "SINGLE"], stockMode: Literal["ALL", "SINGLE"],
                     requestedStartDate: BusinessDate, requestedEndDate: BusinessDate,
                     accountId: EntityId | None = None, tsCode: StockCode | None = None,
                     direction: Literal["BUY", "SELL"] | None = None, limit: int = 20, cursor: str | None = None,
                     readContext: str | None = None, owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read_records(owner_id=owner_id, query=parse_record_query(request, TradeRecordsQuery), kind="TRADE")

    @router.get("/records/cash-flows", response_model=CashRecordsResponse)
    async def cash(request: Request, accountMode: Literal["ALL", "SINGLE"],
                   requestedStartDate: BusinessDate, requestedEndDate: BusinessDate,
                   accountId: EntityId | None = None, direction: Literal["IN", "OUT"] | None = None,
                   limit: int = 20, cursor: str | None = None, readContext: str | None = None,
                   owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read_records(owner_id=owner_id, query=parse_record_query(request, CashRecordsQuery), kind="CASH_FLOW")

    @router.get("/records/trade-day-groups", response_model=TradeDayGroupsResponse)
    async def groups(request: Request, accountMode: Literal["ALL", "SINGLE"], stockMode: Literal["ALL", "SINGLE"],
                     requestedStartDate: BusinessDate, requestedEndDate: BusinessDate,
                     accountId: EntityId | None = None, tsCode: StockCode | None = None,
                     direction: Literal["BUY", "SELL"] | None = None, limit: int = 20, cursor: str | None = None,
                     readContext: str | None = None, owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read_records(owner_id=owner_id, query=parse_record_query(request, TradeRecordsQuery), kind="TRADE", grouped=True)
