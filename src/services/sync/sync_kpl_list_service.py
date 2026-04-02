from __future__ import annotations

from src.config.settings import get_settings
from src.services.sync.fields import KPL_LIST_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def build_kpl_list_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        params = {
            "ts_code": kwargs.get("ts_code"),
            "tag": kwargs.get("tag"),
            "trade_date": kwargs.get("trade_date"),
            "start_date": kwargs.get("start_date") or settings.history_start_date,
            "end_date": kwargs.get("end_date"),
        }
        return {key: value.replace("-", "") if key in {"trade_date", "start_date", "end_date"} and isinstance(value, str) else value for key, value in params.items() if value}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental kpl_list sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
        "tag": kwargs.get("tag"),
    }
    return {key: value for key, value in params.items() if value}


class SyncKplListService(HttpResourceSyncService):
    job_name = "sync_kpl_list"
    target_table = "core.kpl_list"
    api_name = "kpl_list"
    raw_dao_name = "raw_kpl_list"
    core_dao_name = "kpl_list"
    fields = KPL_LIST_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = (
        "net_change",
        "bid_amount",
        "bid_change",
        "bid_turnover",
        "lu_bid_vol",
        "pct_chg",
        "bid_pct_chg",
        "rt_pct_chg",
        "limit_order",
        "amount",
        "turnover_rate",
        "free_float",
        "lu_limit_order",
    )
    params_builder = staticmethod(build_kpl_list_params)
