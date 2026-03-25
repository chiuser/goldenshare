from __future__ import annotations

from src.services.sync.fields import MONEYFLOW_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService
from src.services.sync.sync_daily_basic_service import build_trade_date_only


class SyncMoneyflowService(HttpResourceSyncService):
    job_name = "sync_moneyflow"
    target_table = "core.equity_moneyflow"
    api_name = "moneyflow"
    raw_dao_name = "raw_moneyflow"
    core_dao_name = "equity_moneyflow"
    fields = MONEYFLOW_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = (
        "buy_sm_vol",
        "buy_sm_amount",
        "sell_sm_vol",
        "sell_sm_amount",
        "buy_md_vol",
        "buy_md_amount",
        "sell_md_vol",
        "sell_md_amount",
        "buy_lg_vol",
        "buy_lg_amount",
        "sell_lg_vol",
        "sell_lg_amount",
        "buy_elg_vol",
        "buy_elg_amount",
        "sell_elg_vol",
        "sell_elg_amount",
        "net_mf_vol",
        "net_mf_amount",
    )
    params_builder = staticmethod(build_trade_date_only)
