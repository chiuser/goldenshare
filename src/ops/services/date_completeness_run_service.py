from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from src.app.auth.domain import AuthenticatedUser
from src.app.exceptions import WebAppError
from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import get_dataset_definition
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.schemas.date_completeness import DateCompletenessRunCreateRequest


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

        date_model = definition.date_model
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
