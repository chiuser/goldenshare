from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from src.ops.schemas.freshness import DatasetFreshnessItem, OpsFreshnessSummary
from src.ops.schemas.task_run import TaskRunListItem


class OpsOverviewKpis(BaseModel):
    total_task_runs: int
    queued_task_runs: int
    running_task_runs: int
    success_task_runs: int
    failed_task_runs: int
    canceled_task_runs: int
    partial_success_task_runs: int


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
    recent_task_runs: list[TaskRunListItem]
    recent_failures: list[TaskRunListItem]


class OpsOverviewSummaryResponse(BaseModel):
    freshness_summary: OpsFreshnessSummary
