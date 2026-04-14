from __future__ import annotations

from src.foundation.services.sync.fields import DAILY_BASIC_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService


def build_trade_date_only(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    if trade_date is None:
        return {}
    return {"trade_date": trade_date.strftime("%Y%m%d")}


class SyncDailyBasicService(HttpResourceSyncService):
    job_name = "sync_daily_basic"
    target_table = "core_serving.equity_daily_basic"
    api_name = "daily_basic"
    raw_dao_name = "raw_daily_basic"
    core_dao_name = "equity_daily_basic"
    fields = DAILY_BASIC_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = (
        "close",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_share",
        "float_share",
        "free_share",
        "total_mv",
        "circ_mv",
    )
    params_builder = staticmethod(build_trade_date_only)
