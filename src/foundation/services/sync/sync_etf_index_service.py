from __future__ import annotations

from datetime import date

from src.foundation.services.sync.fields import ETF_INDEX_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService


def build_etf_index_params(run_type: str, trade_date: date | None = None, **kwargs):  # type: ignore[no-untyped-def]
    params = {}
    if kwargs.get("ts_code"):
        params["ts_code"] = kwargs["ts_code"]
    for key in ("pub_date", "base_date"):
        if kwargs.get(key):
            params[key] = kwargs[key].replace("-", "")
    return params


class SyncEtfIndexService(HttpResourceSyncService):
    job_name = "sync_etf_index"
    target_table = "core_serving.etf_index"
    api_name = "etf_index"
    raw_dao_name = "raw_etf_index"
    core_dao_name = "etf_index"
    fields = ETF_INDEX_FIELDS
    date_fields = ("pub_date", "base_date")
    decimal_fields = ("bp",)
    params_builder = staticmethod(build_etf_index_params)
