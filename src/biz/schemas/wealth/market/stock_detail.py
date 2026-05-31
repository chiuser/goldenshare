from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.biz.schemas.wealth.market.context import MarketPageContextDto


StockDetailStatusValue = Literal["READY", "DELAYED", "EMPTY", "ERROR"]
StockDirectionValue = Literal["UP", "DOWN", "FLAT", "UNKNOWN"]


class StockDetailDataStatusDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: StockDetailStatusValue
    expectedTradeDate: date
    observedTradeDate: date | None = None
    note: str | None = None


class StockDetailStockIdentityDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tsCode: str
    symbol: str | None = None
    name: str
    market: str | None = None
    exchange: str | None = None
    industry: str | None = None
    area: str | None = None
    listStatus: str | None = None
    tags: list[str] = Field(default_factory=list)


class StockDetailStockRefDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tsCode: str
    name: str | None = None


class StockQuoteSnapshotDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    price: float | None = None
    change: float | None = None
    changePct: float | None = None
    direction: StockDirectionValue
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    preClose: float | None = None
    turnoverRate: float | None = None
    volumeRatio: float | None = None
    vol: float | None = None
    amount: float | None = None


class StockChartDefaultsDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaultPeriod: Literal["day"] = "day"
    defaultAdjustment: Literal["forward"] = "forward"
    sourceAdjustment: Literal["qfq"] = "qfq"
    availablePeriods: list[Literal["day"]] = Field(default_factory=lambda: ["day"])
    availableAdjustments: list[Literal["forward"]] = Field(default_factory=lambda: ["forward"])
    availableMainOverlays: list[Literal["MA", "BOLL"]] = Field(default_factory=lambda: ["MA", "BOLL"])
    availableIndicatorTabs: list[Literal["VOL", "amount", "MA", "MACD", "KDJ", "BOLL"]] = Field(
        default_factory=lambda: ["VOL", "amount", "MA", "MACD", "KDJ", "BOLL"]
    )


class StockDetailCapabilitiesDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supportsRealtime: bool = False
    supportsMinute: bool = False
    supportsWeeklyMonthly: bool = False
    supportsUserActions: bool = False
    unsupportedActions: list[str] = Field(default_factory=lambda: ["自选", "提醒", "交易计划", "诊股"])


class StockMovingAverageDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ma5: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    ma30: float | None = None
    ma60: float | None = None
    ma90: float | None = None
    ma250: float | None = None


class StockBollDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upper: float | None = None
    middle: float | None = None
    lower: float | None = None


class StockMacdDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dif: float | None = None
    dea: float | None = None
    macd: float | None = None


class StockKdjDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    k: float | None = None
    d: float | None = None
    j: float | None = None


class StockKlineFactorDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ma: StockMovingAverageDto
    boll: StockBollDto
    macd: StockMacdDto
    kdj: StockKdjDto


class StockKlineBarDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    preClose: float | None = None
    change: float | None = None
    changePct: float | None = None
    vol: float | None = None
    amount: float | None = None
    turnoverRate: float | None = None
    volumeRatio: float | None = None
    factors: StockKlineFactorDto


class StockKlineMetaDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    limit: int
    startDate: date | None = None
    endDate: date | None = None


class StockDetailDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sourceTables: list[str]
    sourceAdjustment: Literal["qfq"] = "qfq"
    query: dict[str, str | int | None] = Field(default_factory=dict)


class StockDetailPageInitResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pageContext: MarketPageContextDto
    stock: StockDetailStockIdentityDto
    quote: StockQuoteSnapshotDto | None = None
    chartDefaults: StockChartDefaultsDto
    capabilities: StockDetailCapabilitiesDto
    dataStatus: StockDetailDataStatusDto
    debugInfo: StockDetailDebugInfoDto | None = None


class StockDetailKlineResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pageContext: MarketPageContextDto
    stockRef: StockDetailStockRefDto
    period: Literal["day"]
    adjustment: Literal["forward"]
    sourceAdjustment: Literal["qfq"]
    bars: list[StockKlineBarDto]
    meta: StockKlineMetaDto
    dataStatus: StockDetailDataStatusDto
    debugInfo: StockDetailDebugInfoDto | None = None
