from __future__ import annotations

from datetime import date

from src.services.sync.fields import LIMIT_LIST_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def build_limit_list_params(run_type: str, trade_date: date | None = None, **kwargs):  # type: ignore[no-untyped-def]
    limit_type = kwargs.get("limit_type")
    exchange = kwargs.get("exchange")
    if isinstance(limit_type, list):
        limit_type = ",".join(str(item).strip() for item in limit_type if str(item).strip()) or None
    if isinstance(exchange, list):
        exchange = ",".join(str(item).strip() for item in exchange if str(item).strip()) or None
    if run_type == "FULL":
        params = {
            "trade_date": kwargs.get("trade_date"),
            "start_date": kwargs.get("start_date"),
            "end_date": kwargs.get("end_date"),
            "ts_code": kwargs.get("ts_code"),
            "limit_type": limit_type,
            "exchange": exchange,
        }
        return {
            key: value.replace("-", "") if key in {"trade_date", "start_date", "end_date"} and isinstance(value, str) else value
            for key, value in params.items()
            if value
        }
    if trade_date is None:
        raise ValueError("trade_date is required for incremental limit_list_d sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
        "limit_type": limit_type,
        "exchange": exchange,
    }
    return {key: value for key, value in params.items() if value}


class SyncLimitListService(HttpResourceSyncService):
    job_name = "sync_limit_list"
    target_table = "core.equity_limit_list"
    api_name = "limit_list_d"
    raw_dao_name = "raw_limit_list"
    core_dao_name = "equity_limit_list"
    fields = LIMIT_LIST_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("close", "pct_chg", "amount", "limit_amount", "float_mv", "total_mv", "turnover_ratio", "fd_amount")
    params_builder = staticmethod(build_limit_list_params)
    core_transform = staticmethod(lambda row: {**row, "limit_type": row.get("limit")})
