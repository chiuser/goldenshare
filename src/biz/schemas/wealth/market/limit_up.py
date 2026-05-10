from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PageStatusValue = Literal["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"]
SessionStatusValue = Literal["PRE_OPEN", "TRADING", "BREAK", "CLOSED"]
SeverityValue = Literal["info", "warn", "error"]
DirectionValue = Literal["UP", "DOWN", "FLAT", "UNKNOWN"]
LimitSummaryCardKey = Literal[
    "limitUpCount",
    "limitDownCount",
    "brokenLimitCount",
    "sealingRate",
    "streakCount",
    "maxBoard",
    "skyToFloorCount",
    "floorToSkyCount",
]


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


class LimitUpDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[ModuleStatusItemDto]
    exceptions: list[ModuleExceptionItemDto]


class LimitSummaryCardItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: LimitSummaryCardKey
    label: str
    value: str | int | float | None
    unit: str | None = None
    direction: DirectionValue
    subText: str | None = None


class LimitSectorItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sectorCode: str
    sectorName: str
    sectorType: Literal["CONCEPT", "INDUSTRY", "REGION", "OTHER"]
    limitUpCount: int = Field(ge=0)


class LimitLeaderPerformanceItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stockCode: str
    stockName: str | None = None
    latestPrice: float | None = None
    changePct: float | None = None
    rank: int = Field(ge=1)
    streakLabel: str
    recentLimitText: str
    firstLimitTime: str
    openTimes: int = Field(ge=0)
    sealedAmountDisplayText: str


class LimitStructureBlockDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    selectedSectorCode: str
    selectedStockCode: str
    sectors: list[LimitSectorItemDto]
    leaderStocks: dict[str, list[LimitLeaderPerformanceItemDto]]


class LimitHistoryPointDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    limitUpCount: int = Field(ge=0)
    limitDownCount: int = Field(ge=0)


class LimitHistoryByRangeDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    oneMonth: list[LimitHistoryPointDto]
    threeMonth: list[LimitHistoryPointDto]


class LimitUpPayloadDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    summaryCards: list[LimitSummaryCardItemDto] = Field(min_length=8, max_length=8)
    todayStructure: LimitStructureBlockDto
    yesterdayStructure: LimitStructureBlockDto
    historyPoints: LimitHistoryByRangeDto


class LimitUpSummaryResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradingDay: TradingDayDto
    pageStatus: PageStatusDto
    limitUp: LimitUpPayloadDto
    debugInfo: LimitUpDebugInfoDto | None = None
