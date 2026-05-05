from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.foundation.models.core.index_basic import IndexBasic
from src.ops.models.ops.index_series_active import IndexSeriesActive


class ReviewCenterCommandService:
    def add_active_index(
        self,
        session: Session,
        *,
        resource: str,
        ts_code: str,
    ) -> tuple[str, str]:
        normalized_resource = self._normalize_resource(resource)
        normalized_code = self._normalize_ts_code(ts_code)
        if not normalized_code:
            raise WebAppError(status_code=422, code="validation_error", message="指数代码不能为空")

        index_basic = session.scalar(select(IndexBasic).where(IndexBasic.ts_code == normalized_code))
        if index_basic is None:
            raise WebAppError(status_code=404, code="not_found", message="指数不存在，不能加入激活池")

        existing = session.scalar(
            select(IndexSeriesActive)
            .where(IndexSeriesActive.resource == normalized_resource)
            .where(IndexSeriesActive.ts_code == normalized_code)
        )
        if existing is not None:
            raise WebAppError(status_code=409, code="conflict", message="该指数已经在激活池中")

        observed_at = datetime.now(timezone.utc)
        today = date.today()
        session.add(
            IndexSeriesActive(
                resource=normalized_resource,
                ts_code=normalized_code,
                first_seen_date=today,
                last_seen_date=today,
                last_checked_at=observed_at,
            )
        )
        session.commit()
        return normalized_resource, normalized_code

    def remove_active_index(
        self,
        session: Session,
        *,
        resource: str,
        ts_code: str,
    ) -> tuple[str, str]:
        normalized_resource = self._normalize_resource(resource)
        normalized_code = self._normalize_ts_code(ts_code)
        if not normalized_code:
            raise WebAppError(status_code=422, code="validation_error", message="指数代码不能为空")

        row = session.scalar(
            select(IndexSeriesActive)
            .where(IndexSeriesActive.resource == normalized_resource)
            .where(IndexSeriesActive.ts_code == normalized_code)
        )
        if row is None:
            raise WebAppError(status_code=404, code="not_found", message="该指数不在激活池中")

        session.delete(row)
        session.commit()
        return normalized_resource, normalized_code

    @staticmethod
    def _normalize_resource(resource: str) -> str:
        return str(resource or "index_daily").strip() or "index_daily"

    @staticmethod
    def _normalize_ts_code(ts_code: str) -> str:
        return str(ts_code or "").strip().upper()
