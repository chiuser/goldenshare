from __future__ import annotations

from src.config.settings import get_settings
from src.services.sync.fields import INDEX_WEEKLY_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def build_index_period_params(api_freq: str):
    def _builder(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
        settings = get_settings()
        if run_type == "FULL":
            params = {
                "ts_code": kwargs.get("ts_code"),
                "start_date": kwargs.get("start_date", settings.history_start_date).replace("-", ""),
            }
            if kwargs.get("end_date"):
                params["end_date"] = kwargs["end_date"].replace("-", "")
            if trade_date is not None:
                params["trade_date"] = trade_date.strftime("%Y%m%d")
            return {key: value for key, value in params.items() if value}
        if trade_date is None:
            raise ValueError(f"trade_date is required for incremental index_{api_freq} sync")
        return {"trade_date": trade_date.strftime("%Y%m%d")}

    return _builder


def transform_index_period_bar(row: dict):  # type: ignore[no-untyped-def]
    return {**row, "change_amount": row.get("change")}


class SyncIndexWeeklyService(HttpResourceSyncService):
    job_name = "sync_index_weekly"
    target_table = "core.index_weekly_bar"
    api_name = "index_weekly"
    raw_dao_name = "raw_index_weekly_bar"
    core_dao_name = "index_weekly_bar"
    fields = INDEX_WEEKLY_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount")
    params_builder = staticmethod(build_index_period_params("weekly"))
    core_transform = staticmethod(transform_index_period_bar)
