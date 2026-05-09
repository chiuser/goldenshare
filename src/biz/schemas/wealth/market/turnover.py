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


class TurnoverMetricsDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    todayAmount: float | None = None
    prevAmount: float | None = None
    amountDelta: float | None = None
    amountDeltaPct: float | None = None
    avg5dAmount: float | None = None
    avg20dAmount: float | None = None
    unit: Literal["thousand_yuan"] = "thousand_yuan"


class TurnoverIntradayPointDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: str
    cumAmount: float | None = None


class TurnoverHistoryPointDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    amount: float | None = None


class TurnoverPayloadDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    metrics: TurnoverMetricsDto
    intradayCumulative: list[TurnoverIntradayPointDto] = Field(min_length=5, max_length=5)
    historyByRange: dict[str, list[TurnoverHistoryPointDto]]

    @model_validator(mode="after")
    def _validate_history_ranges(self) -> "TurnoverPayloadDto":
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


class TurnoverDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[ModuleStatusItemDto]
    exceptions: list[ModuleExceptionItemDto]


class TurnoverResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradingDay: TradingDayDto
    pageStatus: PageStatusDto
    turnover: TurnoverPayloadDto
    debugInfo: TurnoverDebugInfoDto | None = None
