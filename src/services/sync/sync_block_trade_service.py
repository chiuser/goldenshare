from __future__ import annotations

from src.services.sync.fields import BLOCK_TRADE_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService
from src.services.sync.sync_daily_basic_service import build_trade_date_only


class SyncBlockTradeService(HttpResourceSyncService):
    job_name = "sync_block_trade"
    target_table = "core.equity_block_trade"
    api_name = "block_trade"
    raw_dao_name = "raw_block_trade"
    core_dao_name = "equity_block_trade"
    fields = BLOCK_TRADE_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("price", "vol", "amount")
    params_builder = staticmethod(build_trade_date_only)
