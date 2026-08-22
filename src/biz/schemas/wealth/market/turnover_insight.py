from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


TurnoverInsightStatus = Literal["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"]
TurnoverInsightDirection = Literal["up", "down", "flat", "neutral"]


class _StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TurnoverInsightTradingDayDto(_StrictDto):
    market: Literal["CN_A"]
    expectedTradeDate: date
    observedTradeDate: date | None = None
    previousObservedTradeDate: date | None = None
    isTradingDay: bool
    sessionStatus: Literal["PRE_OPEN", "TRADING", "BREAK", "CLOSED"]
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    generatedAt: datetime


class TurnoverInsightAmountDto(_StrictDto):
    amountYi: int | None = None
    displayText: str
    direction: TurnoverInsightDirection


class TurnoverInsightAverageAmountDto(TurnoverInsightAmountDto):
    referenceLabel: str


class TurnoverInsightSummaryDto(_StrictDto):
    current: TurnoverInsightAmountDto
    previous: TurnoverInsightAmountDto
    delta: TurnoverInsightAmountDto
    avg5d: TurnoverInsightAverageAmountDto
    avg20d: TurnoverInsightAverageAmountDto


class TurnoverInsightAxisTickDto(_StrictDto):
    valueYi: int
    displayText: str


class TurnoverInsightValueAxisDto(_StrictDto):
    minYi: int
    maxYi: int
    zeroYi: int | None = None
    ticks: list[TurnoverInsightAxisTickDto]


class TurnoverInsightSeriesPointDto(_StrictDto):
    time: str
    showAxisLabel: bool
    currentAmountYi: int | None = None
    currentDisplayText: str
    previousAmountYi: int | None = None
    previousDisplayText: str
    deltaAmountYi: int | None = None
    deltaDisplayText: str
    deltaDirection: Literal["up", "down", "flat"]


class TurnoverInsightExceptionDto(_StrictDto):
    module: Literal["turnoverInsight"] = "turnoverInsight"
    code: str
    severity: Literal["info", "warn", "error"]
    message: str
    details: dict[str, str | int | float | None] | None = None


class TurnoverInsightDebugInfoDto(_StrictDto):
    candidateCount: int
    exceptions: list[TurnoverInsightExceptionDto]


class TurnoverInsightResponseDto(_StrictDto):
    status: TurnoverInsightStatus
    tradingDay: TurnoverInsightTradingDayDto
    asOf: datetime | None = None
    unit: Literal["yi"] = "yi"
    unitLabel: Literal["亿"] = "亿"
    summary: TurnoverInsightSummaryDto
    upperAxis: TurnoverInsightValueAxisDto | None = None
    deltaAxis: TurnoverInsightValueAxisDto | None = None
    series: list[TurnoverInsightSeriesPointDto]
    message: str | None = None
    exceptionCode: str | None = None
    debugInfo: TurnoverInsightDebugInfoDto | None = None

    @model_validator(mode="after")
    def validate_state_contract(self) -> "TurnoverInsightResponseDto":
        if self.status in {"READY", "DELAYED"}:
            if len(self.series) != 241 or self.upperAxis is None or self.deltaAxis is None:
                raise ValueError("complete turnover insight states require 241 points and both axes")
            if self.tradingDay.previousObservedTradeDate is None:
                raise ValueError("complete turnover insight states require previous observed date")
        elif self.status == "PARTIAL":
            if len(self.series) != 241 or self.upperAxis is None or self.deltaAxis is not None:
                raise ValueError("partial turnover insight requires current-only series and upper axis")
            if any(point.previousAmountYi is not None or point.deltaAmountYi is not None for point in self.series):
                raise ValueError("partial turnover insight cannot contain previous or delta values")
        elif self.series:
            raise ValueError("empty and error turnover insight states cannot contain series")
        return self
