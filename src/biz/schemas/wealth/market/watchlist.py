from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.biz.schemas.wealth.market.context import MarketPageContextDto

WatchlistDirection = Literal["UP", "DOWN", "FLAT", "UNKNOWN"]


class WatchlistDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WatchlistDataStatusDto(WatchlistDto):
    status: Literal["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"]
    expectedTradeDate: date
    observedTradeDate: date | None = None


class WatchlistStockDto(WatchlistDto):
    tsCode: str
    name: str
    industry: str | None
    listStatus: str | None


class WatchlistQuoteDto(WatchlistDto):
    price: float | None
    changePct: float | None
    direction: WatchlistDirection
    vol: float | None


class WatchlistValuationDto(WatchlistDto):
    peTtm: float | None
    pb: float | None


class WatchlistActivityDto(WatchlistDto):
    volumeRatio: float | None
    turnoverRate: float | None


class WatchlistMoneyFlowDto(WatchlistDto):
    netAmount: float | None
    direction: WatchlistDirection


class WatchlistItemDto(WatchlistDto):
    id: int
    addedAt: datetime
    stock: WatchlistStockDto
    quote: WatchlistQuoteDto
    valuation: WatchlistValuationDto
    activity: WatchlistActivityDto
    moneyFlow: WatchlistMoneyFlowDto
    missingFields: list[str] = Field(default_factory=list)


class WatchlistPageResponseDto(WatchlistDto):
    pageContext: MarketPageContextDto
    dataStatus: WatchlistDataStatusDto
    items: list[WatchlistItemDto]
    totalCount: int
    nextCursor: int | None


class WatchlistSummaryResponseDto(WatchlistDto):
    totalCount: int


class WatchlistSearchItemDto(WatchlistDto):
    tsCode: str
    name: str
    status: Literal["AVAILABLE", "ADDED"]


class WatchlistSearchResponseDto(WatchlistDto):
    keyword: str
    items: list[WatchlistSearchItemDto]


class WatchlistMembershipResponseDto(WatchlistDto):
    tsCode: str
    isAdded: bool


class WatchlistAddResponseDto(WatchlistMembershipResponseDto):
    created: bool
    totalCount: int


class WatchlistRemoveResponseDto(WatchlistMembershipResponseDto):
    removed: bool
    totalCount: int
