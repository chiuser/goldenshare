from __future__ import annotations

from src.foundation.config.settings import get_settings
from src.foundation.services.sync.fields import DC_INDEX_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService


def build_dc_index_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        params = {
            "ts_code": kwargs.get("ts_code"),
            "start_date": (kwargs.get("start_date") or settings.history_start_date).replace("-", ""),
            "end_date": kwargs.get("end_date", "").replace("-", "") if kwargs.get("end_date") else None,
            "idx_type": kwargs.get("idx_type"),
        }
        return {key: value for key, value in params.items() if value}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental dc_index sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
        "idx_type": kwargs.get("idx_type"),
    }
    return {key: value for key, value in params.items() if value}


class SyncDcIndexService(HttpResourceSyncService):
    job_name = "sync_dc_index"
    target_table = "core_serving.dc_index"
    api_name = "dc_index"
    raw_dao_name = "raw_dc_index"
    core_dao_name = "dc_index"
    fields = DC_INDEX_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("pct_change", "leading_pct", "total_mv", "turnover_rate")
    params_builder = staticmethod(build_dc_index_params)
