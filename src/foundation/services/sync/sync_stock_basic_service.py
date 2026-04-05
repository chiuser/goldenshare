from __future__ import annotations

from src.foundation.services.sync.fields import STOCK_BASIC_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService
from src.foundation.services.transform.normalize_security_service import NormalizeSecurityService


class SyncStockBasicService(HttpResourceSyncService):
    job_name = "sync_stock_basic"
    target_table = "core.security"
    api_name = "stock_basic"
    raw_dao_name = "raw_stock_basic"
    core_dao_name = "security"
    fields = STOCK_BASIC_FIELDS
    date_fields = ("list_date", "delist_date")
    params_builder = staticmethod(lambda run_type, **kwargs: {"list_status": "L,D,P"})
    _normalizer = NormalizeSecurityService()
    core_transform = staticmethod(_normalizer.to_core)
