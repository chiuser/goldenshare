from __future__ import annotations

from src.config.settings import get_settings
from src.services.sync.fields import DC_DAILY_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def build_dc_daily_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
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
        raise ValueError("trade_date is required for incremental dc_daily sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
        "idx_type": kwargs.get("idx_type"),
    }
    return {key: value for key, value in params.items() if value}


class SyncDcDailyService(HttpResourceSyncService):
    job_name = "sync_dc_daily"
    target_table = "core.dc_daily"
    api_name = "dc_daily"
    raw_dao_name = "raw_dc_daily"
    core_dao_name = "dc_daily"
    fields = DC_DAILY_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("close", "open", "high", "low", "change", "pct_change", "vol", "amount", "swing", "turnover_rate")
    params_builder = staticmethod(build_dc_daily_params)
