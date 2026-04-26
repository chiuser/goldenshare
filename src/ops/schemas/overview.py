from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from src.ops.schemas.freshness import DatasetFreshnessItem, OpsFreshnessSummary
from src.ops.schemas.task_run import TaskRunListItem


class OpsOverviewKpis(BaseModel):
    total_executions: int
    queued_executions: int
    running_executions: int
    success_executions: int
    failed_executions: int
    canceled_executions: int
    partial_success_executions: int


class OpsTodayKpis(BaseModel):
    business_date: date
    total_requests: int
    completed_requests: int
    running_requests: int
    failed_requests: int
    queued_requests: int
    attention_dataset_count: int


class OpsOverviewResponse(BaseModel):
    today_kpis: OpsTodayKpis
    kpis: OpsOverviewKpis
    freshness_summary: OpsFreshnessSummary
    lagging_datasets: list[DatasetFreshnessItem]
    recent_executions: list[TaskRunListItem]
    recent_failures: list[TaskRunListItem]


class OpsOverviewSummaryResponse(BaseModel):
    freshness_summary: OpsFreshnessSummary
