from __future__ import annotations

from calendar import monthrange
from datetime import date

from src.services.sync.fields import INDEX_WEIGHT_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def _month_bounds(target_date: date) -> tuple[str, str]:
    first_day = target_date.replace(day=1)
    last_day = target_date.replace(day=monthrange(target_date.year, target_date.month)[1])
    return first_day.strftime("%Y%m%d"), last_day.strftime("%Y%m%d")


def build_index_weight_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    index_code = kwargs.get("index_code") or kwargs.get("ts_code")
    if not index_code:
        raise ValueError("index_weight sync requires index_code (or ts_code for backward compatibility)")
    params = {"index_code": index_code}
    if run_type == "FULL":
        if kwargs.get("start_date"):
            params["start_date"] = kwargs["start_date"].replace("-", "")
        if kwargs.get("end_date"):
            params["end_date"] = kwargs["end_date"].replace("-", "")
        return params
    if trade_date is None:
        raise ValueError("trade_date is required for incremental index_weight sync")
    start_date, end_date = _month_bounds(trade_date)
    params["start_date"] = start_date
    params["end_date"] = end_date
    return params


class SyncIndexWeightService(HttpResourceSyncService):
    job_name = "sync_index_weight"
    target_table = "core.index_weight"
    api_name = "index_weight"
    raw_dao_name = "raw_index_weight"
    core_dao_name = "index_weight"
    fields = INDEX_WEIGHT_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("weight",)
    params_builder = staticmethod(build_index_weight_params)
