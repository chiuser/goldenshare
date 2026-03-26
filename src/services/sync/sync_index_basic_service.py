from __future__ import annotations

from src.services.sync.fields import INDEX_BASIC_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


class SyncIndexBasicService(HttpResourceSyncService):
    job_name = "sync_index_basic"
    target_table = "core.index_basic"
    api_name = "index_basic"
    raw_dao_name = "raw_index_basic"
    core_dao_name = "index_basic"
    fields = INDEX_BASIC_FIELDS
    date_fields = ("base_date", "list_date", "exp_date")
    decimal_fields = ("base_point",)
    params_builder = staticmethod(lambda run_type, **kwargs: {})
