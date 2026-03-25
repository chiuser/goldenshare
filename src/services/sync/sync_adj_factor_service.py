from __future__ import annotations

from src.config.settings import get_settings
from src.services.sync.fields import ADJ_FACTOR_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def build_adj_factor_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        params = {"ts_code": kwargs["ts_code"], "start_date": kwargs.get("start_date", settings.history_start_date).replace("-", "")}
        if kwargs.get("end_date"):
            params["end_date"] = kwargs["end_date"].replace("-", "")
        return params
    if trade_date is None:
        raise ValueError("trade_date is required for incremental adj_factor sync")
    return {"trade_date": trade_date.strftime("%Y%m%d")}


class SyncAdjFactorService(HttpResourceSyncService):
    job_name = "sync_adj_factor"
    target_table = "core.equity_adj_factor"
    api_name = "adj_factor"
    raw_dao_name = "raw_adj_factor"
    core_dao_name = "equity_adj_factor"
    fields = ADJ_FACTOR_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("adj_factor",)
    params_builder = staticmethod(build_adj_factor_params)
