from __future__ import annotations

from dataclasses import dataclass
import re

from src.biz.services.wealth.config import (
    MajorIndicesStrategyPayload,
    StrategyConfigError,
    StrategyConfigService,
)


_INDEX_CODE_PATTERN = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")


class IndexDetailRequestError(ValueError):
    """Raised when an index-detail request cannot be normalized."""


class IndexDetailNotFoundError(ValueError):
    """Raised when an index is outside the configured detail universe."""


class IndexDetailQueryError(RuntimeError):
    """Raised when configuration, source, or mapping execution fails."""


@dataclass(frozen=True, slots=True)
class IndexDetailUniverse:
    config_version: str
    ordered_codes: tuple[str, ...]

    def contains(self, ts_code: str) -> bool:
        return ts_code in self.ordered_codes


class IndexDetailUniverseService:
    """Resolve the only supported index-detail universe from strategy config."""

    def __init__(self, *, config_service: StrategyConfigService | None = None) -> None:
        self._config_service = config_service or StrategyConfigService()

    @staticmethod
    def normalize_ts_code(raw_ts_code: str | None) -> str:
        ts_code = (raw_ts_code or "").strip().upper()
        if not _INDEX_CODE_PATTERN.fullmatch(ts_code):
            raise IndexDetailRequestError("tsCode 必须是 6 位代码和 SH/SZ/BJ 市场后缀")
        return ts_code

    def load_universe(self) -> IndexDetailUniverse:
        try:
            record = self._config_service.get_config(module_key="majorIndices", market="CN_A")
        except StrategyConfigError as exc:
            raise IndexDetailQueryError("指数详情名单配置不可用") from exc
        if not isinstance(record.payload, MajorIndicesStrategyPayload):
            raise IndexDetailQueryError("指数详情名单配置类型不正确")
        return IndexDetailUniverse(
            config_version=record.version,
            ordered_codes=tuple(record.payload.index_codes),
        )

    def require_supported(self, ts_code: str) -> IndexDetailUniverse:
        universe = self.load_universe()
        if not universe.contains(ts_code):
            raise IndexDetailNotFoundError(f"指数不在详情页支持名单中：{ts_code}")
        return universe
