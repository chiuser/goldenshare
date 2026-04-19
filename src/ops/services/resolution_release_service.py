from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.auth.domain import AuthenticatedUser
from src.ops.models.ops.config_revision import ConfigRevision
from src.ops.models.ops.resolution_release import ResolutionRelease
from src.ops.models.ops.resolution_release_stage_status import ResolutionReleaseStageStatus
from src.ops.queries.resolution_release_query_service import ResolutionReleaseQueryService
from src.app.exceptions import WebAppError


class OpsResolutionReleaseCommandService:
    def create_release(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        dataset_key: str,
        target_policy_version: int,
        status: str = "previewing",
        rollback_to_release_id: int | None = None,
    ) -> int:
        self._validate_release_inputs(dataset_key=dataset_key, target_policy_version=target_policy_version, status=status)
        now = datetime.now(timezone.utc)
        release = ResolutionRelease(
            dataset_key=dataset_key.strip(),
            target_policy_version=target_policy_version,
            status=status,
            triggered_by_user_id=user.id,
            triggered_at=now,
            rollback_to_release_id=rollback_to_release_id,
        )
        session.add(release)
        session.flush()
        self._record_revision(
            session,
            object_id=str(release.id),
            action="created",
            before_json=None,
            after_json=self._snapshot(release),
            changed_by_user_id=user.id,
        )
        session.commit()
        session.refresh(release)
        return release.id

    def update_release_status(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        release_id: int,
        status: str,
        finished_at: datetime | None = None,
    ) -> int:
        self._ensure_release_status(status)
        release = session.scalar(select(ResolutionRelease).where(ResolutionRelease.id == release_id))
        if release is None:
            raise WebAppError(status_code=404, code="not_found", message="Resolution release does not exist")

        before = self._snapshot(release)
        release.status = status
        release.finished_at = finished_at or release.finished_at
        if status in {"completed", "rolled_back", "failed"} and release.finished_at is None:
            release.finished_at = datetime.now(timezone.utc)
        after = self._snapshot(release)
        if before == after:
            session.refresh(release)
            return release.id

        self._record_revision(
            session,
            object_id=str(release.id),
            action="status_updated",
            before_json=before,
            after_json=after,
            changed_by_user_id=user.id,
        )
        session.commit()
        session.refresh(release)
        return release.id

    def upsert_release_stage_statuses(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        release_id: int,
        items: list[dict],
    ) -> int:
        release = session.scalar(select(ResolutionRelease).where(ResolutionRelease.id == release_id))
        if release is None:
            raise WebAppError(status_code=404, code="not_found", message="Resolution release does not exist")
        if not items:
            raise WebAppError(status_code=422, code="validation_error", message="items cannot be empty")

        now = datetime.now(timezone.utc)
        upserted_count = 0
        for item in items:
            self._validate_stage_item(item)
            clause = ResolutionReleaseQueryService.stage_key_clause(
                release_id=release_id,
                dataset_key=item["dataset_key"],
                source_key=item.get("source_key"),
                stage=item["stage"],
            )
            stage_row = session.scalar(select(ResolutionReleaseStageStatus).where(clause))
            updated_at = item.get("updated_at") or now
            if stage_row is None:
                stage_row = ResolutionReleaseStageStatus(
                    release_id=release_id,
                    dataset_key=item["dataset_key"],
                    source_key=item.get("source_key"),
                    stage=item["stage"],
                    status=item["status"],
                    rows_in=item.get("rows_in"),
                    rows_out=item.get("rows_out"),
                    message=item.get("message"),
                    updated_at=updated_at,
                )
                session.add(stage_row)
            else:
                stage_row.status = item["status"]
                stage_row.rows_in = item.get("rows_in")
                stage_row.rows_out = item.get("rows_out")
                stage_row.message = item.get("message")
                stage_row.updated_at = updated_at
            upserted_count += 1

        self._record_revision(
            session,
            object_id=str(release.id),
            action="stage_status_upserted",
            before_json=None,
            after_json={"upserted_count": upserted_count},
            changed_by_user_id=user.id,
        )
        session.commit()
        return release_id

    @staticmethod
    def _validate_release_inputs(*, dataset_key: str, target_policy_version: int, status: str) -> None:
        if not dataset_key.strip():
            raise WebAppError(status_code=422, code="validation_error", message="dataset_key cannot be empty")
        if target_policy_version <= 0:
            raise WebAppError(status_code=422, code="validation_error", message="target_policy_version must be greater than 0")
        OpsResolutionReleaseCommandService._ensure_release_status(status)

    @staticmethod
    def _validate_stage_item(item: dict) -> None:
        if not str(item.get("dataset_key") or "").strip():
            raise WebAppError(status_code=422, code="validation_error", message="dataset_key is required in stage item")
        if not str(item.get("stage") or "").strip():
            raise WebAppError(status_code=422, code="validation_error", message="stage is required in stage item")
        if not str(item.get("status") or "").strip():
            raise WebAppError(status_code=422, code="validation_error", message="status is required in stage item")

    @staticmethod
    def _ensure_release_status(status: str) -> None:
        if status not in {"previewing", "running", "completed", "rolled_back", "failed"}:
            raise WebAppError(
                status_code=422,
                code="validation_error",
                message="status must be previewing/running/completed/rolled_back/failed",
            )

    @staticmethod
    def _snapshot(release: ResolutionRelease) -> dict:
        return {
            "id": release.id,
            "dataset_key": release.dataset_key,
            "target_policy_version": release.target_policy_version,
            "status": release.status,
            "triggered_by_user_id": release.triggered_by_user_id,
            "triggered_at": release.triggered_at.isoformat() if release.triggered_at else None,
            "finished_at": release.finished_at.isoformat() if release.finished_at else None,
            "rollback_to_release_id": release.rollback_to_release_id,
        }

    @staticmethod
    def _record_revision(
        session: Session,
        *,
        object_id: str,
        action: str,
        before_json: dict | None,
        after_json: dict | None,
        changed_by_user_id: int,
    ) -> None:
        session.add(
            ConfigRevision(
                object_type="resolution_release",
                object_id=object_id,
                action=action,
                before_json=before_json,
                after_json=after_json,
                changed_by_user_id=changed_by_user_id,
                changed_at=datetime.now(timezone.utc),
            )
        )
