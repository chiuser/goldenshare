from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PageStatusValue = Literal["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"]
SessionStatusValue = Literal["PRE_OPEN", "TRADING", "BREAK", "CLOSED"]
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


class LadderV5StockDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stockName: str | None = None
    stockCode: str
    latestPrice: float | None = None
    changePct: float | None = None
    sectorName: str | None = None
    limitAmount: float | None = None
    limitAmountDisplayText: str
    limitAmountLabel: Literal["封单金额", "板上成交金额"]
    streakText: str
    openTimes: int | None = None
    firstLimitTime: str | None = None
    currentStreakLevel: int = Field(ge=0)
    advanced: bool


class LadderV5PromotionLayerDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previousLabel: str
    currentLabel: str
    previousStocks: list[LadderV5StockDto]
    currentStocks: list[LadderV5StockDto]


class StreakLadderV5Dto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    prevTradeDate: date
    highestStreakLevel: int = Field(ge=0)
    aboveFive: list[LadderV5StockDto]
    promotions: dict[int, LadderV5PromotionLayerDto]
    firstBoard: list[LadderV5StockDto]


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


class StreakLadderDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[ModuleStatusItemDto]
    exceptions: list[ModuleExceptionItemDto]


class StreakLadderResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradingDay: TradingDayDto
    pageStatus: PageStatusDto
    streakLadderV5: StreakLadderV5Dto
    debugInfo: StreakLadderDebugInfoDto | None = None
