from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.date_completeness_run_service import DateCompletenessRunCommandService
from src.ops.services.index_daily_reconciliation_policy import (
    INDEX_DAILY_GAP_REPAIR_RUN_SCOPE,
    INDEX_DAILY_RECONCILIATION_TIMEZONE,
    previous_open_day_repair_slot_for_time,
)
from src.ops.services.index_daily_source_serviceability_service import IndexDailySourceServiceabilityService


INDEX_DAILY_AUDIT_OPEN_STATUSES = ("queued", "running")
INDEX_DAILY_REPAIR_OPEN_STATUSES = ("queued", "running", "canceling")


class IndexDailyCompletenessReconciliationService:
    """Schedule bounded T/P index_daily audits only while recent source delays remain repairable."""

    def __init__(
        self,
        source_service: IndexDailySourceServiceabilityService | None = None,
        run_command_service: DateCompletenessRunCommandService | None = None,
    ) -> None:
        self.source_service = source_service or IndexDailySourceServiceabilityService()
        self.run_command_service = run_command_service or DateCompletenessRunCommandService()

    def enqueue_due_audits(
        self,
        session: Session,
        *,
        now: datetime | None = None,
    ) -> list[DatasetDateCompletenessRun]:
        current_time = self._as_utc(now or datetime.now(timezone.utc))
        local_now = current_time.astimezone(INDEX_DAILY_RECONCILIATION_TIMEZONE)
        if not self._is_open_trade_date(session, trade_date=local_now.date()):
            return []

        target = self._target_for_local_now(session, local_now=local_now)
        if target is None:
            return []
        target_trade_date, repair_slot = target
        if not self._is_due_for_reaudit(
            session,
            target_trade_date=target_trade_date,
            repair_slot=repair_slot,
        ):
            return []
        return [
            self.run_command_service.create_system_run(
                session,
                dataset_key="index_daily",
                start_date=target_trade_date,
                end_date=target_trade_date,
                now=current_time,
            )
        ]

    def _target_for_local_now(
        self,
        session: Session,
        *,
        local_now: datetime,
    ) -> tuple[date, str] | None:
        local_time = local_now.time().replace(tzinfo=None)
        repair_slot = previous_open_day_repair_slot_for_time(local_time)
        if repair_slot is None:
            return None
        previous_open_trade_date = session.scalar(
            select(TradeCalendar.trade_date)
            .where(TradeCalendar.exchange == get_settings().default_exchange)
            .where(TradeCalendar.is_open.is_(True))
            .where(TradeCalendar.trade_date < local_now.date())
            .order_by(TradeCalendar.trade_date.desc())
            .limit(1)
        )
        if previous_open_trade_date is None:
            return None
        return previous_open_trade_date, repair_slot

    def _is_due_for_reaudit(
        self,
        session: Session,
        *,
        target_trade_date: date,
        repair_slot: str,
    ) -> bool:
        latest_audit = session.scalar(
            select(DatasetDateCompletenessRun)
            .where(DatasetDateCompletenessRun.dataset_key == "index_daily")
            .where(DatasetDateCompletenessRun.audit_scope == "date_subject_matrix")
            .where(DatasetDateCompletenessRun.start_date == target_trade_date)
            .where(DatasetDateCompletenessRun.end_date == target_trade_date)
            .order_by(DatasetDateCompletenessRun.requested_at.desc(), DatasetDateCompletenessRun.id.desc())
            .limit(1)
        )
        if latest_audit is None:
            return False
        if latest_audit.run_status != "succeeded" or latest_audit.result_status != "failed":
            return False
        if self._has_open_audit(session, target_trade_date=target_trade_date):
            return False
        if self._has_open_repair_task_run(session, target_trade_date=target_trade_date):
            return False
        return any(
            self.source_service.is_repair_slot_available(classification, repair_slot=repair_slot)
            for classification in self.source_service.classify_active_gaps(
                session,
                target_trade_date=target_trade_date,
            )
        )

    @staticmethod
    def _has_open_audit(session: Session, *, target_trade_date: date) -> bool:
        return session.scalar(
            select(DatasetDateCompletenessRun.id)
            .where(DatasetDateCompletenessRun.dataset_key == "index_daily")
            .where(DatasetDateCompletenessRun.audit_scope == "date_subject_matrix")
            .where(DatasetDateCompletenessRun.start_date == target_trade_date)
            .where(DatasetDateCompletenessRun.end_date == target_trade_date)
            .where(DatasetDateCompletenessRun.run_status.in_(INDEX_DAILY_AUDIT_OPEN_STATUSES))
            .limit(1)
        ) is not None

    @staticmethod
    def _has_open_repair_task_run(session: Session, *, target_trade_date: date) -> bool:
        candidates = session.scalars(
            select(TaskRun)
            .where(TaskRun.task_type == "dataset_action")
            .where(TaskRun.resource_key == "index_daily")
            .where(TaskRun.action == "maintain")
            .where(TaskRun.status.in_(INDEX_DAILY_REPAIR_OPEN_STATUSES))
        )
        expected_trade_date = target_trade_date.isoformat()
        for task_run in candidates:
            payload = task_run.request_payload_json if isinstance(task_run.request_payload_json, dict) else {}
            time_input = task_run.time_input_json if isinstance(task_run.time_input_json, dict) else {}
            if payload.get("run_scope") != INDEX_DAILY_GAP_REPAIR_RUN_SCOPE:
                continue
            if time_input.get("mode") == "point" and time_input.get("trade_date") == expected_trade_date:
                return True
        return False

    @staticmethod
    def _is_open_trade_date(session: Session, *, trade_date: date) -> bool:
        return session.scalar(
            select(TradeCalendar.trade_date)
            .where(TradeCalendar.exchange == get_settings().default_exchange)
            .where(TradeCalendar.trade_date == trade_date)
            .where(TradeCalendar.is_open.is_(True))
            .limit(1)
        ) is not None

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
