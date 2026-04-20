from __future__ import annotations

from src.foundation.services.sync_v2.adapters.base import SourceAdapter
from src.foundation.services.sync_v2.adapters.biying import BiyingSyncV2Adapter
from src.foundation.services.sync_v2.adapters.tushare import TushareSyncV2Adapter
from src.foundation.services.sync_v2.errors import StructuredError, SyncV2SourceError


_ADAPTERS: dict[str, type[SourceAdapter]] = {
    "tushare": TushareSyncV2Adapter,
    "biying": BiyingSyncV2Adapter,
}


def get_source_adapter(source_key: str) -> SourceAdapter:
    adapter_type = _ADAPTERS.get(source_key)
    if adapter_type is None:
        supported = ", ".join(sorted(_ADAPTERS.keys()))
        raise SyncV2SourceError(
            StructuredError(
                error_code="source_adapter_not_found",
                error_type="source",
                phase="adapter_registry",
                message=f"unsupported source adapter: {source_key}; supported={supported}",
                retryable=False,
            )
        )
    return adapter_type()
