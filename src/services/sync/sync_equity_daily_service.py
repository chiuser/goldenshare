from __future__ import annotations

from src.config.settings import get_settings
from src.services.sync.fields import DAILY_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def build_daily_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        params = {"ts_code": kwargs["ts_code"], "start_date": kwargs.get("start_date", settings.history_start_date).replace("-", "")}
        if kwargs.get("end_date"):
            params["end_date"] = kwargs["end_date"].replace("-", "")
        return params
    if trade_date is None:
        raise ValueError("trade_date is required for incremental daily sync")
    return {"trade_date": trade_date.strftime("%Y%m%d")}


class SyncEquityDailyService(HttpResourceSyncService):
    job_name = "sync_equity_daily"
    target_table = "core.equity_daily_bar"
    api_name = "daily"
    raw_dao_name = "raw_daily"
    core_dao_name = "equity_daily_bar"
    fields = DAILY_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount")
    params_builder = staticmethod(build_daily_params)
    core_transform = staticmethod(lambda row: {**row, "change_amount": row.get("change_amount") or row.get("change"), "source": "tushare"})
