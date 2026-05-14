from __future__ import annotations

from dataclasses import dataclass

from src.biz.services.wealth.config import (
    MarketNewsStrategyPayload,
    StrategyConfigService,
    StrategyConfigValidationError,
)


@dataclass(frozen=True, slots=True)
class MarketNewsStrategyConfig:
    version: str
    visible_item_count: int
    query_limit: int


class MarketNewsStrategyConfigResolver:
    """Read and validate market news strategy config."""

    def __init__(self) -> None:
        self._config_service = StrategyConfigService()

    def resolve(self, *, market: str) -> MarketNewsStrategyConfig:
        payload = self._config_service.get_payload(module_key="marketNews", market=market)
        if not isinstance(payload, MarketNewsStrategyPayload):
            raise StrategyConfigValidationError("marketNews payload model mismatch")
        return MarketNewsStrategyConfig(
            version=self._config_service.get_version(module_key="marketNews", market=market),
            visible_item_count=payload.visible_item_count,
            query_limit=payload.query_limit,
        )
