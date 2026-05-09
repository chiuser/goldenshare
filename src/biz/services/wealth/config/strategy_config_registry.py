from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from pydantic import BaseModel

from .strategy_config_models import (
    LeaderboardStrategyPayload,
    MajorIndicesStrategyPayload,
    MarketStyleStrategyPayload,
    MarketSummaryStrategyPayload,
    StrategyConfigRegistrationError,
)

StrategyConfigKey: TypeAlias = tuple[str, str]


@dataclass(frozen=True, slots=True)
class StrategyConfigRegistration:
    module_key: str
    market: str
    definition_file: str
    payload_model: type[BaseModel]


def get_default_definitions_dir() -> Path:
    return Path(__file__).resolve().parent / "definitions"


def get_default_strategy_config_registrations() -> tuple[StrategyConfigRegistration, ...]:
    return (
        StrategyConfigRegistration(
            module_key="majorIndices",
            market="CN_A",
            definition_file="major_indices.cn_a.v1.json",
            payload_model=MajorIndicesStrategyPayload,
        ),
        StrategyConfigRegistration(
            module_key="leaderboards",
            market="CN_A",
            definition_file="leaderboard.cn_a.v1.json",
            payload_model=LeaderboardStrategyPayload,
        ),
        StrategyConfigRegistration(
            module_key="marketSummary",
            market="CN_A",
            definition_file="market_summary.cn_a.v1.json",
            payload_model=MarketSummaryStrategyPayload,
        ),
        StrategyConfigRegistration(
            module_key="marketStyle",
            market="CN_A",
            definition_file="market_style.cn_a.v1.json",
            payload_model=MarketStyleStrategyPayload,
        ),
    )


def build_strategy_config_registration_index(
    registrations: tuple[StrategyConfigRegistration, ...] | list[StrategyConfigRegistration],
) -> dict[StrategyConfigKey, StrategyConfigRegistration]:
    index: dict[StrategyConfigKey, StrategyConfigRegistration] = {}
    for registration in registrations:
        module_key = registration.module_key.strip()
        market = registration.market.strip()
        if not module_key or not market:
            raise StrategyConfigRegistrationError("module_key/market must not be empty")
        if not registration.definition_file.strip():
            raise StrategyConfigRegistrationError(f"{module_key}/{market} definition_file must not be empty")
        key = (module_key, market)
        if key in index:
            raise StrategyConfigRegistrationError(f"duplicate strategy config registration: {module_key}/{market}")
        index[key] = registration
    return index
