from __future__ import annotations

from src.services.sync.fields import HOLDERNUMBER_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService
from src.services.sync.sync_dividend_service import build_date_window_params


class SyncHolderNumberService(HttpResourceSyncService):
    job_name = "sync_holder_number"
    target_table = "core.equity_holder_number"
    api_name = "stk_holdernumber"
    raw_dao_name = "raw_holder_number"
    core_dao_name = "equity_holder_number"
    fields = HOLDERNUMBER_FIELDS
    date_fields = ("ann_date", "end_date")
    params_builder = staticmethod(build_date_window_params)
