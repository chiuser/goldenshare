from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from src.biz.services.wealth.market.watchlist.watchlist_policy import MAX_API_ID

from src.biz.schemas.wealth.market.context import MarketPageContextDto

WatchlistDirection = Literal["UP", "DOWN", "FLAT", "UNKNOWN"]
ApiId = Annotated[StrictInt, Field(ge=1, le=MAX_API_ID)]
SafeCount = Annotated[StrictInt, Field(ge=0, le=MAX_API_ID)]


class WatchlistDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WatchlistGroupDto(WatchlistDto):
    id: ApiId
    name: str
    isDefault: bool
    color: str | None
    memberCount: SafeCount
    createdAt: datetime


class WatchlistGroupRulesDto(WatchlistDto):
    maxGroups: SafeCount
    maxCustomGroups: SafeCount
    nameMaxVisibleChars: SafeCount
    nameMaxUtf8Bytes: SafeCount
    maxBatchMemberships: SafeCount
    palette: list[str]


class WatchlistGroupsResponseDto(WatchlistDto):
    groups: list[WatchlistGroupDto]
    rules: WatchlistGroupRulesDto


class WatchlistGroupMutationResponseDto(WatchlistDto):
    group: WatchlistGroupDto


class WatchlistGroupDeleteResponseDto(WatchlistDto):
    deletedGroupId: ApiId
    deletedMemberCount: SafeCount
    nextGroupId: ApiId


class WatchlistGroupMarkDto(WatchlistDto):
    groupId: ApiId
    name: str
    color: str


class WatchlistGroupCountDto(WatchlistDto):
    groupId: ApiId
    memberCount: SafeCount


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
    membershipId: ApiId
    addedAt: datetime
    isPinned: bool
    groupMarks: list[WatchlistGroupMarkDto]
    stock: WatchlistStockDto
    quote: WatchlistQuoteDto
    valuation: WatchlistValuationDto
    activity: WatchlistActivityDto
    moneyFlow: WatchlistMoneyFlowDto
    missingFields: list[str] = Field(default_factory=list)


class WatchlistPageResponseDto(WatchlistDto):
    group: WatchlistGroupDto
    pageContext: MarketPageContextDto
    dataStatus: WatchlistDataStatusDto
    items: list[WatchlistItemDto]
    totalCount: SafeCount
    nextCursor: str | None


class WatchlistSummaryResponseDto(WatchlistDto):
    totalCount: SafeCount


class WatchlistSearchItemDto(WatchlistDto):
    tsCode: str
    name: str
    status: Literal["AVAILABLE", "ADDED"]


class WatchlistSearchResponseDto(WatchlistDto):
    groupId: ApiId
    keyword: str
    items: list[WatchlistSearchItemDto]


class WatchlistAddResponseDto(WatchlistDto):
    groupId: ApiId
    tsCode: str
    isAdded: Literal[True]
    created: bool
    memberCount: SafeCount


class WatchlistBatchActionResponseDto(WatchlistDto):
    action: Literal["MOVE", "ADD_TO_GROUPS", "REMOVE", "PIN", "UNPIN"]
    requestedCount: SafeCount
    createdCount: SafeCount
    removedCount: SafeCount
    updatedCount: SafeCount
    groupCounts: list[WatchlistGroupCountDto]


class WatchlistStockGroupDto(WatchlistDto):
    groupId: ApiId
    name: str
    isDefault: bool
    color: str | None
    selected: bool


class WatchlistStockGroupsResponseDto(WatchlistDto):
    tsCode: str
    isAdded: bool
    groups: list[WatchlistStockGroupDto]


class WatchlistStockGroupsReplaceResponseDto(WatchlistDto):
    tsCode: str
    isAdded: Literal[True]
    groupIds: list[ApiId]
    createdCount: SafeCount
    removedCount: SafeCount


class WatchlistGroupCreateRequest(WatchlistDto):
    name: str
    color: str


class WatchlistGroupColorRequest(WatchlistDto):
    color: str


class WatchlistSelectionRequest(WatchlistDto):
    membershipIds: list[ApiId]


class WatchlistMoveRequest(WatchlistSelectionRequest):
    targetGroupId: ApiId


class WatchlistAddToGroupsRequest(WatchlistSelectionRequest):
    targetGroupIds: list[ApiId]


class WatchlistStockGroupsReplaceRequest(WatchlistDto):
    groupIds: list[ApiId]
