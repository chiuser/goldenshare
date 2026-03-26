from __future__ import annotations

from src.services.sync.fields import INDEX_DAILY_BASIC_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def build_index_daily_basic_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    params = {}
    if kwargs.get("ts_code"):
        params["ts_code"] = kwargs["ts_code"]
    if run_type == "FULL":
        if kwargs.get("start_date"):
            params["start_date"] = kwargs["start_date"].replace("-", "")
        if kwargs.get("end_date"):
            params["end_date"] = kwargs["end_date"].replace("-", "")
        if trade_date is not None:
            params["trade_date"] = trade_date.strftime("%Y%m%d")
        return params
    if trade_date is not None:
        params["trade_date"] = trade_date.strftime("%Y%m%d")
    if not params:
        raise ValueError("index_daily_basic sync requires ts_code or trade_date")
    return params


class SyncIndexDailyBasicService(HttpResourceSyncService):
    job_name = "sync_index_daily_basic"
    target_table = "core.index_daily_basic"
    api_name = "index_dailybasic"
    raw_dao_name = "raw_index_daily_basic"
    core_dao_name = "index_daily_basic"
    fields = INDEX_DAILY_BASIC_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = (
        "total_mv",
        "float_mv",
        "total_share",
        "float_share",
        "free_share",
        "turnover_rate",
        "turnover_rate_f",
        "pe",
        "pe_ttm",
        "pb",
    )
    params_builder = staticmethod(build_index_daily_basic_params)
