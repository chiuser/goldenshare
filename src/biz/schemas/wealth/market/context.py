from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


SessionStatusValue = Literal["PRE_OPEN", "TRADING", "BREAK", "CLOSED"]


class MarketPageContextDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Literal["CN_A"]
    tradeDate: date
    prevTradeDate: date | None = None
    isTradingDay: bool
    sessionStatus: SessionStatusValue
    timezone: Literal["Asia/Shanghai"]
    generatedAt: datetime
    source: Literal["explicit", "default"]


class MarketPageContextResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pageContext: MarketPageContextDto
