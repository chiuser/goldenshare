from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


TrendPositionValue = Literal["ABOVE", "INSIDE", "BELOW"]
TrendStateValue = Literal["UNKNOWN", "UP", "DOWN"]
CombinedTrendStateValue = Literal[
    "UNKNOWN",
    "UP_UP",
    "UP_DOWN",
    "DOWN_UP",
    "DOWN_DOWN",
]


class StockTrendChannelStockRefDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tsCode: str
    name: str | None = None


class StockTrendChannelFormulaDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Literal["high-low-ema-hysteresis"]
    version: Literal["stock-daily-trend-channel-v1"]
    shortPeriod: Literal[25]
    longPeriod: Literal[90]
    seed: Literal["first_observation"]
    stateRule: Literal["strict_close_breakout_inside_retention"]


class StockTrendChannelBandDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upper: float
    lower: float
    position: TrendPositionValue
    state: TrendStateValue


class StockTrendChannelBarDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    open: float
    high: float
    low: float
    close: float
    shortChannel: StockTrendChannelBandDto
    longChannel: StockTrendChannelBandDto
    combinedState: CombinedTrendStateValue


class StockTrendChannelMetaDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    limit: int
    endDate: date


class StockTrendChannelDataStatusDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["READY", "EMPTY"]
    observedTradeDate: date | None = None
    note: str | None = None


class StockTrendChannelResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stockRef: StockTrendChannelStockRefDto
    period: Literal["day"] = "day"
    adjustment: Literal["forward"] = "forward"
    sourceAdjustment: Literal["qfq"] = "qfq"
    formula: StockTrendChannelFormulaDto
    bars: list[StockTrendChannelBarDto]
    meta: StockTrendChannelMetaDto
    dataStatus: StockTrendChannelDataStatusDto
