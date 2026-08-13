from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrategyConfigError(ValueError):
    """Base error for wealth strategy config loading/validation."""


class StrategyConfigNotFoundError(StrategyConfigError):
    """Raised when strategy config registration or file is missing."""


class StrategyConfigRegistrationError(StrategyConfigError):
    """Raised when config registrations are invalid."""


class StrategyConfigValidationError(StrategyConfigError):
    """Raised when config content fails strict validation."""


class StrategyConfigEnvelope(BaseModel):
    """Shared metadata envelope for all strategy config files."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    module_key: str = Field(alias="moduleKey", min_length=1)
    market: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    updated_at: datetime = Field(alias="updatedAt")
    updated_by: str = Field(alias="updatedBy", min_length=1)
    payload: dict[str, Any]

    @field_validator("module_key", "market", "updated_by")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("updated_at")
    @classmethod
    def _ensure_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("updatedAt must include timezone offset")
        return value


class MajorIndicesStrategyPayload(BaseModel):
    """Config payload for major indices module."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    index_codes: list[str] = Field(alias="indexCodes", min_length=10, max_length=10)

    @field_validator("index_codes")
    @classmethod
    def _validate_index_codes(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values]
        if any(not item for item in cleaned):
            raise ValueError("indexCodes must not contain empty code")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("indexCodes must not contain duplicates")
        return cleaned


class LeaderboardStrategyPayload(BaseModel):
    """Config payload for leaderboards module."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    board_keys: list[str] = Field(alias="boardKeys", min_length=1)
    default_limit: int = Field(alias="defaultLimit", ge=1, le=100)
    strict_hot_date: bool = Field(alias="strictHotDate")

    @field_validator("board_keys")
    @classmethod
    def _validate_board_keys(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values]
        if any(not item for item in cleaned):
            raise ValueError("boardKeys must not contain empty value")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("boardKeys must not contain duplicates")
        return cleaned


class MarketSummaryStrategyPayload(BaseModel):
    """Config payload for market summary module."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    card_count: Literal[5, 6] = Field(alias="cardCount")
    enabled_card_keys: list[str] = Field(alias="enabledCardKeys", min_length=5, max_length=6)
    intraday_template_key: str = Field(alias="intradayTemplateKey", min_length=1)
    close_template_key: str = Field(alias="closeTemplateKey", min_length=1)

    @field_validator("enabled_card_keys")
    @classmethod
    def _validate_enabled_card_keys(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values]
        if any(not item for item in cleaned):
            raise ValueError("enabledCardKeys must not contain empty value")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("enabledCardKeys must not contain duplicates")
        return cleaned

    @field_validator("intraday_template_key", "close_template_key")
    @classmethod
    def _validate_template_keys(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("template key must not be empty")
        return text

    @model_validator(mode="after")
    def _validate_card_count_alignment(self) -> "MarketSummaryStrategyPayload":
        if len(self.enabled_card_keys) != self.card_count:
            raise ValueError("enabledCardKeys length must equal cardCount")
        return self


class MarketStyleRangeConfig(BaseModel):
    """Range config for market style history windows."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    one_month_trading_days: int = Field(alias="oneMonthTradingDays", ge=1, le=250)
    three_month_trading_days: int = Field(alias="threeMonthTradingDays", ge=1, le=250)

    @model_validator(mode="after")
    def _validate_range_order(self) -> "MarketStyleRangeConfig":
        if self.three_month_trading_days < self.one_month_trading_days:
            raise ValueError("threeMonthTradingDays must be greater than or equal to oneMonthTradingDays")
        return self


class MarketStyleIndexCardSource(BaseModel):
    """Index card source config for style module."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source_type: Literal["index"] = Field(alias="sourceType")
    index_code: str = Field(alias="indexCode", min_length=1)
    label: str = Field(min_length=1)
    source_text: str = Field(alias="sourceText", min_length=1)

    @field_validator("index_code", "label", "source_text")
    @classmethod
    def _strip_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class MarketStyleMedianCardSource(BaseModel):
    """Median card source config for style module."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source_type: Literal["equity_median"] = Field(alias="sourceType")
    universe: Literal["CN_A_ALL"]
    label: str = Field(min_length=1)
    source_text: str = Field(alias="sourceText", min_length=1)

    @field_validator("label", "source_text")
    @classmethod
    def _strip_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class MarketStyleCardSources(BaseModel):
    """Three fixed card sources for style module."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    large_cap: MarketStyleIndexCardSource = Field(alias="largeCap")
    small_cap: MarketStyleIndexCardSource = Field(alias="smallCap")
    median: MarketStyleMedianCardSource


class MarketStyleStrategyPayload(BaseModel):
    """Config payload for market style module."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ranges: MarketStyleRangeConfig
    card_sources: MarketStyleCardSources = Field(alias="cardSources")


class LimitUpStrategyPayload(BaseModel):
    """Config payload for limit-up module."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    st_excluded_sector_codes: list[str] = Field(alias="stExcludedSectorCodes", min_length=1)
    recent_limit_window_days: int = Field(alias="recentLimitWindowDays", ge=1, le=60)

    @field_validator("st_excluded_sector_codes")
    @classmethod
    def _validate_excluded_sector_codes(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values]
        if any(not item for item in cleaned):
            raise ValueError("stExcludedSectorCodes must not contain empty code")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("stExcludedSectorCodes must not contain duplicates")
        return cleaned


class MarketNewsStrategyPayload(BaseModel):
    """Config payload for market news panels."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    visible_item_count: int = Field(alias="visibleItemCount", ge=1, le=50)
    query_limit: int = Field(alias="queryLimit", ge=300, le=2000)

    @model_validator(mode="after")
    def _validate_query_limit(self) -> "MarketNewsStrategyPayload":
        if self.query_limit < self.visible_item_count:
            raise ValueError("queryLimit must be greater than or equal to visibleItemCount")
        return self


def _validate_weight_sum(*values: Decimal) -> None:
    if sum(values, start=Decimal("0")) != Decimal("1"):
        raise ValueError("weights must sum to 1")


class SectorHeatMainWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    price_strength: Decimal = Field(alias="priceStrength", ge=0, le=1)
    breadth: Decimal = Field(ge=0, le=1)
    capital_flow: Decimal = Field(alias="capitalFlow", ge=0, le=1)
    activity: Decimal = Field(ge=0, le=1)
    persistence: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _validate_sum(self) -> "SectorHeatMainWeights":
        _validate_weight_sum(
            self.price_strength,
            self.breadth,
            self.capital_flow,
            self.activity,
            self.persistence,
        )
        return self


class SectorHeatPriceWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    daily_return: Decimal = Field(alias="dailyReturn", ge=0, le=1)
    relative_strength_5: Decimal = Field(alias="relativeStrength5", ge=0, le=1)
    daily_acceleration: Decimal = Field(alias="dailyAcceleration", ge=0, le=1)

    @model_validator(mode="after")
    def _validate_sum(self) -> "SectorHeatPriceWeights":
        _validate_weight_sum(self.daily_return, self.relative_strength_5, self.daily_acceleration)
        return self


class SectorHeatBreadthWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    up_ratio: Decimal = Field(alias="upRatio", ge=0, le=1)
    limit_up_ratio: Decimal = Field(alias="limitUpRatio", ge=0, le=1)

    @model_validator(mode="after")
    def _validate_sum(self) -> "SectorHeatBreadthWeights":
        _validate_weight_sum(self.up_ratio, self.limit_up_ratio)
        return self


class SectorHeatCapitalPersistenceWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    weight: Decimal = Field(ge=0, le=1)
    positive_day_ratio: Decimal = Field(alias="positiveDayRatio", ge=0, le=1)
    slope: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _validate_inner_sum(self) -> "SectorHeatCapitalPersistenceWeights":
        _validate_weight_sum(self.positive_day_ratio, self.slope)
        return self


class SectorHeatCapitalFlowWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    current: Decimal = Field(ge=0, le=1)
    persistence: SectorHeatCapitalPersistenceWeights

    @model_validator(mode="after")
    def _validate_outer_sum(self) -> "SectorHeatCapitalFlowWeights":
        _validate_weight_sum(self.current, self.persistence.weight)
        return self


class SectorHeatPersistenceWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    top_20_streak: Decimal = Field(alias="top20Streak", ge=0, le=1)
    rank_improvement: Decimal = Field(alias="rankImprovement", ge=0, le=1)

    @model_validator(mode="after")
    def _validate_sum(self) -> "SectorHeatPersistenceWeights":
        _validate_weight_sum(self.top_20_streak, self.rank_improvement)
        return self


class SectorHeatComponentWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    price: SectorHeatPriceWeights
    breadth: SectorHeatBreadthWeights
    capital_flow: SectorHeatCapitalFlowWeights = Field(alias="capitalFlow")
    persistence: SectorHeatPersistenceWeights


class SectorHeatLevelThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    boiling: Decimal = Field(ge=0, le=100)
    hot: Decimal = Field(ge=0, le=100)
    active: Decimal = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _validate_order(self) -> "SectorHeatLevelThresholds":
        if not self.boiling > self.hot > self.active:
            raise ValueError("level thresholds must be strictly descending")
        return self


class SectorHeatTrendThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    heating: Decimal = Field(gt=0)
    cooling: Decimal = Field(lt=0)


class SectorHeatWinsorThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    lower: Decimal = Field(ge=0, lt=1)
    upper: Decimal = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _validate_order(self) -> "SectorHeatWinsorThresholds":
        if self.lower >= self.upper:
            raise ValueError("winsor lower must be less than upper")
        return self


class SectorOverviewHeatStrategyPayload(BaseModel):
    """Strict EOD V1 concept-heat strategy contract."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    score_version: str = Field(alias="scoreVersion", min_length=1, max_length=64)
    weights: SectorHeatMainWeights
    component_weights: SectorHeatComponentWeights = Field(alias="componentWeights")
    level_thresholds: SectorHeatLevelThresholds = Field(alias="levelThresholds")
    trend_thresholds: SectorHeatTrendThresholds = Field(alias="trendThresholds")
    trend_confirmation_days: int = Field(alias="trendConfirmationDays", ge=1, le=10)
    min_member_count: int = Field(alias="minMemberCount", ge=1, le=10_000)
    min_quote_coverage: Decimal = Field(alias="minQuoteCoverage", gt=0, le=1)
    baseline_trading_days: int = Field(alias="baselineTradingDays", ge=1, le=250)
    flow_trading_days: int = Field(alias="flowTradingDays", ge=2, le=60)
    persistence_trading_days: int = Field(alias="persistenceTradingDays", ge=1, le=60)
    persistence_top_n: int = Field(alias="persistenceTopN", ge=1, le=1_000)
    winsor: SectorHeatWinsorThresholds

    @field_validator("score_version")
    @classmethod
    def _strip_score_version(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("scoreVersion must not be empty")
        return text

    @model_validator(mode="after")
    def _validate_window_alignment(self) -> "SectorOverviewHeatStrategyPayload":
        if self.baseline_trading_days < self.flow_trading_days:
            raise ValueError("baselineTradingDays must be greater than or equal to flowTradingDays")
        if self.trend_confirmation_days > self.persistence_trading_days + 1:
            raise ValueError("trendConfirmationDays exceeds the available persistence window")
        return self
