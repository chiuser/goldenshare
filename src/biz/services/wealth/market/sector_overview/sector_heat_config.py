from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from src.biz.services.wealth.config import SectorOverviewHeatStrategyPayload, StrategyConfigService


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return format(normalized, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def canonical_json_hash(value: Any) -> str:
    payload = json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ResolvedSectorHeatConfig:
    version: str
    payload: SectorOverviewHeatStrategyPayload
    config_hash: str


class SectorHeatConfigResolver:
    def __init__(self, strategy_config_service: StrategyConfigService | None = None) -> None:
        self._strategy_config_service = strategy_config_service or StrategyConfigService()

    def resolve(self, *, market: str = "CN_A") -> ResolvedSectorHeatConfig:
        record = self._strategy_config_service.get_config(module_key="sectorOverview", market=market)
        if not isinstance(record.payload, SectorOverviewHeatStrategyPayload):
            raise TypeError("sectorOverview strategy config resolved to an unexpected payload type")
        canonical_payload = record.payload.model_dump(mode="python", by_alias=True)
        return ResolvedSectorHeatConfig(
            version=record.version,
            payload=record.payload,
            config_hash=canonical_json_hash(canonical_payload),
        )
