from __future__ import annotations

from datetime import date

from src.foundation.services.sync.fields import ETF_BASIC_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService


def build_etf_basic_params(run_type: str, trade_date: date | None = None, **kwargs):  # type: ignore[no-untyped-def]
    params = {}
    if kwargs.get("list_status"):
        params["list_status"] = kwargs["list_status"]
    for key in ("ts_code", "index_code", "exchange", "mgr"):
        if kwargs.get(key):
            params[key] = kwargs[key]
    for key in ("list_date",):
        if kwargs.get(key):
            params[key] = kwargs[key].replace("-", "")
    return params


class SyncEtfBasicService(HttpResourceSyncService):
    job_name = "sync_etf_basic"
    target_table = "core.etf_basic"
    api_name = "etf_basic"
    raw_dao_name = "raw_etf_basic"
    core_dao_name = "etf_basic"
    fields = ETF_BASIC_FIELDS
    date_fields = ("setup_date", "list_date")
    decimal_fields = ("mgt_fee",)
    params_builder = staticmethod(build_etf_basic_params)
