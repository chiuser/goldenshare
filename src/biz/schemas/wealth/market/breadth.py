from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class BreadthMetricsDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upCount: int = Field(ge=0)
    downCount: int = Field(ge=0)
    flatCount: int = Field(ge=0)
    redRate: float = Field(ge=0, le=100)


class BreadthHistoryPointDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    upCount: int = Field(ge=0)
    downCount: int = Field(ge=0)


class BreadthPayloadDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    metrics: BreadthMetricsDto
    historyByRange: dict[str, list[BreadthHistoryPointDto]]

    @model_validator(mode="after")
    def _validate_history_ranges(self) -> "BreadthPayloadDto":
        expected = {"1m", "3m"}
        keys = set(self.historyByRange.keys())
        if keys != expected:
            raise ValueError("historyByRange must contain exact keys: 1m, 3m")
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


class BreadthDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[ModuleStatusItemDto]
    exceptions: list[ModuleExceptionItemDto]


class BreadthResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradingDay: TradingDayDto
    pageStatus: PageStatusDto
    breadth: BreadthPayloadDto
    debugInfo: BreadthDebugInfoDto | None = None
