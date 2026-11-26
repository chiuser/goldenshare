from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat


class MajorEtfTrendPointDto(BaseModel):
    tradeDate: date
    amountYuan: FiniteFloat | None


class MajorEtfQuoteDto(BaseModel):
    tsCode: str
    name: str | None
    closePrice: FiniteFloat | None
    priceChangePct: FiniteFloat | None
    amountYuan: FiniteFloat | None


class MajorEtfMonitorResponseDto(BaseModel):
    status: Literal["ready", "empty"]
    tradeDate: date | None = None
    oneMonthStartDate: date | None = None
    trend: list[MajorEtfTrendPointDto] = Field(default_factory=list)
    quotes: list[MajorEtfQuoteDto] = Field(default_factory=list)
