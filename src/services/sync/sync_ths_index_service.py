from __future__ import annotations

from src.services.sync.fields import THS_INDEX_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def build_ths_index_params(run_type: str, **kwargs):  # type: ignore[no-untyped-def]
    params = {
        "ts_code": kwargs.get("ts_code"),
        "exchange": kwargs.get("exchange"),
        "type": kwargs.get("type"),
    }
    return {key: value for key, value in params.items() if value not in (None, "")}


class SyncThsIndexService(HttpResourceSyncService):
    job_name = "sync_ths_index"
    target_table = "core.ths_index"
    api_name = "ths_index"
    raw_dao_name = "raw_ths_index"
    core_dao_name = "ths_index"
    fields = THS_INDEX_FIELDS
    date_fields = ("list_date",)
    params_builder = staticmethod(build_ths_index_params)
