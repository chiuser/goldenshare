from __future__ import annotations

from src.foundation.services.sync_v2.contracts import DatasetSyncContract
from src.foundation.services.sync_v2.registry_parts.contracts import (
    BOARD_HOTSPOT_CONTRACTS,
    INDEX_SERIES_CONTRACTS,
    LOW_FREQUENCY_CONTRACTS,
    MARKET_EQUITY_CONTRACTS,
    MARKET_FUND_CONTRACTS,
    MONEYFLOW_CONTRACTS,
    REFERENCE_MASTER_CONTRACTS,
)

DOMAIN_CONTRACT_GROUPS: dict[str, dict[str, DatasetSyncContract]] = {
    "market_equity": MARKET_EQUITY_CONTRACTS,
    "market_fund": MARKET_FUND_CONTRACTS,
    "index_series": INDEX_SERIES_CONTRACTS,
    "board_hotspot": BOARD_HOTSPOT_CONTRACTS,
    "moneyflow": MONEYFLOW_CONTRACTS,
    "reference_master": REFERENCE_MASTER_CONTRACTS,
    "low_frequency": LOW_FREQUENCY_CONTRACTS,
}

def _assemble_sync_v2_contracts() -> dict[str, DatasetSyncContract]:
    assembled: dict[str, DatasetSyncContract] = {}
    for domain, contracts in DOMAIN_CONTRACT_GROUPS.items():
        for dataset_key, contract in contracts.items():
            if dataset_key in assembled:
                raise RuntimeError(f"Duplicate sync_v2 contract key={dataset_key} domain={domain}")
            assembled[dataset_key] = contract
    return assembled

SYNC_V2_CONTRACTS: dict[str, DatasetSyncContract] = _assemble_sync_v2_contracts()

__all__ = ["DOMAIN_CONTRACT_GROUPS", "SYNC_V2_CONTRACTS"]
