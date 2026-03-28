from __future__ import annotations

from src.services.sync.fields import ETF_BASIC_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


class SyncEtfBasicService(HttpResourceSyncService):
    job_name = "sync_etf_basic"
    target_table = "core.etf_basic"
    api_name = "etf_basic"
    raw_dao_name = "raw_etf_basic"
    core_dao_name = "etf_basic"
    fields = ETF_BASIC_FIELDS
    date_fields = ("setup_date", "list_date")
    decimal_fields = ("mgt_fee",)
    params_builder = staticmethod(lambda run_type, **kwargs: {"list_status": "L,D,P"})
