from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.models.meta.dataset_resolution_policy import DatasetResolutionPolicy
from src.ops.models.ops.dataset_pipeline_mode import DatasetPipelineMode
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
from src.ops.models.ops.std_mapping_rule import StdMappingRule
from src.ops.schemas.dataset_pipeline import DatasetPipelineModeItem, DatasetPipelineModeListResponse
from src.operations.specs import get_dataset_freshness_spec


class DatasetPipelineModeQueryService:
    _STD_TABLE_HINTS = {
        "stock_basic": "core_multi.security_std",
        "equity_indicators": "core_multi.indicator_*_std",
    }
    _SERVING_TABLE_HINTS = {
        "stock_basic": "core_serving.security_serving",
    }

    def list_modes(self, session: Session, *, limit: int = 500, offset: int = 0) -> DatasetPipelineModeListResponse:
        limit = max(1, min(limit, 2000))
        rows = session.scalars(
            select(DatasetStatusSnapshot)
            .order_by(DatasetStatusSnapshot.domain_key.asc(), DatasetStatusSnapshot.display_name.asc())
            .limit(limit)
            .offset(offset)
        ).all()

        if not rows:
            return DatasetPipelineModeListResponse(total=0, items=[])

        dataset_keys = [row.dataset_key for row in rows]
        mode_rows = session.scalars(
            select(DatasetPipelineMode).where(DatasetPipelineMode.dataset_key.in_(dataset_keys))
        ).all()
        mode_by_key = {row.dataset_key: row for row in mode_rows}

        mapping_counts = dict(
            session.execute(
                select(StdMappingRule.dataset_key, func.count())
                .where(
                    StdMappingRule.dataset_key.in_(dataset_keys),
                    StdMappingRule.status == "active",
                )
                .group_by(StdMappingRule.dataset_key)
            ).all()
        )
        cleansing_counts = dict(
            session.execute(
                select(StdCleansingRule.dataset_key, func.count())
                .where(
                    StdCleansingRule.dataset_key.in_(dataset_keys),
                    StdCleansingRule.status == "active",
                )
                .group_by(StdCleansingRule.dataset_key)
            ).all()
        )
        resolution_keys = set(
            session.scalars(
                select(DatasetResolutionPolicy.dataset_key).where(
                    DatasetResolutionPolicy.dataset_key.in_(dataset_keys),
                    DatasetResolutionPolicy.enabled.is_(True),
                )
            ).all()
        )

        items: list[DatasetPipelineModeItem] = []
        for row in rows:
            mode = mode_by_key.get(row.dataset_key)
            resolved_mode = mode.mode if mode is not None else "unknown"
            source_scope = mode.source_scope if mode is not None else "unknown"
            spec = get_dataset_freshness_spec(row.resource_key)
            raw_table = spec.raw_table if spec is not None else None
            items.append(
                DatasetPipelineModeItem(
                    dataset_key=row.dataset_key,
                    display_name=row.display_name,
                    domain_key=row.domain_key,
                    mode=resolved_mode,
                    source_scope=source_scope,
                    layer_plan=self._layer_plan(mode=resolved_mode),
                    raw_table=raw_table,
                    std_table_hint=self._std_table_hint(row.dataset_key, resolved_mode),
                    serving_table=self._serving_table(row.target_table, row.dataset_key, resolved_mode),
                    freshness_status=row.freshness_status,
                    latest_business_date=row.latest_business_date,
                    std_mapping_configured=mapping_counts.get(row.dataset_key, 0) > 0,
                    std_cleansing_configured=cleansing_counts.get(row.dataset_key, 0) > 0,
                    resolution_policy_configured=row.dataset_key in resolution_keys,
                )
            )

        total = session.scalar(select(func.count()).select_from(DatasetStatusSnapshot)) or 0
        return DatasetPipelineModeListResponse(total=int(total), items=items)

    @classmethod
    def _std_table_hint(cls, dataset_key: str, mode: str) -> str | None:
        if mode in {"multi_source_pipeline"}:
            return cls._STD_TABLE_HINTS.get(dataset_key, f"core_multi.{dataset_key}_std")
        return None

    @classmethod
    def _serving_table(cls, target_table: str, dataset_key: str, mode: str) -> str | None:
        if mode in {"raw_only", "legacy_core_direct"}:
            return None
        if target_table.startswith("core_serving."):
            return target_table
        return cls._SERVING_TABLE_HINTS.get(dataset_key)

    @staticmethod
    def _layer_plan(*, mode: str) -> str:
        if mode == "multi_source_pipeline":
            return "raw->std->resolution->serving"
        if mode == "single_source_direct":
            return "raw->serving"
        if mode == "raw_only":
            return "raw-only"
        if mode == "legacy_core_direct":
            return "raw->core(legacy)"
        return "unknown"
