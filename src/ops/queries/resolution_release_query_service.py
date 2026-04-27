from __future__ import annotations

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session, aliased

from src.app.models.app_user import AppUser
from src.foundation.datasets.source_registry import get_source_display_name
from src.ops.dataset_labels import get_dataset_display_name
from src.ops.layer_stage_labels import get_layer_stage_display_name
from src.ops.models.ops.resolution_release import ResolutionRelease
from src.ops.models.ops.resolution_release_stage_status import ResolutionReleaseStageStatus
from src.app.exceptions import WebAppError
from src.ops.schemas.resolution_release import (
    ResolutionReleaseDetailResponse,
    ResolutionReleaseListItem,
    ResolutionReleaseListResponse,
    ResolutionReleaseStageStatusItem,
    ResolutionReleaseStageStatusListResponse,
)


class ResolutionReleaseQueryService:
    def list_releases(
        self,
        session: Session,
        *,
        dataset_key: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ResolutionReleaseListResponse:
        limit = max(1, min(limit, 200))
        filters = []
        if dataset_key:
            filters.append(ResolutionRelease.dataset_key == dataset_key)
        if status:
            filters.append(ResolutionRelease.status == status)

        count_stmt = select(func.count()).select_from(ResolutionRelease)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = session.scalar(count_stmt) or 0

        triggered_by = aliased(AppUser)
        stmt = (
            select(ResolutionRelease, triggered_by.username)
            .outerjoin(triggered_by, triggered_by.id == ResolutionRelease.triggered_by_user_id)
            .order_by(desc(ResolutionRelease.triggered_at), desc(ResolutionRelease.id))
            .limit(limit)
            .offset(offset)
        )
        if filters:
            stmt = stmt.where(*filters)
        rows = session.execute(stmt).all()
        return ResolutionReleaseListResponse(
            total=total,
            items=[self._list_item(release, username) for release, username in rows],
        )

    def get_release_detail(self, session: Session, release_id: int) -> ResolutionReleaseDetailResponse:
        triggered_by = aliased(AppUser)
        stmt = (
            select(ResolutionRelease, triggered_by.username)
            .outerjoin(triggered_by, triggered_by.id == ResolutionRelease.triggered_by_user_id)
            .where(ResolutionRelease.id == release_id)
        )
        row = session.execute(stmt).one_or_none()
        if row is None:
            raise WebAppError(status_code=404, code="not_found", message="Resolution release does not exist")
        release, username = row
        item = self._list_item(release, username)
        return ResolutionReleaseDetailResponse(**item.model_dump())

    def list_release_stage_statuses(
        self,
        session: Session,
        *,
        release_id: int,
        dataset_key: str | None = None,
        source_key: str | None = None,
        stage: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> ResolutionReleaseStageStatusListResponse:
        release_exists = session.scalar(select(ResolutionRelease.id).where(ResolutionRelease.id == release_id))
        if release_exists is None:
            raise WebAppError(status_code=404, code="not_found", message="Resolution release does not exist")

        filters = [ResolutionReleaseStageStatus.release_id == release_id]
        if dataset_key:
            filters.append(ResolutionReleaseStageStatus.dataset_key == dataset_key)
        if source_key:
            filters.append(ResolutionReleaseStageStatus.source_key == source_key)
        if stage:
            filters.append(ResolutionReleaseStageStatus.stage == stage)

        count_stmt = select(func.count()).select_from(ResolutionReleaseStageStatus).where(*filters)
        total = session.scalar(count_stmt) or 0

        stmt = (
            select(ResolutionReleaseStageStatus)
            .where(*filters)
            .order_by(
                desc(ResolutionReleaseStageStatus.updated_at),
                ResolutionReleaseStageStatus.dataset_key.asc(),
                ResolutionReleaseStageStatus.source_key.asc(),
                ResolutionReleaseStageStatus.stage.asc(),
            )
            .limit(max(1, min(limit, 500)))
            .offset(max(0, offset))
        )
        rows = session.scalars(stmt).all()
        return ResolutionReleaseStageStatusListResponse(
            total=total,
            items=[
                ResolutionReleaseStageStatusItem(
                    id=item.id,
                    release_id=item.release_id,
                    dataset_key=item.dataset_key,
                    dataset_display_name=_require_dataset_display_name(item.dataset_key),
                    source_key=item.source_key,
                    source_display_name=_require_source_display_name(item.source_key),
                    stage=item.stage,
                    stage_display_name=_require_stage_display_name(item.stage),
                    status=item.status,
                    rows_in=item.rows_in,
                    rows_out=item.rows_out,
                    message=item.message,
                    updated_at=item.updated_at,
                )
                for item in rows
            ],
        )

    @staticmethod
    def _list_item(release: ResolutionRelease, username: str | None) -> ResolutionReleaseListItem:
        return ResolutionReleaseListItem(
            id=release.id,
            dataset_key=release.dataset_key,
            dataset_display_name=_require_dataset_display_name(release.dataset_key),
            target_policy_version=release.target_policy_version,
            status=release.status,
            triggered_by_username=username,
            triggered_at=release.triggered_at,
            finished_at=release.finished_at,
            rollback_to_release_id=release.rollback_to_release_id,
            created_at=release.created_at,
            updated_at=release.updated_at,
        )

    @staticmethod
    def stage_key_clause(
        *,
        release_id: int,
        dataset_key: str,
        source_key: str | None,
        stage: str,
    ):
        if source_key is None:
            source_condition = ResolutionReleaseStageStatus.source_key.is_(None)
        else:
            source_condition = ResolutionReleaseStageStatus.source_key == source_key
        return and_(
            ResolutionReleaseStageStatus.release_id == release_id,
            ResolutionReleaseStageStatus.dataset_key == dataset_key,
            source_condition,
            ResolutionReleaseStageStatus.stage == stage,
        )


def _require_dataset_display_name(dataset_key: str | None) -> str:
    display_name = get_dataset_display_name(dataset_key)
    if display_name is None:
        raise WebAppError(status_code=422, code="validation_error", message="Resolution release dataset display name is unavailable")
    return display_name


def _require_source_display_name(source_key: str | None) -> str:
    display_name = get_source_display_name(source_key or "combined")
    if display_name is None:
        raise WebAppError(status_code=422, code="validation_error", message="Resolution release source display name is unavailable")
    return display_name


def _require_stage_display_name(stage: str | None) -> str:
    display_name = get_layer_stage_display_name(stage)
    if display_name is None:
        raise WebAppError(status_code=422, code="validation_error", message="Resolution release stage display name is unavailable")
    return display_name
