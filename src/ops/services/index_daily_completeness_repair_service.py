from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.ingestion.plan_helpers import split_multi_values
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.index_daily_reconciliation_policy import (
    INDEX_DAILY_GAP_REPAIR_RUN_SCOPE,
    INDEX_DAILY_RECONCILIATION_TIMEZONE,
    INDEX_DAILY_REPAIR_BATCH_SIZE,
    INDEX_DAILY_REPAIR_MAX_TASK_RUNS_PER_ROUND,
    is_allowed_index_daily_repair_target,
)
from src.ops.services.index_daily_source_serviceability_service import IndexDailySourceServiceabilityService
from src.ops.services.task_run_service import TaskRunCommandService, TaskRunCreateContext


INDEX_DAILY_REPAIR_OPEN_STATUSES = ("queued", "running", "canceling")


class IndexDailyCompletenessRepairService:
    """Turn eligible index_daily serving gaps into standard TaskRun intentions."""

    def __init__(self, source_service: IndexDailySourceServiceabilityService | None = None) -> None:
        self.source_service = source_service or IndexDailySourceServiceabilityService()

    def missing_codes(self, session: Session, *, trade_date: date) -> list[str]:
        return self.source_service.missing_active_codes(session, target_trade_date=trade_date)

    def create_repair_task_runs(
        self,
        session: Session,
        *,
        source_run: DatasetDateCompletenessRun,
        now: datetime | None = None,
    ) -> list[TaskRun]:
        trade_date = self._eligible_trade_date(session, source_run=source_run, now=now)
        if trade_date is None:
            return []

        classifications = self.source_service.classify_active_gaps(session, target_trade_date=trade_date)
        pending_codes = self._pending_repair_codes(session, trade_date=trade_date)
        repair_codes = [
            classification.ts_code
            for classification in classifications
            if classification.automatic_repair_eligible and classification.ts_code not in pending_codes
        ]
        if not repair_codes:
            return []

        max_codes = INDEX_DAILY_REPAIR_BATCH_SIZE * INDEX_DAILY_REPAIR_MAX_TASK_RUNS_PER_ROUND
        selected_codes = repair_codes[:max_codes]
        task_runs: list[TaskRun] = []
        for batch_index, start in enumerate(range(0, len(selected_codes), INDEX_DAILY_REPAIR_BATCH_SIZE), start=1):
            batch_codes = selected_codes[start : start + INDEX_DAILY_REPAIR_BATCH_SIZE]
            task_runs.append(
                TaskRunCommandService().create_task_run(
                    session,
                    context=TaskRunCreateContext(
                        task_type="dataset_action",
                        resource_key="index_daily",
                        action="maintain",
                        time_input={"mode": "point", "trade_date": trade_date.isoformat()},
                        filters={"ts_code": ",".join(batch_codes)},
                        request_payload={
                            "run_scope": INDEX_DAILY_GAP_REPAIR_RUN_SCOPE,
                            "source_date_completeness_run_id": source_run.id,
                            "repair_trade_date": trade_date.isoformat(),
                            "missing_code_count": len(classifications),
                            "batch_index": batch_index,
                            "batch_size": len(batch_codes),
                        },
                        trigger_source="system",
                        requested_by_user_id=None,
                        schedule_id=None,
                    ),
                )
            )
        return task_runs

    def _eligible_trade_date(
        self,
        session: Session,
        *,
        source_run: DatasetDateCompletenessRun,
        now: datetime | None,
    ) -> date | None:
        if source_run.dataset_key != "index_daily":
            return None
        if source_run.run_status != "succeeded" or source_run.result_status != "failed":
            return None
        if source_run.audit_scope != "date_subject_matrix":
            return None
        if source_run.start_date != source_run.end_date:
            return None
        trade_date = source_run.start_date
        local_today = (now or datetime.now(timezone.utc)).astimezone(INDEX_DAILY_RECONCILIATION_TIMEZONE).date()
        current_is_open = session.scalar(
            select(TradeCalendar.trade_date)
            .where(TradeCalendar.exchange == get_settings().default_exchange)
            .where(TradeCalendar.trade_date == local_today)
            .where(TradeCalendar.is_open.is_(True))
            .limit(1)
        )
        if current_is_open is None:
            return None
        previous_open_trade_date = session.scalar(
            select(TradeCalendar.trade_date)
            .where(TradeCalendar.exchange == get_settings().default_exchange)
            .where(TradeCalendar.is_open.is_(True))
            .where(TradeCalendar.trade_date < local_today)
            .order_by(TradeCalendar.trade_date.desc())
            .limit(1)
        )
        if not is_allowed_index_daily_repair_target(
            target_trade_date=trade_date,
            current_trade_date=local_today,
            previous_open_trade_date=previous_open_trade_date,
        ):
            return None
        return trade_date

    def _pending_repair_codes(self, session: Session, *, trade_date: date) -> set[str]:
        candidates = session.scalars(
            select(TaskRun)
            .where(TaskRun.task_type == "dataset_action")
            .where(TaskRun.resource_key == "index_daily")
            .where(TaskRun.action == "maintain")
            .where(TaskRun.status.in_(INDEX_DAILY_REPAIR_OPEN_STATUSES))
        )
        pending_codes: set[str] = set()
        for task_run in candidates:
            time_input = task_run.time_input_json if isinstance(task_run.time_input_json, dict) else {}
            payload = task_run.request_payload_json if isinstance(task_run.request_payload_json, dict) else {}
            if time_input.get("mode") != "point" or time_input.get("trade_date") != trade_date.isoformat():
                continue
            if payload.get("run_scope") != INDEX_DAILY_GAP_REPAIR_RUN_SCOPE:
                continue
            filters = task_run.filters_json if isinstance(task_run.filters_json, dict) else {}
            pending_codes.update(code for code in split_multi_values(filters.get("ts_code")) if code)
        return pending_codes
