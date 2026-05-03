from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.ops.models.ops.dataset_date_completeness_exclusion import DatasetDateCompletenessExclusion
from src.ops.models.ops.dataset_date_completeness_gap import DatasetDateCompletenessGap
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.schemas.date_completeness import (
    DateCompletenessExclusionItem,
    DateCompletenessExclusionListResponse,
    DateCompletenessGapItem,
    DateCompletenessGapListResponse,
    DateCompletenessRunItem,
    DateCompletenessRunListResponse,
)


class DateCompletenessRunQueryService:
    def list_runs(
        self,
        session: Session,
        *,
        dataset_key: str | None = None,
        run_status: str | None = None,
        result_status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> DateCompletenessRunListResponse:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters = self._filters(dataset_key=dataset_key, run_status=run_status, result_status=result_status)

        count_stmt = select(func.count()).select_from(DatasetDateCompletenessRun)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = int(session.scalar(count_stmt) or 0)

        stmt = (
            select(DatasetDateCompletenessRun)
            .order_by(desc(DatasetDateCompletenessRun.requested_at), desc(DatasetDateCompletenessRun.id))
            .limit(limit)
            .offset(offset)
        )
        if filters:
            stmt = stmt.where(*filters)
        runs = list(session.scalars(stmt))
        return DateCompletenessRunListResponse(total=total, items=[self._run_item(run) for run in runs])

    def get_run(self, session: Session, run_id: int) -> DateCompletenessRunItem:
        run = session.get(DatasetDateCompletenessRun, run_id)
        if run is None:
            raise WebAppError(status_code=404, code="not_found", message="日期完整性审计记录不存在")
        return self._run_item(run)

    def list_gaps(
        self,
        session: Session,
        run_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> DateCompletenessGapListResponse:
        if session.get(DatasetDateCompletenessRun, run_id) is None:
            raise WebAppError(status_code=404, code="not_found", message="日期完整性审计记录不存在")

        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        count_stmt = (
            select(func.count())
            .select_from(DatasetDateCompletenessGap)
            .where(DatasetDateCompletenessGap.run_id == run_id)
        )
        total = int(session.scalar(count_stmt) or 0)
        stmt = (
            select(DatasetDateCompletenessGap)
            .where(DatasetDateCompletenessGap.run_id == run_id)
            .order_by(DatasetDateCompletenessGap.range_start.asc(), DatasetDateCompletenessGap.id.asc())
            .limit(limit)
            .offset(offset)
        )
        gaps = list(session.scalars(stmt))
        return DateCompletenessGapListResponse(total=total, items=[self._gap_item(gap) for gap in gaps])

    def list_exclusions(
        self,
        session: Session,
        run_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> DateCompletenessExclusionListResponse:
        if session.get(DatasetDateCompletenessRun, run_id) is None:
            raise WebAppError(status_code=404, code="not_found", message="日期完整性审计记录不存在")

        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        count_stmt = (
            select(func.count())
            .select_from(DatasetDateCompletenessExclusion)
            .where(DatasetDateCompletenessExclusion.run_id == run_id)
        )
        total = int(session.scalar(count_stmt) or 0)
        stmt = (
            select(DatasetDateCompletenessExclusion)
            .where(DatasetDateCompletenessExclusion.run_id == run_id)
            .order_by(DatasetDateCompletenessExclusion.bucket_value.asc(), DatasetDateCompletenessExclusion.id.asc())
            .limit(limit)
            .offset(offset)
        )
        exclusions = list(session.scalars(stmt))
        return DateCompletenessExclusionListResponse(
            total=total,
            items=[self._exclusion_item(item) for item in exclusions],
        )

    @staticmethod
    def _filters(
        *,
        dataset_key: str | None,
        run_status: str | None,
        result_status: str | None,
    ) -> list:
        filters = []
        if dataset_key:
            filters.append(DatasetDateCompletenessRun.dataset_key == dataset_key)
        if run_status:
            filters.append(DatasetDateCompletenessRun.run_status == run_status)
        if result_status:
            filters.append(DatasetDateCompletenessRun.result_status == result_status)
        return filters

    @staticmethod
    def _run_item(run: DatasetDateCompletenessRun) -> DateCompletenessRunItem:
        return DateCompletenessRunItem(
            id=run.id,
            dataset_key=run.dataset_key,
            display_name=run.display_name,
            target_table=run.target_table,
            run_mode=run.run_mode,
            run_status=run.run_status,
            result_status=run.result_status,
            start_date=run.start_date,
            end_date=run.end_date,
            date_axis=run.date_axis,
            bucket_rule=run.bucket_rule,
            window_mode=run.window_mode,
            input_shape=run.input_shape,
            observed_field=run.observed_field,
            bucket_window_rule=run.bucket_window_rule,
            bucket_applicability_rule=run.bucket_applicability_rule,
            expected_bucket_count=run.expected_bucket_count,
            actual_bucket_count=run.actual_bucket_count,
            missing_bucket_count=run.missing_bucket_count,
            excluded_bucket_count=run.excluded_bucket_count,
            gap_range_count=run.gap_range_count,
            current_stage=run.current_stage,
            operator_message=run.operator_message,
            technical_message=run.technical_message,
            requested_by_user_id=run.requested_by_user_id,
            schedule_id=run.schedule_id,
            requested_at=run.requested_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    @staticmethod
    def _gap_item(gap: DatasetDateCompletenessGap) -> DateCompletenessGapItem:
        return DateCompletenessGapItem(
            id=gap.id,
            run_id=gap.run_id,
            dataset_key=gap.dataset_key,
            bucket_kind=gap.bucket_kind,
            range_start=gap.range_start,
            range_end=gap.range_end,
            missing_count=gap.missing_count,
            sample_values=[str(value) for value in list(gap.sample_values_json or [])],
            created_at=gap.created_at,
        )

    @staticmethod
    def _exclusion_item(item: DatasetDateCompletenessExclusion) -> DateCompletenessExclusionItem:
        return DateCompletenessExclusionItem(
            id=item.id,
            run_id=item.run_id,
            dataset_key=item.dataset_key,
            bucket_kind=item.bucket_kind,
            bucket_value=item.bucket_value,
            window_start=item.window_start,
            window_end=item.window_end,
            reason_code=item.reason_code,
            reason_message=item.reason_message,
            created_at=item.created_at,
        )
