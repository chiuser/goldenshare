from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PageStatusValue = Literal["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"]
SessionStatusValue = Literal["PRE_OPEN", "TRADING", "BREAK", "CLOSED"]
SeverityValue = Literal["info", "warn", "error"]
DirectionValue = Literal["UP", "DOWN", "FLAT", "UNKNOWN"]
BoardKeyValue = Literal["gainers", "losers", "amount", "turnover", "volumeRatio", "popularity", "surge"]


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


class LeaderboardDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[ModuleStatusItemDto]
    exceptions: list[ModuleExceptionItemDto]


class LeaderboardDefinitionDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boardKey: BoardKeyValue
    boardLabel: str


class LeaderboardSubjectDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subjectType: Literal["stock"]
    subjectCode: str
    subjectName: str | None = None


class LeaderboardMetricsDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latestPrice: float | None = None
    changePct: float | None = None
    turnoverRate: float | None = None
    volumeRatio: float | None = None
    volume: float | None = None
    amount: float | None = None
    direction: DirectionValue = "UNKNOWN"


class LeaderboardRowDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    subject: LeaderboardSubjectDto
    metrics: LeaderboardMetricsDto


class LeaderboardBoardDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boardKey: BoardKeyValue
    boardLabel: str
    status: PageStatusValue
    expectedTradeDate: date
    observedTradeDate: date | None = None
    lagDays: int | None = None
    rows: list[LeaderboardRowDto]


class LeaderboardsResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradingDay: TradingDayDto
    pageStatus: PageStatusDto
    definitions: list[LeaderboardDefinitionDto]
    boards: list[LeaderboardBoardDto]
    debugInfo: LeaderboardDebugInfoDto | None = None
