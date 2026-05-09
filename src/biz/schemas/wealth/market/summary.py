from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


PageStatusValue = Literal["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"]
SessionStatusValue = Literal["PRE_OPEN", "TRADING", "BREAK", "CLOSED"]
DirectionValue = Literal["UP", "DOWN", "FLAT", "UNKNOWN"]
SeverityValue = Literal["info", "warn", "error"]


class TradingDayDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    prevTradeDate: date | None = None
    market: Literal["CN_A"]
    isTradingDay: bool
    sessionStatus: SessionStatusValue
    timezone: Literal["Asia/Shanghai"]


class PageStatusDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PageStatusValue
    displayText: str
    asOfTime: datetime | None = None


class MarketSummaryDefinitionDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definitionKey: str
    version: str
    cardCount: Literal[5, 6]
    textPosition: Literal["BOTTOM_FIXED"] = "BOTTOM_FIXED"
    layoutVariant: Literal["FIVE_SINGLE_ROW", "SIX_TWO_ROWS"]


class MarketSummaryCardDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cardKey: str
    label: str
    value: str | None = None
    subText: str | None = None
    direction: DirectionValue | None = None


class MarketSummaryTextCardDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    content: str
    templateKey: str


class MarketSummaryPayloadDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: MarketSummaryDefinitionDto
    cards: list[MarketSummaryCardDto]
    textCard: MarketSummaryTextCardDto


class ModuleStatusItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    moduleKey: str
    expectedTradeDate: date
    observedTradeDate: date | None = None
    lagDays: int | None = None
    status: PageStatusValue
    note: str | None = None


class ModuleExceptionItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: str
    code: str
    severity: SeverityValue
    message: str
    details: dict[str, str | int | float | None] | None = None


class MarketSummaryDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[ModuleStatusItemDto]
    exceptions: list[ModuleExceptionItemDto]


class MarketSummaryResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradingDay: TradingDayDto
    pageStatus: PageStatusDto
    marketSummary: MarketSummaryPayloadDto
    debugInfo: MarketSummaryDebugInfoDto | None = None

