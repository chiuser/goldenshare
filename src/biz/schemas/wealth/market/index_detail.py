from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


IndexDetailDataStatusValue = Literal["READY", "DELAYED", "PARTIAL", "EMPTY"]
IndexDetailDirection = Literal["UP", "DOWN", "FLAT", "UNKNOWN"]
IndexDetailSeverity = Literal["info", "warn", "error"]
IndexDetailDebugModule = Literal["pageInit", "quote", "dailyBasic", "breadth", "kline", "weights"]
IndexDetailExceptionModule = Literal[
    "indexDetail",
    "indexDetailPageInit",
    "indexDetailKline",
    "indexDetailWeights",
]
IndexDetailExceptionCode = Literal[
    "ID_REQUEST_INVALID",
    "ID_NOT_FOUND",
    "ID_SOURCE_EMPTY",
    "ID_SOURCE_DELAYED",
    "ID_FACTOR_PARTIAL",
    "ID_BASIC_DAILY_PARTIAL",
    "ID_BASIC_BREADTH_PARTIAL",
    "ID_WEIGHT_EMPTY",
    "ID_WEIGHT_CONTRIBUTION_PARTIAL",
    "ID_QUERY_FAILED",
]
IndexDetailPeriod = Literal["day", "m1", "m5", "m15", "m30", "m60", "m90", "m120"]
IndexDetailMinuteFrequency = Literal[1, 5, 15, 30, 60, 90, 120]


class IndexDetailPageContextDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Literal["CN_A"]
    tradeDate: date
    prevTradeDate: date | None
    isTradingDay: bool
    sessionStatus: Literal["PRE_OPEN", "TRADING", "BREAK", "CLOSED"]
    timezone: Literal["Asia/Shanghai"]
    generatedAt: datetime
    source: Literal["explicit", "default"]


class IndexDetailDataStatusDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: IndexDetailDataStatusValue
    expectedTradeDate: date
    observedTradeDate: date | None


class IndexDetailModuleDebugDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: IndexDetailDebugModule
    status: IndexDetailDataStatusValue | Literal["ERROR"]
    expectedTradeDate: date
    observedTradeDate: date | None
    rowCount: int | None
    missingCount: int | None


class IndexDetailExceptionDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: IndexDetailExceptionModule
    code: IndexDetailExceptionCode
    severity: IndexDetailSeverity
    message: str


class IndexDetailDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[IndexDetailModuleDebugDto]
    exceptions: list[IndexDetailExceptionDto]


class IndexDetailIdentityDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tsCode: str
    name: str
    market: str | None
    category: str | None
    publisher: str | None
    tags: list[str]


class IndexDetailIndexRefDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tsCode: str
    name: str | None


class IndexDetailQuoteDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    point: float | None
    change: float | None
    changePct: float | None
    direction: IndexDetailDirection
    open: float | None
    high: float | None
    low: float | None
    preClose: float | None
    vol: float | None
    amount: float | None


class IndexDetailDailyBasicDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    pe: float | None
    peTtm: float | None
    pb: float | None
    turnoverRate: float | None
    floatMv: float | None
    totalMv: float | None


class IndexDetailConstituentBreadthDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    weightTradeDate: date
    upCount: int
    flatCount: int
    downCount: int
    totalConstituentCount: int
    matchedCount: int
    missingCount: int
    dataStatus: IndexDetailDataStatusDto


class IndexDetailChartDefaultsDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaultPeriod: Literal["day"]
    availablePeriods: list[IndexDetailPeriod]
    availableMainOverlays: list[Literal["MA", "BOLL", "TREND_CHANNEL"]]
    availableIndicatorTabs: list[Literal["VOL", "amount", "MA", "MACD", "KDJ", "BOLL"]]


class IndexDetailCapabilitiesDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supportsTimeShare: Literal[False]
    supportsWeeklyMonthly: Literal[False]
    supportsMinute: bool
    minuteFrequencies: list[IndexDetailMinuteFrequency]
    supportsTrendChannel: bool
    supportsNineTurn: Literal[False]
    supportsTechnicalConclusion: Literal[False]
    supportsTradePlanEntry: Literal[True]


class IndexDetailPageInitResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pageContext: IndexDetailPageContextDto
    asOfTradeDate: date | None
    index: IndexDetailIdentityDto
    quote: IndexDetailQuoteDto | None
    dailyBasic: IndexDetailDailyBasicDto | None
    constituentBreadth: IndexDetailConstituentBreadthDto | None
    chartDefaults: IndexDetailChartDefaultsDto
    capabilities: IndexDetailCapabilitiesDto
    dataStatus: IndexDetailDataStatusDto
    debugInfo: IndexDetailDebugInfoDto | None


class IndexMovingAverageDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ma5: float | None
    ma10: float | None
    ma20: float | None
    ma30: float | None
    ma60: float | None
    ma90: float | None
    ma250: float | None


class IndexBollDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upper: float | None
    middle: float | None
    lower: float | None


class IndexMacdDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dif: float | None
    dea: float | None
    macd: float | None


class IndexKdjDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    k: float | None
    d: float | None
    j: float | None


class IndexKlineFactorsDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ma: IndexMovingAverageDto
    boll: IndexBollDto
    macd: IndexMacdDto
    kdj: IndexKdjDto


class IndexKlineBarDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    preClose: float | None
    change: float | None
    changePct: float | None
    amplitude: float | None
    vol: float | None
    amount: float | None
    factors: IndexKlineFactorsDto


class IndexDetailKlineMetaDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    limit: int
    startDate: date | None
    endDate: date | None


class IndexDetailKlineResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pageContext: IndexDetailPageContextDto
    indexRef: IndexDetailIndexRefDto
    period: Literal["day"]
    bars: list[IndexKlineBarDto]
    meta: IndexDetailKlineMetaDto
    dataStatus: IndexDetailDataStatusDto
    debugInfo: IndexDetailDebugInfoDto | None


class IndexDetailWeightRowDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conCode: str
    name: str | None
    weight: float
    changePct: float | None
    contributionPoint: float | None
    direction: IndexDetailDirection


class IndexDetailWeightCoverageDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    totalCount: int
    returnedCount: int
    contributionAvailableCount: int
    contributionMissingCount: int
    isTruncated: Literal[False]


class IndexDetailWeightsResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indexRef: IndexDetailIndexRefDto
    contributionTradeDate: date
    weightTradeDate: date | None
    isEstimated: Literal[True]
    rows: list[IndexDetailWeightRowDto]
    coverage: IndexDetailWeightCoverageDto
    dataStatus: IndexDetailDataStatusDto
    note: Literal["基于最新月度权重估算，非指数公司官方归因"]
    debugInfo: IndexDetailDebugInfoDto | None
