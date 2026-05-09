from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class MarketStyleDefinitionDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definitionKey: str
    version: str
    fixedCardCount: Literal[3] = 3


class MarketStyleCardDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cardKey: Literal["largeCap", "smallCap", "median"]
    label: str
    valuePct: float | None = None
    sourceText: str
    direction: DirectionValue


class MarketStyleHistoryPointDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    largePct: float | None = None
    smallPct: float | None = None
    medianPct: float | None = None


class MarketStylePayloadDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: MarketStyleDefinitionDto
    cards: list[MarketStyleCardDto] = Field(min_length=3, max_length=3)
    historyByRange: dict[str, list[MarketStyleHistoryPointDto]]

    @model_validator(mode="after")
    def _validate_history_ranges(self) -> "MarketStylePayloadDto":
        keys = set(self.historyByRange.keys())
        if keys != {"oneMonth", "threeMonth"}:
            raise ValueError("historyByRange must contain exact keys: oneMonth, threeMonth")
        return self


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


class MarketStyleDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[ModuleStatusItemDto]
    exceptions: list[ModuleExceptionItemDto]


class MarketStyleResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradingDay: TradingDayDto
    pageStatus: PageStatusDto
    style: MarketStylePayloadDto
    debugInfo: MarketStyleDebugInfoDto | None = None
