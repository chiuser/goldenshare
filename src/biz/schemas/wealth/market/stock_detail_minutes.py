from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MinuteFrequency = Literal[1, 5, 15, 30, 60, 90, 120]
MinuteStatus = Literal["READY", "DELAYED", "EMPTY", "ERROR"]


class MinutePageMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    count: int
    limit: int
    has_more: bool = Field(alias="hasMore")
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    start_date: date | None = Field(default=None, alias="startDate")
    end_date: date | None = Field(default=None, alias="endDate")
    observed_start_date: date | None = Field(default=None, alias="observedStartDate")
    observed_end_date: date | None = Field(default=None, alias="observedEndDate")


class MinuteDataStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: MinuteStatus
    expected_end_date: date | None = Field(default=None, alias="expectedEndDate")
    observed_end_date: date | None = Field(default=None, alias="observedEndDate")
    message: str | None = None


class StockMinuteBarDto(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ts_code: str = Field(alias="tsCode")
    freq: MinuteFrequency
    trade_date: date = Field(alias="tradeDate")
    trade_time: datetime = Field(alias="tradeTime")
    open: float
    high: float
    low: float
    close: float
    vol: float
    amount: float
    exchange: str


class StockMinuteIndicatorDto(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ts_code: str = Field(alias="tsCode")
    freq: MinuteFrequency
    trade_date: date = Field(alias="tradeDate")
    trade_time: datetime = Field(alias="tradeTime")
    macd_dif: float | None = Field(default=None, alias="macdDif")
    macd_dea: float | None = Field(default=None, alias="macdDea")
    macd: float | None = None
    kdj_k: float | None = Field(default=None, alias="kdjK")
    kdj_d: float | None = Field(default=None, alias="kdjD")
    kdj_j: float | None = Field(default=None, alias="kdjJ")
    params_key: str = Field(alias="paramsKey")
    indicator_version: int = Field(alias="indicatorVersion")


class StockMinutesResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ts_code: str = Field(alias="tsCode")
    freq: MinuteFrequency
    bars: list[StockMinuteBarDto]
    meta: MinutePageMeta
    data_status: MinuteDataStatus = Field(alias="dataStatus")
    debug_info: dict[str, Any] | None = Field(default=None, alias="debugInfo")


class StockMinuteIndicatorsResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ts_code: str = Field(alias="tsCode")
    freq: MinuteFrequency
    items: list[StockMinuteIndicatorDto]
    meta: MinutePageMeta
    data_status: MinuteDataStatus = Field(alias="dataStatus")
    debug_info: dict[str, Any] | None = Field(default=None, alias="debugInfo")
