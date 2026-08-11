from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


IndexMinuteFrequency = Literal[1, 5, 15, 30, 60, 90, 120]
IndexMinuteStatusValue = Literal["READY", "DELAYED", "EMPTY"]
IndexMinuteStatusCode = Literal["IM_SOURCE_NOT_READY"]


class IndexMinutePageMetaDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    limit: int
    hasMore: bool
    nextCursor: str | None
    startDate: date | None
    endDate: date | None
    observedStartDate: date | None
    observedEndDate: date | None


class IndexMinuteDataStatusDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: IndexMinuteStatusValue
    code: IndexMinuteStatusCode | None
    expectedEndDate: date | None
    observedEndDate: date | None
    message: str | None


class IndexMinuteBarDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tsCode: str
    freq: IndexMinuteFrequency
    tradeDate: date
    tradeTime: datetime
    open: float
    high: float
    low: float
    close: float
    vol: float
    amount: float
    exchange: str


class IndexMinuteIndicatorDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tsCode: str
    freq: IndexMinuteFrequency
    tradeDate: date
    tradeTime: datetime
    ma5: float | None
    ma10: float | None
    ma20: float | None
    ma30: float | None
    ma60: float | None
    ma90: float | None
    ma250: float | None
    bollMiddle: float | None
    bollUpper: float | None
    bollLower: float | None
    macdDif: float | None
    macdDea: float | None
    macd: float | None
    kdjK: float | None
    kdjD: float | None
    kdjJ: float | None
    observationCount: int
    paramsKey: str
    indicatorVersion: int


class IndexMinutesResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tsCode: str
    freq: IndexMinuteFrequency
    bars: list[IndexMinuteBarDto]
    meta: IndexMinutePageMetaDto
    dataStatus: IndexMinuteDataStatusDto


class IndexMinuteIndicatorsResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tsCode: str
    freq: IndexMinuteFrequency
    items: list[IndexMinuteIndicatorDto]
    meta: IndexMinutePageMetaDto
    dataStatus: IndexMinuteDataStatusDto
