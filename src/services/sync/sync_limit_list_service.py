from __future__ import annotations

from src.services.sync.fields import LIMIT_LIST_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService
from src.services.sync.sync_daily_basic_service import build_trade_date_only


class SyncLimitListService(HttpResourceSyncService):
    job_name = "sync_limit_list"
    target_table = "core.equity_limit_list"
    api_name = "limit_list_d"
    raw_dao_name = "raw_limit_list"
    core_dao_name = "equity_limit_list"
    fields = LIMIT_LIST_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("close", "pct_chg", "amount", "limit_amount", "float_mv", "total_mv", "turnover_ratio", "fd_amount")
    params_builder = staticmethod(build_trade_date_only)
    core_transform = staticmethod(lambda row: {**row, "limit_type": row.get("limit")})
