from __future__ import annotations

from typing import TYPE_CHECKING

from src.foundation.services.sync_v2.registry import (
    get_sync_v2_contract,
    has_sync_v2_contract,
    list_sync_v2_contracts,
)

if TYPE_CHECKING:
    from src.foundation.services.sync_v2.service import SyncV2Service

__all__ = [
    "SyncV2Service",
    "get_sync_v2_contract",
    "has_sync_v2_contract",
    "list_sync_v2_contracts",
]


def __getattr__(name: str):
    if name == "SyncV2Service":
        from src.foundation.services.sync_v2.service import SyncV2Service

        return SyncV2Service
    raise AttributeError(name)
