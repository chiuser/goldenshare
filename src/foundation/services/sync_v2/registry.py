from __future__ import annotations

from src.foundation.services.sync_v2.contracts import DatasetSyncContract
from src.foundation.services.sync_v2.registry_parts.assemble import SYNC_V2_CONTRACTS

def list_sync_v2_contracts() -> tuple[DatasetSyncContract, ...]:
    return tuple(SYNC_V2_CONTRACTS[key] for key in sorted(SYNC_V2_CONTRACTS.keys()))

def has_sync_v2_contract(dataset_key: str) -> bool:
    return dataset_key in SYNC_V2_CONTRACTS

def get_sync_v2_contract(dataset_key: str) -> DatasetSyncContract:
    contract = SYNC_V2_CONTRACTS.get(dataset_key)
    if contract is None:
        raise KeyError(f"sync_v2 contract not found for dataset={dataset_key}")
    return contract
