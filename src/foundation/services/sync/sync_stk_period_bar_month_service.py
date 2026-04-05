from __future__ import annotations

from src.foundation.services.sync.sync_stk_period_bar_week_service import (
    SyncStkPeriodBarWeekService,
    build_stk_period_bar_params,
)


class SyncStkPeriodBarMonthService(SyncStkPeriodBarWeekService):
    job_name = "sync_stk_period_bar_month"
    params_builder = staticmethod(build_stk_period_bar_params("month"))
