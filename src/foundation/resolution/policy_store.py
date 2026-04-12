from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.meta.dataset_resolution_policy import DatasetResolutionPolicy
from src.foundation.models.meta.dataset_source_status import DatasetSourceStatus
from src.foundation.resolution.types import ResolutionPolicy


class ResolutionPolicyStore:
    def get_enabled_policy(self, session: Session, dataset_key: str) -> ResolutionPolicy | None:
        row = session.scalar(
            select(DatasetResolutionPolicy).where(
                DatasetResolutionPolicy.dataset_key == dataset_key,
                DatasetResolutionPolicy.enabled.is_(True),
            )
        )
        if row is None:
            return None
        return ResolutionPolicy(
            dataset_key=row.dataset_key,
            mode=row.mode,  # type: ignore[arg-type]
            primary_source_key=row.primary_source_key,
            fallback_source_keys=tuple(row.fallback_source_keys or ()),
            field_rules=dict(row.field_rules_json or {}),
            version=int(row.version),
            enabled=bool(row.enabled),
        )

    def get_active_sources(self, session: Session, dataset_key: str) -> set[str]:
        rows = list(
            session.scalars(
                select(DatasetSourceStatus).where(
                    DatasetSourceStatus.dataset_key == dataset_key,
                    DatasetSourceStatus.is_active.is_(True),
                )
            )
        )
        return {row.source_key for row in rows}
