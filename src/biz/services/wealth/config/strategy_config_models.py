from __future__ import annotations

from datetime import datetime
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
    query_multiplier: int = Field(alias="queryMultiplier", ge=1, le=5)

    @property
    def query_limit(self) -> int:
        return self.visible_item_count * self.query_multiplier
