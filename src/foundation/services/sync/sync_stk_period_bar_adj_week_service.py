from __future__ import annotations

from src.foundation.services.sync.fields import STK_PERIOD_BAR_ADJ_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService

from src.foundation.services.sync.sync_stk_period_bar_week_service import build_stk_period_bar_params


def transform_stk_period_bar_adj(row: dict):  # type: ignore[no-untyped-def]
    return {**row, "change_amount": row.get("change")}


class SyncStkPeriodBarAdjWeekService(HttpResourceSyncService):
    job_name = "sync_stk_period_bar_adj_week"
    target_table = "core_serving.stk_period_bar_adj"
    api_name = "stk_week_month_adj"
    raw_dao_name = "raw_stk_period_bar_adj"
    core_dao_name = "stk_period_bar_adj"
    fields = STK_PERIOD_BAR_ADJ_FIELDS
    date_fields = ("trade_date", "end_date")
    decimal_fields = (
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "open_qfq",
        "high_qfq",
        "low_qfq",
        "close_qfq",
        "open_hfq",
        "high_hfq",
        "low_hfq",
        "close_hfq",
        "vol",
        "amount",
        "change",
        "pct_chg",
    )
    params_builder = staticmethod(build_stk_period_bar_params("week"))
    core_transform = staticmethod(transform_stk_period_bar_adj)
