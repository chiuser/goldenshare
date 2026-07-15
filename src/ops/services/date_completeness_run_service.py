from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.auth.domain import AuthenticatedUser
from src.app.exceptions import WebAppError
from src.foundation.config.settings import get_settings
from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.schemas.date_completeness import DateCompletenessRunCreateRequest
from src.ops.services.date_completeness_audit_service import DATE_SUBJECT_MATRIX_SAFE_BUCKET_LIMIT, ExpectedBucketPlanner


class DateCompletenessRunCommandService:
    def create_manual_run(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        payload: DateCompletenessRunCreateRequest,
    ) -> DatasetDateCompletenessRun:
        definition = self._get_definition(payload.dataset_key)
        self._ensure_supported(definition)
        if payload.start_date > payload.end_date:
            raise WebAppError(status_code=422, code="validation_error", message="审计开始日期不能晚于结束日期")
        self._ensure_safe_manual_range(
            session,
            definition=definition,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )

        date_model = definition.date_model
        completeness = definition.completeness
        now = datetime.now(timezone.utc)
        run = DatasetDateCompletenessRun(
            dataset_key=definition.dataset_key,
            display_name=definition.display_name,
            target_table=definition.storage.target_table,
            run_mode="manual",
            run_status="queued",
            result_status=None,
            start_date=payload.start_date,
            end_date=payload.end_date,
            date_axis=date_model.date_axis,
            bucket_rule=date_model.bucket_rule,
            window_mode=date_model.window_mode,
            input_shape=date_model.input_shape,
            observed_field=str(date_model.observed_field),
            bucket_window_rule=date_model.bucket_window_rule or "none",
            bucket_applicability_rule=date_model.bucket_applicability_rule,
            row_identity_filters_json=dict(definition.storage.row_identity_filters),
            audit_scope=completeness.scope if completeness.scope == "date_subject_matrix" else "date_bucket",
            subject_kind=completeness.subject_kind,
            current_stage="queued",
            operator_message="审计任务已创建，等待审计 worker 执行。",
            technical_message=None,
            requested_by_user_id=user.id,
            schedule_id=None,
            requested_at=now,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run

    def create_scheduled_run(
        self,
        session: Session,
        *,
        dataset_key: str,
        start_date: date,
        end_date: date,
        schedule_id: int,
    ) -> DatasetDateCompletenessRun:
        definition = self._get_definition(dataset_key)
        self._ensure_supported(definition)
        if start_date > end_date:
            raise WebAppError(status_code=422, code="validation_error", message="审计开始日期不能晚于结束日期")

        date_model = definition.date_model
        completeness = definition.completeness
        now = datetime.now(timezone.utc)
        run = DatasetDateCompletenessRun(
            dataset_key=definition.dataset_key,
            display_name=definition.display_name,
            target_table=definition.storage.target_table,
            run_mode="scheduled",
            run_status="queued",
            result_status=None,
            start_date=start_date,
            end_date=end_date,
            date_axis=date_model.date_axis,
            bucket_rule=date_model.bucket_rule,
            window_mode=date_model.window_mode,
            input_shape=date_model.input_shape,
            observed_field=str(date_model.observed_field),
            bucket_window_rule=date_model.bucket_window_rule or "none",
            bucket_applicability_rule=date_model.bucket_applicability_rule,
            row_identity_filters_json=dict(definition.storage.row_identity_filters),
            audit_scope=completeness.scope if completeness.scope == "date_subject_matrix" else "date_bucket",
            subject_kind=completeness.subject_kind,
            current_stage="queued",
            operator_message="自动审计任务已创建，等待审计 worker 执行。",
            technical_message=None,
            requested_by_user_id=None,
            schedule_id=schedule_id,
            requested_at=now,
        )
        session.add(run)
        session.flush()
        return run

    def create_system_run(
        self,
        session: Session,
        *,
        dataset_key: str,
        start_date: date,
        end_date: date,
        now: datetime | None = None,
    ) -> DatasetDateCompletenessRun:
        definition = self._get_definition(dataset_key)
        self._ensure_supported(definition)
        if start_date > end_date:
            raise WebAppError(status_code=422, code="validation_error", message="审计开始日期不能晚于结束日期")

        date_model = definition.date_model
        completeness = definition.completeness
        requested_at = now or datetime.now(timezone.utc)
        run = DatasetDateCompletenessRun(
            dataset_key=definition.dataset_key,
            display_name=definition.display_name,
            target_table=definition.storage.target_table,
            run_mode="scheduled",
            run_status="queued",
            result_status=None,
            start_date=start_date,
            end_date=end_date,
            date_axis=date_model.date_axis,
            bucket_rule=date_model.bucket_rule,
            window_mode=date_model.window_mode,
            input_shape=date_model.input_shape,
            observed_field=str(date_model.observed_field),
            bucket_window_rule=date_model.bucket_window_rule or "none",
            bucket_applicability_rule=date_model.bucket_applicability_rule,
            row_identity_filters_json=dict(definition.storage.row_identity_filters),
            audit_scope=completeness.scope if completeness.scope == "date_subject_matrix" else "date_bucket",
            subject_kind=completeness.subject_kind,
            current_stage="queued",
            operator_message="系统审计任务已创建，等待审计 worker 执行。",
            technical_message=None,
            requested_by_user_id=None,
            schedule_id=None,
            requested_at=requested_at,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run

    @staticmethod
    def _get_definition(dataset_key: str) -> DatasetDefinition:
        normalized = dataset_key.strip()
        if not normalized:
            raise WebAppError(status_code=422, code="validation_error", message="数据集不能为空")
        try:
            return get_dataset_definition(normalized)
        except KeyError as exc:
            raise WebAppError(status_code=404, code="not_found", message="数据集定义不存在") from exc

    @staticmethod
    def _ensure_supported(definition: DatasetDefinition) -> None:
        date_model = definition.date_model
        if not date_model.audit_applicable:
            raise WebAppError(status_code=422, code="audit_not_applicable", message="该数据集不支持日期完整性审计")
        if not date_model.observed_field:
            raise WebAppError(status_code=422, code="audit_not_applicable", message="该数据集缺少审计观测日期字段")

    def _ensure_safe_manual_range(
        self,
        session: Session,
        *,
        definition: DatasetDefinition,
        start_date: date,
        end_date: date,
    ) -> None:
        if definition.completeness.scope != "date_subject_matrix":
            return
        expected_count = self._expected_bucket_count(
            session,
            definition=definition,
            start_date=start_date,
            end_date=end_date,
        )
        if expected_count <= DATE_SUBJECT_MATRIX_SAFE_BUCKET_LIMIT:
            return
        raise WebAppError(
            status_code=422,
            code="date_subject_matrix_range_too_large",
            message=(
                "对象矩阵审计范围超过当前单次安全上限，"
                f"本次范围包含 {expected_count} 个日期桶，超过安全上限 {DATE_SUBJECT_MATRIX_SAFE_BUCKET_LIMIT} 个。"
                "请缩小日期范围后再创建审计。"
            ),
        )

    def _expected_bucket_count(
        self,
        session: Session,
        *,
        definition: DatasetDefinition,
        start_date: date,
        end_date: date,
    ) -> int:
        date_model = definition.date_model
        open_trade_dates = self._load_open_trade_dates(
            session,
            date_axis=date_model.date_axis,
            bucket_applicability_rule=date_model.bucket_applicability_rule,
            bucket_window_rule=date_model.bucket_window_rule or "none",
            start_date=start_date,
            end_date=end_date,
        )
        expected, _excluded = ExpectedBucketPlanner().plan_with_exclusions(
            date_axis=date_model.date_axis,
            bucket_rule=date_model.bucket_rule,
            start_date=start_date,
            end_date=end_date,
            open_trade_dates=open_trade_dates,
            bucket_window_rule=date_model.bucket_window_rule or "none",
            bucket_applicability_rule=date_model.bucket_applicability_rule,
        )
        return len(expected)

    @staticmethod
    def _load_open_trade_dates(
        session: Session,
        *,
        date_axis: str,
        bucket_applicability_rule: str,
        bucket_window_rule: str,
        start_date: date,
        end_date: date,
    ) -> list[date] | None:
        needs_open_dates = date_axis == "trade_open_day" or bucket_applicability_rule == "requires_open_trade_day_in_bucket"
        if not needs_open_dates:
            return None
        exchange = get_settings().default_exchange
        calendar_start, calendar_end = DateCompletenessRunCommandService._calendar_range(
            start_date=start_date,
            end_date=end_date,
            bucket_window_rule=bucket_window_rule,
        )
        return list(
            session.scalars(
                select(TradeCalendar.trade_date)
                .where(TradeCalendar.exchange == exchange)
                .where(TradeCalendar.trade_date >= calendar_start)
                .where(TradeCalendar.trade_date <= calendar_end)
                .where(TradeCalendar.is_open.is_(True))
                .order_by(TradeCalendar.trade_date.asc())
            )
        )

    @staticmethod
    def _calendar_range(*, start_date: date, end_date: date, bucket_window_rule: str) -> tuple[date, date]:
        if bucket_window_rule == "iso_week":
            calendar_start = start_date - timedelta(days=start_date.weekday())
            calendar_end = end_date + timedelta(days=6 - end_date.weekday())
            return calendar_start, calendar_end
        if bucket_window_rule == "natural_month":
            calendar_start = date(start_date.year, start_date.month, 1)
            calendar_end = date(end_date.year, end_date.month, monthrange(end_date.year, end_date.month)[1])
            return calendar_start, calendar_end
        return start_date, end_date
