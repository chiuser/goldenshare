from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.ops.models.ops.job_execution import JobExecution
from src.ops.queries.execution_query_service import ExecutionQueryService
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService
from src.ops.schemas.overview import OpsOverviewKpis, OpsOverviewResponse, OpsOverviewSummaryResponse, OpsTodayKpis


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


class OpsOverviewQueryService:
    def __init__(self) -> None:
        self.execution_query_service = ExecutionQueryService()
        self.freshness_query_service = OpsFreshnessQueryService()

    def build_overview(self, session: Session) -> OpsOverviewResponse:
        rows = session.execute(
            select(JobExecution.status, func.count()).group_by(JobExecution.status)
        ).all()
        counts = {status: count for status, count in rows}
        today_kpis = self._build_today_kpis(session)
        recent_executions = self.execution_query_service.list_executions(session, limit=10).items
        recent_failures = self.execution_query_service.list_executions(session, status="failed", limit=5).items
        freshness_response = self.freshness_query_service.build_freshness(session)
        freshness_summary, lagging_datasets = self.freshness_query_service.summarize(freshness_response)

        return OpsOverviewResponse(
            today_kpis=today_kpis.model_copy(
                update={"attention_dataset_count": len(lagging_datasets)},
            ),
            kpis=OpsOverviewKpis(
                total_executions=sum(counts.values()),
                queued_executions=counts.get("queued", 0),
                running_executions=counts.get("running", 0) + counts.get("canceling", 0),
                success_executions=counts.get("success", 0),
                failed_executions=counts.get("failed", 0),
                canceled_executions=counts.get("canceled", 0),
                partial_success_executions=counts.get("partial_success", 0),
            ),
            freshness_summary=freshness_summary,
            lagging_datasets=lagging_datasets,
            recent_executions=recent_executions,
            recent_failures=recent_failures,
        )

    def build_overview_summary(self, session: Session) -> OpsOverviewSummaryResponse:
        freshness_response = self.freshness_query_service.build_freshness(session)
        freshness_summary, _ = self.freshness_query_service.summarize(freshness_response)
        return OpsOverviewSummaryResponse(freshness_summary=freshness_summary)

    @staticmethod
    def _build_today_kpis(session: Session) -> OpsTodayKpis:
        now_local = datetime.now(LOCAL_TZ)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(ZoneInfo("UTC"))
        rows = session.execute(
            select(JobExecution.status, func.count())
            .where(JobExecution.requested_at >= start_utc)
            .group_by(JobExecution.status)
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
