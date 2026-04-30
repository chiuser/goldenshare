from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.app.auth.domain import AuthenticatedUser
from src.app.exceptions import WebAppError
from src.foundation.config.settings import get_settings
from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.models.ops.dataset_date_completeness_schedule import DatasetDateCompletenessSchedule
from src.ops.schemas.date_completeness import DateCompletenessScheduleCreateRequest
from src.ops.services.date_completeness_run_service import DateCompletenessRunCommandService
from src.ops.services.schedule_planner import compute_next_run_at, ensure_timezone


class DateCompletenessScheduleCommandService:
    VALID_STATUSES = {"active", "paused"}
    VALID_WINDOW_MODES = {"fixed_range", "rolling"}
    VALID_LOOKBACK_UNITS = {"calendar_day", "open_day", "month"}
    SUPPORTED_CALENDAR_SCOPES = {"default_cn_market", "cn_a_share"}

    def create_schedule(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        payload: DateCompletenessScheduleCreateRequest,
    ) -> DatasetDateCompletenessSchedule:
        definition = self._get_supported_definition(payload.dataset_key)
        self._ensure_status(payload.status)
        self._ensure_calendar(payload.calendar_scope, payload.calendar_exchange)
        next_run_at = self._compute_next_run_at(
            cron_expr=payload.cron_expr,
            timezone_name=payload.timezone,
            after=datetime.now(timezone.utc),
        )
        values = self._validated_window_values(
            window_mode=payload.window_mode,
            start_date=payload.start_date,
            end_date=payload.end_date,
            lookback_count=payload.lookback_count,
            lookback_unit=payload.lookback_unit,
        )
        schedule = DatasetDateCompletenessSchedule(
            dataset_key=definition.dataset_key,
            display_name=self._display_name(payload.display_name, definition),
            status=payload.status,
            window_mode=values["window_mode"],
            start_date=values["start_date"],
            end_date=values["end_date"],
            lookback_count=values["lookback_count"],
            lookback_unit=values["lookback_unit"],
            calendar_scope=payload.calendar_scope,
            calendar_exchange=payload.calendar_exchange,
            cron_expr=payload.cron_expr.strip(),
            timezone=payload.timezone,
            next_run_at=next_run_at,
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
        )
        session.add(schedule)
        session.commit()
        session.refresh(schedule)
        return schedule

    def update_schedule(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        schedule_id: int,
        changes: dict,
    ) -> DatasetDateCompletenessSchedule:
        schedule = self._get_schedule(session, schedule_id)
        if "display_name" in changes:
            schedule.display_name = self._required_text(changes["display_name"], "计划名称")
        if "status" in changes:
            self._ensure_status(str(changes["status"]))
            schedule.status = str(changes["status"])
        calendar_scope = str(changes.get("calendar_scope", schedule.calendar_scope))
        calendar_exchange = changes.get("calendar_exchange", schedule.calendar_exchange)
        self._ensure_calendar(calendar_scope, calendar_exchange)

        timezone_name = str(changes.get("timezone", schedule.timezone))
        cron_expr = str(changes.get("cron_expr", schedule.cron_expr))
        next_run_at = self._compute_next_run_at(
            cron_expr=cron_expr,
            timezone_name=timezone_name,
            after=datetime.now(timezone.utc),
        )
        values = self._validated_window_values(
            window_mode=str(changes.get("window_mode", schedule.window_mode)),
            start_date=changes.get("start_date", schedule.start_date),
            end_date=changes.get("end_date", schedule.end_date),
            lookback_count=changes.get("lookback_count", schedule.lookback_count),
            lookback_unit=changes.get("lookback_unit", schedule.lookback_unit),
        )

        schedule.window_mode = values["window_mode"]
        schedule.start_date = values["start_date"]
        schedule.end_date = values["end_date"]
        schedule.lookback_count = values["lookback_count"]
        schedule.lookback_unit = values["lookback_unit"]
        schedule.calendar_scope = calendar_scope
        schedule.calendar_exchange = calendar_exchange
        schedule.cron_expr = cron_expr.strip()
        schedule.timezone = timezone_name
        schedule.next_run_at = next_run_at
        schedule.updated_by_user_id = user.id
        session.commit()
        session.refresh(schedule)
        return schedule

    def pause_schedule(self, session: Session, *, user: AuthenticatedUser, schedule_id: int) -> DatasetDateCompletenessSchedule:
        schedule = self._get_schedule(session, schedule_id)
        schedule.status = "paused"
        schedule.updated_by_user_id = user.id
        session.commit()
        session.refresh(schedule)
        return schedule

    def resume_schedule(self, session: Session, *, user: AuthenticatedUser, schedule_id: int) -> DatasetDateCompletenessSchedule:
        schedule = self._get_schedule(session, schedule_id)
        schedule.status = "active"
        schedule.next_run_at = self._compute_next_run_at(
            cron_expr=schedule.cron_expr,
            timezone_name=schedule.timezone,
            after=datetime.now(timezone.utc),
        )
        schedule.updated_by_user_id = user.id
        session.commit()
        session.refresh(schedule)
        return schedule

    def delete_schedule(self, session: Session, *, schedule_id: int) -> int:
        schedule = self._get_schedule(session, schedule_id)
        session.delete(schedule)
        session.commit()
        return schedule_id

    def enqueue_due_schedules(
        self,
        session: Session,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> list[DatasetDateCompletenessRun]:
        limit = max(1, min(limit, 1000))
        current = now or datetime.now(timezone.utc)
        due_schedules = list(
            session.scalars(
                select(DatasetDateCompletenessSchedule)
                .where(DatasetDateCompletenessSchedule.status == "active")
                .where(or_(DatasetDateCompletenessSchedule.next_run_at.is_(None), DatasetDateCompletenessSchedule.next_run_at <= current))
                .order_by(DatasetDateCompletenessSchedule.next_run_at.asc(), DatasetDateCompletenessSchedule.id.asc())
                .limit(limit)
            )
        )
        runs: list[DatasetDateCompletenessRun] = []
        for schedule in due_schedules:
            start_date, end_date = self._resolve_schedule_window(session, schedule=schedule, now=current)
            run = DateCompletenessRunCommandService().create_scheduled_run(
                session,
                dataset_key=schedule.dataset_key,
                start_date=start_date,
                end_date=end_date,
                schedule_id=schedule.id,
            )
            schedule.last_run_id = run.id
            schedule.next_run_at = self._compute_next_run_at(
                cron_expr=schedule.cron_expr,
                timezone_name=schedule.timezone,
                after=current,
            )
            session.commit()
            session.refresh(run)
            runs.append(run)
        return runs

    @classmethod
    def _validated_window_values(
        cls,
        *,
        window_mode: str,
        start_date: date | None,
        end_date: date | None,
        lookback_count: int | None,
        lookback_unit: str | None,
    ) -> dict:
        if window_mode not in cls.VALID_WINDOW_MODES:
            raise WebAppError(status_code=422, code="validation_error", message="审计窗口模式无效")
        if window_mode == "fixed_range":
            if start_date is None or end_date is None:
                raise WebAppError(status_code=422, code="validation_error", message="固定范围必须填写开始日期和结束日期")
            if start_date > end_date:
                raise WebAppError(status_code=422, code="validation_error", message="审计开始日期不能晚于结束日期")
            return {
                "window_mode": window_mode,
                "start_date": start_date,
                "end_date": end_date,
                "lookback_count": None,
                "lookback_unit": None,
            }
        if lookback_count is None or int(lookback_count) <= 0:
            raise WebAppError(status_code=422, code="validation_error", message="滚动窗口数量必须大于 0")
        if lookback_unit not in cls.VALID_LOOKBACK_UNITS:
            raise WebAppError(status_code=422, code="validation_error", message="滚动窗口单位无效")
        return {
            "window_mode": window_mode,
            "start_date": None,
            "end_date": None,
            "lookback_count": int(lookback_count),
            "lookback_unit": lookback_unit,
        }

    def _resolve_schedule_window(
        self,
        session: Session,
        *,
        schedule: DatasetDateCompletenessSchedule,
        now: datetime,
    ) -> tuple[date, date]:
        if schedule.window_mode == "fixed_range":
            if schedule.start_date is None or schedule.end_date is None:
                raise WebAppError(status_code=422, code="validation_error", message="固定范围审计计划缺少日期范围")
            return schedule.start_date, schedule.end_date

        zone = ensure_timezone(schedule.timezone)
        local_today = now.astimezone(zone).date()
        count = int(schedule.lookback_count or 0)
        unit = schedule.lookback_unit
        if count <= 0 or unit not in self.VALID_LOOKBACK_UNITS:
            raise WebAppError(status_code=422, code="validation_error", message="滚动窗口配置无效")
        if unit == "calendar_day":
            return local_today - timedelta(days=count - 1), local_today
        if unit == "month":
            start_month = _add_months(date(local_today.year, local_today.month, 1), -(count - 1))
            end_date = date(local_today.year, local_today.month, monthrange(local_today.year, local_today.month)[1])
            return start_month, end_date
        return self._open_day_window(session, local_today=local_today, count=count, schedule=schedule)

    def _open_day_window(
        self,
        session: Session,
        *,
        local_today: date,
        count: int,
        schedule: DatasetDateCompletenessSchedule,
    ) -> tuple[date, date]:
        exchange = self._calendar_exchange(schedule)
        open_dates = list(
            session.scalars(
                select(TradeCalendar.trade_date)
                .where(TradeCalendar.exchange == exchange)
                .where(TradeCalendar.trade_date <= local_today)
                .where(TradeCalendar.is_open.is_(True))
                .order_by(TradeCalendar.trade_date.desc())
                .limit(count)
            )
        )
        if not open_dates:
            raise WebAppError(status_code=422, code="validation_error", message="交易日历缺少开市日期，无法生成审计窗口")
        selected = sorted(open_dates)
        return selected[0], selected[-1]

    @staticmethod
    def _calendar_exchange(schedule: DatasetDateCompletenessSchedule) -> str:
        if schedule.calendar_scope == "custom_exchange":
            return str(schedule.calendar_exchange or "").strip().upper()
        return get_settings().default_exchange

    @classmethod
    def _ensure_status(cls, status: str) -> None:
        if status not in cls.VALID_STATUSES:
            raise WebAppError(status_code=422, code="validation_error", message="自动审计状态无效")

    @classmethod
    def _ensure_calendar(cls, calendar_scope: str, calendar_exchange: object) -> None:
        if calendar_scope not in cls.SUPPORTED_CALENDAR_SCOPES:
            raise WebAppError(status_code=422, code="validation_error", message="第一版仅支持默认 A 股交易日历")
        if calendar_exchange not in (None, ""):
            raise WebAppError(status_code=422, code="validation_error", message="第一版不支持自定义交易所日历")

    @staticmethod
    def _compute_next_run_at(*, cron_expr: str, timezone_name: str, after: datetime) -> datetime:
        next_run_at = compute_next_run_at(
            schedule_type="cron",
            cron_expr=cron_expr.strip(),
            timezone_name=timezone_name,
            after=after,
        )
        if next_run_at is None:
            raise WebAppError(status_code=422, code="validation_error", message="周期排程无法生成下次运行时间")
        return next_run_at

    @staticmethod
    def _get_supported_definition(dataset_key: str) -> DatasetDefinition:
        normalized = dataset_key.strip()
        if not normalized:
            raise WebAppError(status_code=422, code="validation_error", message="数据集不能为空")
        try:
            definition = get_dataset_definition(normalized)
        except KeyError as exc:
            raise WebAppError(status_code=404, code="not_found", message="数据集定义不存在") from exc
        if not definition.date_model.audit_applicable:
            raise WebAppError(status_code=422, code="audit_not_applicable", message="该数据集不支持日期完整性审计")
        if not definition.date_model.observed_field:
            raise WebAppError(status_code=422, code="audit_not_applicable", message="该数据集缺少审计观测日期字段")
        return definition

    @staticmethod
    def _display_name(display_name: str | None, definition: DatasetDefinition) -> str:
        return display_name.strip() if display_name and display_name.strip() else f"{definition.display_name} 日期完整性审计"

    @staticmethod
    def _required_text(value: object, label: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise WebAppError(status_code=422, code="validation_error", message=f"{label}不能为空")
        return text

    @staticmethod
    def _get_schedule(session: Session, schedule_id: int) -> DatasetDateCompletenessSchedule:
        schedule = session.get(DatasetDateCompletenessSchedule, schedule_id)
        if schedule is None:
            raise WebAppError(status_code=404, code="not_found", message="日期完整性自动审计不存在")
        return schedule


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)
