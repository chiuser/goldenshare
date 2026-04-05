from __future__ import annotations

from src.foundation.services.sync.fields import STK_PERIOD_BAR_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService


def build_stk_period_bar_params(freq: str):
    def _builder(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
        params = {"freq": freq}
        if kwargs.get("ts_code"):
            params["ts_code"] = kwargs["ts_code"]
        if kwargs.get("start_date"):
            params["start_date"] = kwargs["start_date"].replace("-", "")
        if kwargs.get("end_date"):
            params["end_date"] = kwargs["end_date"].replace("-", "")
        if trade_date is not None:
            params["trade_date"] = trade_date.strftime("%Y%m%d")
        return params

    return _builder


def transform_stk_period_bar(row: dict):  # type: ignore[no-untyped-def]
    return {**row, "change_amount": row.get("change")}


class SyncStkPeriodBarWeekService(HttpResourceSyncService):
    job_name = "sync_stk_period_bar_week"
    target_table = "core.stk_period_bar"
    api_name = "stk_weekly_monthly"
    raw_dao_name = "raw_stk_period_bar"
    core_dao_name = "stk_period_bar"
    fields = STK_PERIOD_BAR_FIELDS
    date_fields = ("trade_date", "end_date")
    decimal_fields = ("open", "high", "low", "close", "pre_close", "vol", "amount", "change", "pct_chg")
    params_builder = staticmethod(build_stk_period_bar_params("week"))
    core_transform = staticmethod(transform_stk_period_bar)
