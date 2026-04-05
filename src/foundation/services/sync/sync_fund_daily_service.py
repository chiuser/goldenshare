from __future__ import annotations

from src.foundation.config.settings import get_settings
from src.foundation.services.sync.fields import FUND_DAILY_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService


def build_fund_daily_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        params = {"ts_code": kwargs.get("ts_code"), "start_date": kwargs.get("start_date", settings.history_start_date).replace("-", "")}
        if kwargs.get("end_date"):
            params["end_date"] = kwargs["end_date"].replace("-", "")
        return {k: v for k, v in params.items() if v}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental fund_daily sync")
    return {"trade_date": trade_date.strftime("%Y%m%d")}


class SyncFundDailyService(HttpResourceSyncService):
    job_name = "sync_fund_daily"
    target_table = "core.fund_daily_bar"
    api_name = "fund_daily"
    raw_dao_name = "raw_fund_daily"
    core_dao_name = "fund_daily_bar"
    fields = FUND_DAILY_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount")
    params_builder = staticmethod(build_fund_daily_params)
    core_transform = staticmethod(lambda row: {**row, "change_amount": row.get("change")})
