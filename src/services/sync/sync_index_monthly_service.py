from __future__ import annotations

from src.services.sync.fields import INDEX_MONTHLY_FIELDS
from src.services.sync.sync_index_weekly_service import (
    SyncIndexWeeklyService,
    build_index_period_params,
)


class SyncIndexMonthlyService(SyncIndexWeeklyService):
    job_name = "sync_index_monthly"
    api_name = "index_monthly"
    target_table = "core.index_monthly_serving"
    raw_dao_name = "raw_index_monthly_bar"
    core_dao_name = "index_monthly_serving"
    fields = INDEX_MONTHLY_FIELDS
    params_builder = staticmethod(build_index_period_params("monthly"))
    serving_table = "core.index_monthly_serving"
    period_kind = "monthly"
