from __future__ import annotations

from dataclasses import dataclass

from src.biz.services.wealth.config import (
    LeaderboardStrategyPayload,
    StrategyConfigService,
    StrategyConfigValidationError,
)


_BOARD_LABELS: dict[str, str] = {
    "gainers": "涨幅榜",
    "losers": "跌幅榜",
    "amount": "成交额榜",
    "turnover": "换手榜",
    "volumeRatio": "量比榜",
    "popularity": "人气榜",
    "surge": "飙升榜",
}


@dataclass(frozen=True, slots=True)
class LeaderboardDefinition:
    board_key: str
    board_label: str


@dataclass(frozen=True, slots=True)
class LeaderboardStrategyConfig:
    version: str
    definitions: tuple[LeaderboardDefinition, ...]
    default_limit: int
    strict_hot_date: bool


class LeaderboardStrategyConfigResolver:
    """Read and validate leaderboard strategy config."""

    def __init__(self) -> None:
        self._config_service = StrategyConfigService()

    def resolve(self, *, market: str) -> LeaderboardStrategyConfig:
        payload = self._config_service.get_payload(module_key="leaderboards", market=market)
        if not isinstance(payload, LeaderboardStrategyPayload):
            raise StrategyConfigValidationError("leaderboards payload model mismatch")

        unknown_keys = [key for key in payload.board_keys if key not in _BOARD_LABELS]
        if unknown_keys:
            raise StrategyConfigValidationError(f"leaderboards contains unsupported board keys: {unknown_keys}")

        definitions = tuple(
            LeaderboardDefinition(
                board_key=board_key,
                board_label=_BOARD_LABELS[board_key],
            )
            for board_key in payload.board_keys
        )
        if not definitions:
            raise StrategyConfigValidationError("leaderboards boardKeys must not be empty")

        return LeaderboardStrategyConfig(
            version=self._config_service.get_version(module_key="leaderboards", market=market),
            definitions=definitions,
            default_limit=payload.default_limit,
            strict_hot_date=payload.strict_hot_date,
        )

