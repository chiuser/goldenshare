from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from qtf.contracts.runtime import DatasetEvidence
from qtf.modules.sector.factor_kernel import SectorObservation


SECTOR_L2_SOURCE_CONTRACT = {
    "source_kind": "PROD",
    "datasets": {
        "core_serving.trade_calendar": {
            "fields": ["exchange", "trade_date", "is_open", "pretrade_date"],
            "filter": {"exchange": "SSE", "is_open": True},
        },
        "core_serving.wealth_sector_hierarchy": {
            "fields": [
                "sector_code",
                "sector_name",
                "industry_level",
                "parent_sector_code",
                "root_sector_code",
                "display_order",
                "baseline_version",
                "published_at",
            ],
            "filter": {"industry_level": [1, 2], "publication": "current_unique"},
        },
        "core_serving.dc_daily": {
            "fields": ["ts_code", "trade_date", "category", "pct_change", "amount"],
            "filter": {"category": "行业板块", "universe": "published_l2"},
        },
    },
    "stable_order": ["trade_date", "ts_code"],
}
SECTOR_L2_UNIVERSE_SPEC = {
    "classification": "EASTMONEY",
    "industry_level": 2,
    "published_only": True,
}
SECTOR_L2_COMPARISON_SPEC = {
    "scope": "SIBLINGS",
    "parent_level": 1,
}


@dataclass(frozen=True, slots=True)
class SectorHierarchyNode:
    sector_code: str
    sector_name: str
    industry_level: int
    parent_sector_code: str | None
    root_sector_code: str
    display_order: int
    baseline_version: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class SectorInputRequest:
    start_date: date
    end_date: date
    history_trade_days: int = 0
    future_trade_days: int = 0
    statement_timeout_ms: int = 60_000


@dataclass(frozen=True, slots=True)
class SectorInputSnapshot:
    as_of: datetime
    trade_dates: tuple[date, ...]
    hierarchy: tuple[SectorHierarchyNode, ...]
    observations: tuple[SectorObservation, ...]
    dataset_evidence: tuple[DatasetEvidence, ...]
    content_hash: str
    source_contract_hash: str
