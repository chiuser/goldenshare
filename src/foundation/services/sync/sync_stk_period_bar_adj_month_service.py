from __future__ import annotations

from src.foundation.services.sync.sync_stk_period_bar_adj_week_service import SyncStkPeriodBarAdjWeekService
from src.foundation.services.sync.sync_stk_period_bar_week_service import build_stk_period_bar_params


class SyncStkPeriodBarAdjMonthService(SyncStkPeriodBarAdjWeekService):
    job_name = "sync_stk_period_bar_adj_month"
    params_builder = staticmethod(build_stk_period_bar_params("month"))
