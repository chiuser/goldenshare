from __future__ import annotations

from datetime import date

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

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
        SQLite/PG 通用最小实现：按时间倒序拉取后在 Python 侧按 (dataset, source, stage) 去重。
        """
        limit = max(1, min(limit, 5000))
        filters = []
        if dataset_key:
            filters.append(DatasetLayerSnapshotHistory.dataset_key == dataset_key)
        if source_key:
            filters.append(DatasetLayerSnapshotHistory.source_key == source_key)
        if stage:
            filters.append(DatasetLayerSnapshotHistory.stage == stage)
        if status:
            filters.append(DatasetLayerSnapshotHistory.status == status)

        stmt = select(DatasetLayerSnapshotHistory).order_by(
            desc(DatasetLayerSnapshotHistory.snapshot_date),
            desc(DatasetLayerSnapshotHistory.calculated_at),
            desc(DatasetLayerSnapshotHistory.id),
        )
        if filters:
            stmt = stmt.where(*filters)
        rows = session.scalars(stmt.limit(limit * 20)).all()

        dedup: dict[tuple[str, str | None, str], LayerSnapshotLatestItem] = {}
        for row in rows:
            key = (row.dataset_key, row.source_key, row.stage)
            if key in dedup:
                continue
            dedup[key] = LayerSnapshotLatestItem(
                snapshot_date=row.snapshot_date,
                dataset_key=row.dataset_key,
                source_key=row.source_key,
                stage=row.stage,
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
            if len(dedup) >= limit:
                break

        items = list(dedup.values())
        return LayerSnapshotLatestResponse(total=len(items), items=items)

    @staticmethod
    def _to_history_item(row: DatasetLayerSnapshotHistory) -> LayerSnapshotHistoryItem:
        return LayerSnapshotHistoryItem(
            id=row.id,
            snapshot_date=row.snapshot_date,
            dataset_key=row.dataset_key,
            source_key=row.source_key,
            stage=row.stage,
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
