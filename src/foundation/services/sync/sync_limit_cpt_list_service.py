from __future__ import annotations

from src.foundation.services.sync.fields import LIMIT_CPT_LIST_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService


def build_limit_cpt_list_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    if run_type == "FULL":
        params = {
            "trade_date": kwargs.get("trade_date"),
            "start_date": kwargs.get("start_date"),
            "end_date": kwargs.get("end_date"),
            "ts_code": kwargs.get("ts_code"),
        }
        return {
            key: value.replace("-", "") if key in {"trade_date", "start_date", "end_date"} and isinstance(value, str) else value
            for key, value in params.items()
            if value
        }
    if trade_date is None:
        raise ValueError("trade_date is required for incremental limit_cpt_list sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
    }
    return {key: value for key, value in params.items() if value}


class SyncLimitCptListService(HttpResourceSyncService):
    job_name = "sync_limit_cpt_list"
    target_table = "core_serving.limit_cpt_list"
    api_name = "limit_cpt_list"
    raw_dao_name = "raw_limit_cpt_list"
    core_dao_name = "limit_cpt_list"
    fields = LIMIT_CPT_LIST_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("pct_chg",)
    params_builder = staticmethod(build_limit_cpt_list_params)
