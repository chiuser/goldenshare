from __future__ import annotations

from src.services.sync.fields import LIMIT_STEP_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def build_limit_step_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    if run_type == "FULL":
        params = {
            "trade_date": kwargs.get("trade_date"),
            "start_date": kwargs.get("start_date"),
            "end_date": kwargs.get("end_date"),
            "ts_code": kwargs.get("ts_code"),
            "nums": kwargs.get("nums"),
        }
        return {
            key: value.replace("-", "") if key in {"trade_date", "start_date", "end_date"} and isinstance(value, str) else value
            for key, value in params.items()
            if value
        }
    if trade_date is None:
        raise ValueError("trade_date is required for incremental limit_step sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
        "nums": kwargs.get("nums"),
    }
    return {key: value for key, value in params.items() if value}


class SyncLimitStepService(HttpResourceSyncService):
    job_name = "sync_limit_step"
    target_table = "core.limit_step"
    api_name = "limit_step"
    raw_dao_name = "raw_limit_step"
    core_dao_name = "limit_step"
    fields = LIMIT_STEP_FIELDS
    date_fields = ("trade_date",)
    decimal_fields: tuple[str, ...] = ()
    params_builder = staticmethod(build_limit_step_params)
