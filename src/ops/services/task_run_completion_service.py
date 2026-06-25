from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.datasets.registry import get_dataset_action_key
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.services.date_completeness_run_service import DateCompletenessRunCommandService
from src.ops.services.index_daily_completeness_repair_service import INDEX_DAILY_GAP_REPAIR_RUN_SCOPE
from src.ops.services.operations_dataset_status_snapshot_service import DatasetStatusSnapshotService
from src.utils import truncate_text


TERMINAL_TASK_RUN_STATUSES = ("success", "partial_success", "failed", "canceled")


@dataclass(frozen=True)
class TaskRunCompletionCursor:
    ended_at: datetime | None
    task_run_id: int = 0


@dataclass(frozen=True)
class TaskRunCompletionSummary:
    task_run_id: int
    title: str
    task_type_label: str
    status_label: str
    trigger_source_label: str
    time_scope_label: str
    duration_label: str
    progress_label: str
    rows_label: str
    issue_summary: str | None
    detail_url: str | None


class TaskRunCompletionService:
    def __init__(self, snapshot_service_cls=DatasetStatusSnapshotService) -> None:  # type: ignore[no-untyped-def]
        self.snapshot_service_cls = snapshot_service_cls

    def initialize_cursor(self, session: Session) -> TaskRunCompletionCursor:
        row = session.execute(
            select(TaskRun.ended_at, TaskRun.id)
            .where(TaskRun.status.in_(TERMINAL_TASK_RUN_STATUSES))
            .where(TaskRun.ended_at.is_not(None))
            .order_by(TaskRun.ended_at.desc(), TaskRun.id.desc())
            .limit(1)
        ).first()
        if row is None:
            return TaskRunCompletionCursor(ended_at=None, task_run_id=0)
        return TaskRunCompletionCursor(ended_at=row.ended_at, task_run_id=int(row.id))

    def load_completed_after(
        self,
        session: Session,
        *,
        cursor: TaskRunCompletionCursor,
        limit: int,
    ) -> list[TaskRun]:
        stmt = (
            select(TaskRun)
            .where(TaskRun.status.in_(TERMINAL_TASK_RUN_STATUSES))
            .where(TaskRun.ended_at.is_not(None))
            .order_by(TaskRun.ended_at.asc(), TaskRun.id.asc())
            .limit(limit)
        )
        if cursor.ended_at is not None:
            stmt = stmt.where(
                or_(
                    TaskRun.ended_at > cursor.ended_at,
                    and_(TaskRun.ended_at == cursor.ended_at, TaskRun.id > cursor.task_run_id),
                )
            )
        return list(session.scalars(stmt))

    def refresh_snapshot_for_task_run(self, session: Session, task_run: TaskRun) -> int:
        target = self.snapshot_refresh_target(task_run)
        if target is None:
            return 0
        target_type, target_key = target
        bind = session.get_bind()
        if bind is None:
            raise RuntimeError("数据状态快照刷新缺少数据库连接。")
        with Session(bind=bind, autoflush=False, autocommit=False, future=True) as snapshot_session:
            return int(
                self.snapshot_service_cls().refresh_for_target(
                    snapshot_session,
                    target_type=target_type,
                    target_key=target_key,
                    strict=False,
                )
            )

    def create_index_daily_completion_audit_run(
        self,
        session: Session,
        task_run: TaskRun,
        *,
        now: datetime | None = None,
    ) -> DatasetDateCompletenessRun | None:
        trade_date = self._index_daily_completion_audit_trade_date(session, task_run, now=now)
        if trade_date is None:
            return None
        existing_open_run = session.scalar(
            select(DatasetDateCompletenessRun)
            .where(DatasetDateCompletenessRun.dataset_key == "index_daily")
            .where(DatasetDateCompletenessRun.audit_scope == "date_subject_matrix")
            .where(DatasetDateCompletenessRun.start_date == trade_date)
            .where(DatasetDateCompletenessRun.end_date == trade_date)
            .where(DatasetDateCompletenessRun.run_status.in_(("queued", "running")))
            .limit(1)
        )
        if existing_open_run is not None:
            return None
        return DateCompletenessRunCommandService().create_system_run(
            session,
            dataset_key="index_daily",
            start_date=trade_date,
            end_date=trade_date,
        )

    def _index_daily_completion_audit_trade_date(
        self,
        session: Session,
        task_run: TaskRun,
        *,
        now: datetime | None,
    ) -> date | None:
        if task_run.task_type != "dataset_action":
            return None
        if task_run.resource_key != "index_daily" or task_run.action != "maintain":
            return None
        if task_run.status != "success":
            return None
        payload = task_run.request_payload_json if isinstance(task_run.request_payload_json, dict) else {}
        if payload.get("run_scope") == INDEX_DAILY_GAP_REPAIR_RUN_SCOPE:
            return None
        time_input = task_run.time_input_json if isinstance(task_run.time_input_json, dict) else {}
        if time_input.get("mode") != "point":
            return None
        trade_date_value = str(time_input.get("trade_date") or "").strip()
        if not trade_date_value:
            return None
        try:
            trade_date = date.fromisoformat(trade_date_value)
        except ValueError:
            return None
        local_today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Asia/Shanghai")).date()
        if trade_date != local_today:
            return None
        is_open = session.scalar(
            select(TradeCalendar.is_open)
            .where(TradeCalendar.exchange == get_settings().default_exchange)
            .where(TradeCalendar.trade_date == trade_date)
            .limit(1)
        )
        return trade_date if is_open is True else None

    @staticmethod
    def snapshot_refresh_target(task_run: TaskRun) -> tuple[str, str] | None:
        if task_run.task_type == "dataset_action":
            if not task_run.resource_key:
                return None
            try:
                return ("dataset_action", get_dataset_action_key(task_run.resource_key, task_run.action or "maintain"))
            except KeyError:
                return None
        if task_run.task_type == "workflow":
            target_key = str((task_run.request_payload_json or {}).get("target_key") or "").strip()
            if not target_key:
                return None
            return ("workflow", target_key)
        return None

    def build_completion_summary(self, session: Session, task_run: TaskRun, *, public_base_url: str | None = None) -> TaskRunCompletionSummary:
        issue = session.get(TaskRunIssue, task_run.primary_issue_id) if task_run.primary_issue_id is not None else None
        return TaskRunCompletionSummary(
            task_run_id=int(task_run.id),
            title=task_run.title,
            task_type_label=self._task_type_label(task_run.task_type),
            status_label=self._status_label(task_run.status),
            trigger_source_label=self._trigger_source_label(task_run.trigger_source),
            time_scope_label=self._time_scope_label(task_run.time_input_json),
            duration_label=self._duration_label(task_run.started_at or task_run.requested_at, task_run.ended_at),
            progress_label=f"{int(task_run.unit_done or 0)}/{int(task_run.unit_total or 0)}",
            rows_label=(
                f"读取 {int(task_run.rows_fetched or 0)}，"
                f"写入 {int(task_run.rows_saved or 0)}，"
                f"拒绝 {int(task_run.rows_rejected or 0)}"
            ),
            issue_summary=self._issue_summary(issue, task_run.status),
            detail_url=self._detail_url(public_base_url, task_run.id),
        )

    @staticmethod
    def _task_type_label(value: str | None) -> str:
        return {
            "dataset_action": "数据维护",
            "workflow": "工作流",
            "maintenance_action": "系统维护",
        }.get(value or "", value or "未知")

    @staticmethod
    def _status_label(value: str | None) -> str:
        return {
            "success": "成功",
            "partial_success": "部分成功",
            "failed": "失败",
            "canceled": "已取消",
        }.get(value or "", value or "未知")

    @staticmethod
    def _trigger_source_label(value: str | None) -> str:
        return {
            "manual": "手动",
            "schedule": "自动",
            "system": "系统",
            "workflow": "工作流",
        }.get(value or "", value or "未知")

    @staticmethod
    def _time_scope_label(time_input: dict | None) -> str:
        payload = time_input or {}
        mode = str(payload.get("mode") or "").strip()
        trade_date = payload.get("trade_date")
        start_date = payload.get("start_date")
        end_date = payload.get("end_date")
        month = payload.get("month")
        start_month = payload.get("start_month")
        end_month = payload.get("end_month")
        if mode == "point" and trade_date:
            return str(trade_date)
        if start_date and end_date:
            return f"{start_date} ~ {end_date}"
        if month:
            return str(month)
        if start_month and end_month:
            return f"{start_month} ~ {end_month}"
        return "无"

    @staticmethod
    def _duration_label(started_at: datetime | None, ended_at: datetime | None) -> str:
        if started_at is None or ended_at is None:
            return "未知"
        total_seconds = max(int((ended_at - started_at).total_seconds()), 0)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}小时{minutes}分{seconds}秒"
        if minutes:
            return f"{minutes}分{seconds}秒"
        return f"{seconds}秒"

    @staticmethod
    def _issue_summary(issue: TaskRunIssue | None, status: str | None) -> str | None:
        if status not in {"failed", "partial_success"}:
            return None
        if issue is None:
            return None
        text = issue.operator_message or issue.title or issue.technical_message
        return truncate_text(text, 500) if text else None

    @staticmethod
    def _detail_url(public_base_url: str | None, task_run_id: int) -> str | None:
        base_url = (public_base_url or "").strip().rstrip("/")
        if not base_url:
            return None
        return f"{base_url}/app/ops/tasks/{task_run_id}"
