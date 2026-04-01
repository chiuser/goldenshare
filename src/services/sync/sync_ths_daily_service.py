from __future__ import annotations

from src.config.settings import get_settings
from src.services.sync.fields import THS_DAILY_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def build_ths_daily_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        params = {
            "ts_code": kwargs.get("ts_code"),
            "start_date": (kwargs.get("start_date") or settings.history_start_date).replace("-", ""),
            "end_date": kwargs.get("end_date", "").replace("-", "") if kwargs.get("end_date") else None,
        }
        return {key: value for key, value in params.items() if value}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental ths_daily sync")
    params = {"trade_date": trade_date.strftime("%Y%m%d")}
    if kwargs.get("ts_code"):
        params["ts_code"] = kwargs["ts_code"]
    return params


class SyncThsDailyService(HttpResourceSyncService):
    job_name = "sync_ths_daily"
    target_table = "core.ths_daily"
    api_name = "ths_daily"
    raw_dao_name = "raw_ths_daily"
    core_dao_name = "ths_daily"
    fields = THS_DAILY_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = (
        "close",
        "open",
        "high",
        "low",
        "pre_close",
        "avg_price",
        "change",
        "pct_change",
        "vol",
        "turnover_rate",
        "total_mv",
        "float_mv",
    )
    params_builder = staticmethod(build_ths_daily_params)
