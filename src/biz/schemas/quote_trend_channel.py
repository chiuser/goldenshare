from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


TrendChannelPosition = Literal["ABOVE", "INSIDE", "BELOW"]
TrendChannelState = Literal["UNKNOWN", "UP", "DOWN"]
TrendChannelCombinedState = Literal[
    "UNKNOWN",
    "UP_UP",
    "UP_DOWN",
    "DOWN_UP",
    "DOWN_DOWN",
]


class TrendChannelInstrumentDto(BaseModel):
    ts_code: Literal["000001.SH"]
    name: str
    security_type: Literal["index"] = "index"


class TrendChannelFormulaDto(BaseModel):
    key: Literal["high-low-ema-hysteresis"]
    version: Literal["sse-daily-trend-channel-v1"]
    short_period: Literal[25]
    long_period: Literal[90]
    seed: Literal["first_observation"]
    state_rule: Literal["strict_close_breakout_inside_retention"]


class TrendChannelBandDto(BaseModel):
    upper: Decimal
    lower: Decimal
    position: TrendChannelPosition
    state: TrendChannelState


class TrendChannelBarDto(BaseModel):
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    short_channel: TrendChannelBandDto
    long_channel: TrendChannelBandDto
    combined_state: TrendChannelCombinedState
    is_provisional: Literal[False] = False


class TrendChannelDataStatusDto(BaseModel):
    status: Literal["READY", "EMPTY"]
    observed_trade_date: date | None
    as_of_time: datetime
    is_provisional: Literal[False] = False
    note: str | None = None


class TrendChannelMetaDto(BaseModel):
    bar_count: int
    limit: int
    start_date: date | None
    end_date: date | None
    has_more_history: bool
    next_end_date: date | None


class TrendChannelResponse(BaseModel):
    instrument: TrendChannelInstrumentDto
    period: Literal["day"] = "day"
    adjustment: Literal["none"] = "none"
    formula: TrendChannelFormulaDto
    data_status: TrendChannelDataStatusDto
    bars: list[TrendChannelBarDto]
    meta: TrendChannelMetaDto
