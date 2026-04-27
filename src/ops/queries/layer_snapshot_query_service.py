from __future__ import annotations

from datetime import date

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.foundation.datasets.source_registry import get_source_display_name
from src.ops.dataset_labels import get_dataset_display_name
from src.ops.layer_stage_labels import get_layer_stage_display_name
from src.ops.models.ops.dataset_layer_snapshot_current import DatasetLayerSnapshotCurrent
from src.ops.models.ops.dataset_layer_snapshot_history import DatasetLayerSnapshotHistory
from src.ops.schemas.layer_snapshot import (
    LayerSnapshotHistoryItem,
    LayerSnapshotHistoryResponse,
    LayerSnapshotLatestItem,
    LayerSnapshotLatestResponse,
)


class LayerSnapshotQueryService:
    def list_history(
        self,
        session: Session,
        *,
        snapshot_date_from: date | None = None,
        snapshot_date_to: date | None = None,
        dataset_key: str | None = None,
        source_key: str | None = None,
        stage: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> LayerSnapshotHistoryResponse:
        limit = max(1, min(limit, 1000))
        filters = []
        if snapshot_date_from:
            filters.append(DatasetLayerSnapshotHistory.snapshot_date >= snapshot_date_from)
        if snapshot_date_to:
            filters.append(DatasetLayerSnapshotHistory.snapshot_date <= snapshot_date_to)
        if dataset_key:
            filters.append(DatasetLayerSnapshotHistory.dataset_key == dataset_key)
        if source_key:
            filters.append(DatasetLayerSnapshotHistory.source_key == source_key)
        if stage:
            filters.append(DatasetLayerSnapshotHistory.stage == stage)
        if status:
            filters.append(DatasetLayerSnapshotHistory.status == status)

        count_stmt = select(func.count()).select_from(DatasetLayerSnapshotHistory)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = session.scalar(count_stmt) or 0

        stmt = (
            select(DatasetLayerSnapshotHistory)
            .order_by(
                desc(DatasetLayerSnapshotHistory.snapshot_date),
                desc(DatasetLayerSnapshotHistory.calculated_at),
                desc(DatasetLayerSnapshotHistory.id),
            )
            .limit(limit)
            .offset(max(0, offset))
        )
        if filters:
            stmt = stmt.where(*filters)
        rows = session.scalars(stmt).all()
        return LayerSnapshotHistoryResponse(
            total=total,
            items=[self._to_history_item(row) for row in rows],
        )

    def list_latest(
        self,
        session: Session,
        *,
        dataset_key: str | None = None,
        source_key: str | None = None,
        stage: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> LayerSnapshotLatestResponse:
        """
        latest 语义应读取当前快照表（dataset_layer_snapshot_current）。
        """
        limit = max(1, min(limit, 5000))
        filters = []
        if dataset_key:
            filters.append(DatasetLayerSnapshotCurrent.dataset_key == dataset_key)
        if source_key:
            normalized_source = source_key.strip()
            filters.append(DatasetLayerSnapshotCurrent.source_key.in_([normalized_source, "combined"]))
        if stage:
            filters.append(DatasetLayerSnapshotCurrent.stage == stage)
        if status:
            filters.append(DatasetLayerSnapshotCurrent.status == status)

        count_stmt = select(func.count()).select_from(DatasetLayerSnapshotCurrent)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = session.scalar(count_stmt) or 0

        stmt = select(DatasetLayerSnapshotCurrent).order_by(
            desc(DatasetLayerSnapshotCurrent.calculated_at),
            desc(DatasetLayerSnapshotCurrent.dataset_key),
            desc(DatasetLayerSnapshotCurrent.source_key),
            desc(DatasetLayerSnapshotCurrent.stage),
        )
        if filters:
            stmt = stmt.where(*filters)
        rows = session.scalars(stmt.limit(limit)).all()

        if not rows:
            return self._list_latest_from_history(
                session,
                dataset_key=dataset_key,
                source_key=source_key,
                stage=stage,
                status=status,
                limit=limit,
            )

        items: list[LayerSnapshotLatestItem] = []
        for row in rows:
            items.append(
                LayerSnapshotLatestItem(
                    snapshot_date=row.calculated_at.date(),
                    dataset_key=row.dataset_key,
                    dataset_display_name=_require_dataset_display_name(row.dataset_key),
                    source_key=row.source_key,
                    source_display_name=_require_source_display_name(row.source_key),
                    stage=row.stage,
                    stage_display_name=_require_stage_display_name(row.stage),
                    status=row.status,
                    rows_in=row.rows_in,
                    rows_out=row.rows_out,
                    error_count=row.error_count,
                    last_success_at=row.last_success_at,
                    last_failure_at=row.last_failure_at,
                    lag_seconds=row.lag_seconds,
                    message=row.message,
                    calculated_at=row.calculated_at,
                )
            )
        return LayerSnapshotLatestResponse(total=int(total), items=items)

    def _list_latest_from_history(
        self,
        session: Session,
        *,
        dataset_key: str | None,
        source_key: str | None,
        stage: str | None,
        status: str | None,
        limit: int,
    ) -> LayerSnapshotLatestResponse:
        history_filters = []
        if dataset_key:
            history_filters.append(DatasetLayerSnapshotHistory.dataset_key == dataset_key)
        if source_key:
            normalized_source = source_key.strip()
            history_filters.append(DatasetLayerSnapshotHistory.source_key.in_([normalized_source, "combined"]))
        if stage:
            history_filters.append(DatasetLayerSnapshotHistory.stage == stage)
        if status:
            history_filters.append(DatasetLayerSnapshotHistory.status == status)

        history_stmt = select(DatasetLayerSnapshotHistory).order_by(
            desc(DatasetLayerSnapshotHistory.snapshot_date),
            desc(DatasetLayerSnapshotHistory.calculated_at),
            desc(DatasetLayerSnapshotHistory.id),
        )
        if history_filters:
            history_stmt = history_stmt.where(*history_filters)
        history_rows = session.scalars(history_stmt).all()

        unique_items: list[LayerSnapshotLatestItem] = []
        seen_keys: set[tuple[str, str, str]] = set()
        for row in history_rows:
            key = (row.dataset_key, row.source_key, row.stage)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique_items.append(
                LayerSnapshotLatestItem(
                    snapshot_date=row.snapshot_date,
                    dataset_key=row.dataset_key,
                    dataset_display_name=_require_dataset_display_name(row.dataset_key),
                    source_key=row.source_key,
                    source_display_name=_require_source_display_name(row.source_key),
                    stage=row.stage,
                    stage_display_name=_require_stage_display_name(row.stage),
                    status=row.status,
                    rows_in=row.rows_in,
                    rows_out=row.rows_out,
                    error_count=row.error_count,
                    last_success_at=row.last_success_at,
                    last_failure_at=row.last_failure_at,
                    lag_seconds=row.lag_seconds,
                    message=row.message,
                    calculated_at=row.calculated_at,
                )
            )
        return LayerSnapshotLatestResponse(total=len(unique_items), items=unique_items[:limit])

    @staticmethod
    def _to_history_item(row: DatasetLayerSnapshotHistory) -> LayerSnapshotHistoryItem:
        return LayerSnapshotHistoryItem(
            id=row.id,
            snapshot_date=row.snapshot_date,
            dataset_key=row.dataset_key,
            dataset_display_name=_require_dataset_display_name(row.dataset_key),
            source_key=row.source_key,
            source_display_name=_require_source_display_name(row.source_key),
            stage=row.stage,
            stage_display_name=_require_stage_display_name(row.stage),
            status=row.status,
            rows_in=row.rows_in,
            rows_out=row.rows_out,
            error_count=row.error_count,
            last_success_at=row.last_success_at,
            last_failure_at=row.last_failure_at,
            lag_seconds=row.lag_seconds,
            message=row.message,
            calculated_at=row.calculated_at,
        )


def _require_dataset_display_name(dataset_key: str | None) -> str:
    display_name = get_dataset_display_name(dataset_key)
    if display_name is None:
        raise WebAppError(status_code=422, code="validation_error", message="Layer snapshot dataset display name is unavailable")
    return display_name


def _require_source_display_name(source_key: str | None) -> str:
    display_name = get_source_display_name(source_key or "combined")
    if display_name is None:
        raise WebAppError(status_code=422, code="validation_error", message="Layer snapshot source display name is unavailable")
    return display_name


def _require_stage_display_name(stage: str | None) -> str:
    display_name = get_layer_stage_display_name(stage)
    if display_name is None:
        raise WebAppError(status_code=422, code="validation_error", message="Layer snapshot stage display name is unavailable")
    return display_name
