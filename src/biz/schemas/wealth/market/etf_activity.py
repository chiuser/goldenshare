from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat


class EtfActivityTrendPointDto(BaseModel):
    tradeDate: date
    amountYuan: FiniteFloat | None
    ma5Yuan: FiniteFloat | None
    ma20Yuan: FiniteFloat | None


class EtfActivityRankRowDto(BaseModel):
    rank: int
    tsCode: str
    name: str | None
    closePrice: FiniteFloat
    priceChangePct: FiniteFloat
    amountYuan: FiniteFloat
    rankChange: int | None


class EtfActivityRankErrorDto(BaseModel):
    code: Literal["ETF_ACTIVITY_RANKING_UNAVAILABLE"] = "ETF_ACTIVITY_RANKING_UNAVAILABLE"
    message: str = "ETF 排行榜暂不可读取，请重试"


class EtfActivityRankingDto(BaseModel):
    status: Literal["ready", "partial", "empty", "error"]
    rows: list[EtfActivityRankRowDto] = Field(default_factory=list)
    error: EtfActivityRankErrorDto | None = None


class EtfActivityResponseDto(BaseModel):
    tradeDate: date | None = None
    previousTradeDate: date | None = None
    oneMonthStartDate: date | None = None
    trend: list[EtfActivityTrendPointDto] = Field(default_factory=list)
    ranking: EtfActivityRankingDto
