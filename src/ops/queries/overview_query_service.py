from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.ops.models.ops.task_run import TaskRun
from src.ops.queries.task_run_query_service import TaskRunQueryService
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService
from src.ops.schemas.freshness import DatasetFreshnessItem, OpsFreshnessResponse
from src.ops.schemas.overview import OpsOverviewKpis, OpsOverviewResponse, OpsOverviewSummaryResponse, OpsTodayKpis


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


class OpsOverviewQueryService:
    def __init__(self) -> None:
        self.task_run_query_service = TaskRunQueryService()
        self.freshness_query_service = OpsFreshnessQueryService()

    def build_overview(self, session: Session) -> OpsOverviewResponse:
        rows = session.execute(
            select(TaskRun.status, func.count()).group_by(TaskRun.status)
        ).all()
        counts = {status: count for status, count in rows}
        today_kpis = self._build_today_kpis(session)
        recent_task_runs = self.task_run_query_service.list_task_runs(session, limit=10).items
        recent_failures = self.task_run_query_service.list_task_runs(session, status="failed", limit=5).items
        freshness_response = self.freshness_query_service.build_freshness(session)
        freshness_summary, _ = self.freshness_query_service.summarize(freshness_response)
        attention_datasets = self._build_attention_datasets(freshness_response)

        return OpsOverviewResponse(
            today_kpis=today_kpis.model_copy(
                update={"attention_dataset_count": len(attention_datasets)},
            ),
            kpis=OpsOverviewKpis(
                total_task_runs=sum(counts.values()),
                queued_task_runs=counts.get("queued", 0),
                running_task_runs=counts.get("running", 0) + counts.get("canceling", 0),
                success_task_runs=counts.get("success", 0),
                failed_task_runs=counts.get("failed", 0),
                canceled_task_runs=counts.get("canceled", 0),
                partial_success_task_runs=counts.get("partial_success", 0),
            ),
            freshness_summary=freshness_summary,
            lagging_datasets=attention_datasets,
            recent_task_runs=recent_task_runs,
            recent_failures=recent_failures,
        )

    def build_overview_summary(self, session: Session) -> OpsOverviewSummaryResponse:
        freshness_response = self.freshness_query_service.build_freshness(session)
        freshness_summary, _ = self.freshness_query_service.summarize(freshness_response)
        return OpsOverviewSummaryResponse(freshness_summary=freshness_summary)

    @staticmethod
    def _build_attention_datasets(freshness_response: OpsFreshnessResponse) -> list[DatasetFreshnessItem]:
        attention_by_dataset: dict[str, DatasetFreshnessItem] = {}
        for group in freshness_response.groups:
            for item in group.items:
                has_recent_failure = bool(item.recent_failure_summary or item.recent_failure_message)
                lagging_or_stale = item.freshness_status in {"lagging", "stale"}
                if not has_recent_failure and not lagging_or_stale:
                    continue
                attention_by_dataset[item.dataset_key] = item

        status_priority = {
            "stale": 0,
            "lagging": 1,
        }
        items = list(attention_by_dataset.values())
        items.sort(
            key=lambda item: (
                0 if (item.recent_failure_summary or item.recent_failure_message) else 1,
                status_priority.get(item.freshness_status, 2),
                -(item.lag_days or 0),
                -(item.recent_failure_at.timestamp() if item.recent_failure_at else 0.0),
                item.display_name,
            )
        )
        return items

    @staticmethod
    def _build_today_kpis(session: Session) -> OpsTodayKpis:
        now_local = datetime.now(LOCAL_TZ)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(ZoneInfo("UTC"))
        rows = session.execute(
            select(TaskRun.status, func.count())
            .where(TaskRun.requested_at >= start_utc)
            .group_by(TaskRun.status)
        ).all()
        counts = {status: count for status, count in rows}
        completed = (
            counts.get("success", 0)
            + counts.get("failed", 0)
            + counts.get("canceled", 0)
            + counts.get("partial_success", 0)
        )
        return OpsTodayKpis(
            business_date=now_local.date(),
            total_requests=sum(counts.values()),
            completed_requests=completed,
            running_requests=counts.get("running", 0) + counts.get("canceling", 0),
            failed_requests=counts.get("failed", 0),
            queued_requests=counts.get("queued", 0),
            attention_dataset_count=0,
        )
