from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.models.meta.dataset_resolution_policy import DatasetResolutionPolicy
from src.ops.models.ops.dataset_pipeline_mode import DatasetPipelineMode
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
from src.ops.models.ops.std_mapping_rule import StdMappingRule
from src.ops.schemas.dataset_pipeline import DatasetPipelineModeItem, DatasetPipelineModeListResponse
from src.operations.specs import DatasetFreshnessSpec, get_dataset_freshness_spec, list_dataset_freshness_specs


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
        specs = list_dataset_freshness_specs()
        spec_by_key = {spec.dataset_key: spec for spec in specs}
        dataset_keys = [spec.dataset_key for spec in specs]

        snapshot_rows = session.scalars(
            select(DatasetStatusSnapshot).where(DatasetStatusSnapshot.dataset_key.in_(dataset_keys))
        ).all()
        snapshot_by_key = {row.dataset_key: row for row in snapshot_rows}

        legacy_rows = session.scalars(
            select(DatasetStatusSnapshot).where(~DatasetStatusSnapshot.dataset_key.in_(dataset_keys))
        ).all()
        all_dataset_keys = [*dataset_keys, *[row.dataset_key for row in legacy_rows]]
        mode_rows = session.scalars(
            select(DatasetPipelineMode).where(DatasetPipelineMode.dataset_key.in_(all_dataset_keys))
        ).all()
        mode_by_key = {row.dataset_key: row for row in mode_rows}

        mapping_counts = dict(
            session.execute(
                select(StdMappingRule.dataset_key, func.count())
                .where(
                    StdMappingRule.dataset_key.in_(all_dataset_keys),
                    StdMappingRule.status == "active",
                )
                .group_by(StdMappingRule.dataset_key)
            ).all()
        )
        cleansing_counts = dict(
            session.execute(
                select(StdCleansingRule.dataset_key, func.count())
                .where(
                    StdCleansingRule.dataset_key.in_(all_dataset_keys),
                    StdCleansingRule.status == "active",
                )
                .group_by(StdCleansingRule.dataset_key)
            ).all()
        )
        resolution_keys = set(
            session.scalars(
                select(DatasetResolutionPolicy.dataset_key).where(
                    DatasetResolutionPolicy.dataset_key.in_(all_dataset_keys),
                    DatasetResolutionPolicy.enabled.is_(True),
                )
            ).all()
        )

        items: list[DatasetPipelineModeItem] = []
        for dataset_key in dataset_keys:
            spec = spec_by_key[dataset_key]
            row = snapshot_by_key.get(dataset_key)
            mode = mode_by_key.get(dataset_key)
            if mode is None and spec is not None:
                mode = self._inferred_mode_from_spec(dataset_key, spec)
            resolved_mode = mode.mode if mode is not None else "unknown"
            source_scope = mode.source_scope if mode is not None else "unknown"
            raw_table = spec.raw_table
            target_table = spec.target_table
            items.append(
                DatasetPipelineModeItem(
                    dataset_key=dataset_key,
                    display_name=spec.display_name,
                    domain_key=spec.domain_key,
                    domain_display_name=spec.domain_display_name,
                    mode=resolved_mode,
                    source_scope=source_scope,
                    layer_plan=self._layer_plan(mode=resolved_mode),
                    raw_table=raw_table,
                    std_table_hint=self._std_table_hint(dataset_key, resolved_mode),
                    serving_table=self._serving_table(target_table, dataset_key, resolved_mode),
                    freshness_status=row.freshness_status if row is not None else "unknown",
                    latest_business_date=row.latest_business_date if row is not None else None,
                    std_mapping_configured=mapping_counts.get(dataset_key, 0) > 0,
                    std_cleansing_configured=cleansing_counts.get(dataset_key, 0) > 0,
                    resolution_policy_configured=dataset_key in resolution_keys,
                )
            )

        for row in legacy_rows:
            if row.dataset_key in spec_by_key:
                continue
            spec = get_dataset_freshness_spec(row.resource_key)
            mode = mode_by_key.get(row.dataset_key)
            if mode is None and spec is not None:
                mode = self._inferred_mode_from_spec(row.dataset_key, spec)
            resolved_mode = mode.mode if mode is not None else "unknown"
            source_scope = mode.source_scope if mode is not None else "unknown"
            raw_table = spec.raw_table if spec is not None else None
            target_table = spec.target_table if spec is not None else row.target_table
            items.append(
                DatasetPipelineModeItem(
                    dataset_key=row.dataset_key,
                    display_name=row.display_name,
                    domain_key=row.domain_key,
                    domain_display_name=row.domain_display_name,
                    mode=resolved_mode,
                    source_scope=source_scope,
                    layer_plan=self._layer_plan(mode=resolved_mode),
                    raw_table=raw_table,
                    std_table_hint=self._std_table_hint(row.dataset_key, resolved_mode),
                    serving_table=self._serving_table(target_table, row.dataset_key, resolved_mode),
                    freshness_status=row.freshness_status,
                    latest_business_date=row.latest_business_date,
                    std_mapping_configured=mapping_counts.get(row.dataset_key, 0) > 0,
                    std_cleansing_configured=cleansing_counts.get(row.dataset_key, 0) > 0,
                    resolution_policy_configured=row.dataset_key in resolution_keys,
                )
            )

        items.sort(key=lambda it: (it.domain_display_name, it.display_name))
        total = len(items)
        sliced = items[offset : offset + limit]
        return DatasetPipelineModeListResponse(total=int(total), items=sliced)

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

    @staticmethod
    def _inferred_mode_from_spec(dataset_key: str, spec: DatasetFreshnessSpec) -> DatasetPipelineMode:
        target = spec.target_table
        raw_table = spec.raw_table or ""
        if dataset_key == "stock_basic":
            return DatasetPipelineMode(
                dataset_key=dataset_key,
                mode="multi_source_pipeline",
                source_scope="tushare,biying",
                raw_enabled=True,
                std_enabled=True,
                resolution_enabled=True,
                serving_enabled=True,
                notes="按规格推断：双源标准化+融合发布链路",
            )
        if target.startswith("raw_") or target.startswith("raw."):
            scope = "biying" if raw_table.startswith("raw_biying.") else "tushare"
            return DatasetPipelineMode(
                dataset_key=dataset_key,
                mode="raw_only",
                source_scope=scope,
                raw_enabled=True,
                std_enabled=False,
                resolution_enabled=False,
                serving_enabled=False,
                notes="按规格推断：仅采集原始数据",
            )
        if target.startswith("core_serving."):
            scope = "biying" if raw_table.startswith("raw_biying.") else "tushare"
            return DatasetPipelineMode(
                dataset_key=dataset_key,
                mode="single_source_direct",
                source_scope=scope,
                raw_enabled=True,
                std_enabled=False,
                resolution_enabled=False,
                serving_enabled=True,
                notes="按规格推断：单源直出 serving",
            )
        return DatasetPipelineMode(
            dataset_key=dataset_key,
            mode="legacy_core_direct",
            source_scope="tushare",
            raw_enabled=True,
            std_enabled=False,
            resolution_enabled=False,
            serving_enabled=False,
            notes="按规格推断：历史保留路径（core 口径）",
        )
