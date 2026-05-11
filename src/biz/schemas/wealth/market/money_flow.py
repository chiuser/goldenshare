from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


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


class MoneyFlowMetricsDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    todayNetAmount: float | None = None
    prevNetAmount: float | None = None
    unit: Literal["yuan"] = "yuan"


class OrderSizeFlowItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: float | None = None
    rate: float | None = None


class OrderSizeFlowDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    elg: OrderSizeFlowItemDto
    lg: OrderSizeFlowItemDto
    md: OrderSizeFlowItemDto
    sm: OrderSizeFlowItemDto


class MoneyFlowHistoryPointDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    netAmount: float | None = None


class MoneyFlowPayloadDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    metrics: MoneyFlowMetricsDto
    byOrderSize: OrderSizeFlowDto
    historyByRange: dict[str, list[MoneyFlowHistoryPointDto]]

    @model_validator(mode="after")
    def _validate_history_ranges(self) -> "MoneyFlowPayloadDto":
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


class MoneyFlowDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[ModuleStatusItemDto]
    exceptions: list[ModuleExceptionItemDto]


class MoneyFlowResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradingDay: TradingDayDto
    pageStatus: PageStatusDto
    moneyFlow: MoneyFlowPayloadDto
    debugInfo: MoneyFlowDebugInfoDto | None = None
