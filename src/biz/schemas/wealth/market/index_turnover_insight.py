from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


IndexTurnoverInsightStatus = Literal["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"]
IndexTurnoverInsightItemStatus = Literal["READY", "PARTIAL", "EMPTY", "ERROR"]
IndexTurnoverInsightDirection = Literal["up", "down", "flat", "neutral"]


class _StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IndexTurnoverInsightTradingDayDto(_StrictDto):
    market: Literal["CN_A"]
    expectedTradeDate: date
    observedTradeDate: date | None = None
    previousObservedTradeDate: date | None = None
    isTradingDay: bool
    sessionStatus: Literal["PRE_OPEN", "TRADING", "BREAK", "CLOSED"]
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    generatedAt: datetime


class IndexTurnoverInsightAmountDto(_StrictDto):
    amountYi: int | None = None
    displayText: str
    direction: IndexTurnoverInsightDirection


class IndexTurnoverInsightAverageAmountDto(IndexTurnoverInsightAmountDto):
    referenceLabel: str


class IndexTurnoverInsightSummaryDto(_StrictDto):
    current: IndexTurnoverInsightAmountDto
    previous: IndexTurnoverInsightAmountDto
    delta: IndexTurnoverInsightAmountDto
    avg5d: IndexTurnoverInsightAverageAmountDto
    avg20d: IndexTurnoverInsightAverageAmountDto


class IndexTurnoverInsightAxisTickDto(_StrictDto):
    valueYi: int
    displayText: str


class IndexTurnoverInsightValueAxisDto(_StrictDto):
    minYi: int
    maxYi: int
    zeroYi: int | None = None
    ticks: list[IndexTurnoverInsightAxisTickDto]


class IndexTurnoverInsightSeriesPointDto(_StrictDto):
    time: str
    showAxisLabel: bool
    currentAmountYi: int | None = None
    currentDisplayText: str
    previousAmountYi: int | None = None
    previousDisplayText: str
    deltaAmountYi: int | None = None
    deltaDisplayText: str
    deltaDirection: Literal["up", "down", "flat"]


class IndexTurnoverInsightExceptionDto(_StrictDto):
    module: Literal["indexTurnoverInsight"] = "indexTurnoverInsight"
    code: str
    severity: Literal["info", "warn", "error"]
    message: str
    details: dict[str, str | int | float | None] | None = None


class IndexTurnoverInsightDebugInfoDto(_StrictDto):
    candidateTradeDateCount: int
    scannedFileCount: int
    scannedRowCount: int
    exceptions: list[IndexTurnoverInsightExceptionDto]


class IndexTurnoverInsightPanelDto(_StrictDto):
    tsCode: str
    indexName: str
    status: IndexTurnoverInsightItemStatus
    summary: IndexTurnoverInsightSummaryDto
    upperAxis: IndexTurnoverInsightValueAxisDto | None = None
    deltaAxis: IndexTurnoverInsightValueAxisDto | None = None
    series: list[IndexTurnoverInsightSeriesPointDto]
    message: str | None = None
    exceptionCode: str | None = None

    @model_validator(mode="after")
    def validate_state_contract(self) -> "IndexTurnoverInsightPanelDto":
        if self.status == "READY":
            if (
                len(self.series) != 241
                or self.upperAxis is None
                or self.deltaAxis is None
                or self.summary.avg5d.amountYi is None
                or self.summary.avg20d.amountYi is None
            ):
                raise ValueError("ready index panel requires complete series, axes and averages")
        elif self.status == "PARTIAL":
            comparison = (
                len(self.series) == 241
                and self.upperAxis is not None
                and self.deltaAxis is not None
                and any(
                    average.amountYi is None
                    for average in (self.summary.avg5d, self.summary.avg20d)
                )
            )
            current_only = (
                len(self.series) == 241
                and self.upperAxis is not None
                and self.deltaAxis is None
                and all(
                    point.previousAmountYi is None and point.deltaAmountYi is None
                    for point in self.series
                )
            )
            if not comparison and not current_only:
                raise ValueError("partial index panel has an invalid structural shape")
        elif self.series or self.upperAxis is not None or self.deltaAxis is not None:
            raise ValueError("empty and error index panels cannot contain chart data")
        return self


class IndexTurnoverInsightResponseDto(_StrictDto):
    status: IndexTurnoverInsightStatus
    tradingDay: IndexTurnoverInsightTradingDayDto
    asOf: str | None = None
    unit: Literal["yi"] = "yi"
    unitLabel: Literal["亿"] = "亿"
    indices: list[IndexTurnoverInsightPanelDto]
    message: str | None = None
    exceptionCode: str | None = None
    debugInfo: IndexTurnoverInsightDebugInfoDto | None = None

    @model_validator(mode="after")
    def validate_root_contract(self) -> "IndexTurnoverInsightResponseDto":
        if len(self.indices) != 10:
            raise ValueError("index turnover insight response must contain exactly 10 panels")
        identities = [(item.tsCode, item.indexName) for item in self.indices]
        if len(set(identities)) != 10:
            raise ValueError("index turnover insight panel identities must be unique")
        observed = self.tradingDay.observedTradeDate
        expected = self.tradingDay.expectedTradeDate
        if self.status == "DELAYED":
            if observed is None or observed == expected:
                raise ValueError("delayed response requires an earlier observed date")
        elif self.status in {"READY", "PARTIAL"}:
            if observed != expected:
                raise ValueError("ready and partial responses must use the expected date")
        if any(item.status == "READY" for item in self.indices):
            if self.tradingDay.previousObservedTradeDate is None:
                raise ValueError("complete panels require a previous observed date")
        if self.asOf is not None:
            expected_as_of = f"盘后数据 · {observed.isoformat()}" if observed else None
            if self.asOf != expected_as_of:
                raise ValueError("asOf must describe the observed trade date")
        return self
