from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.ops.models.ops.dataset_pipeline_mode import DatasetPipelineMode
from src.ops.specs import DatasetFreshnessSpec, list_dataset_freshness_specs


@dataclass(slots=True)
class SeedDatasetPipelineModeReport:
    dataset_total: int
    created: int
    updated: int
    dry_run: bool


@dataclass(slots=True)
class _ModeDraft:
    dataset_key: str
    mode: str
    source_scope: str
    raw_enabled: bool
    std_enabled: bool
    resolution_enabled: bool
    serving_enabled: bool
    notes: str | None


class DatasetPipelineModeSeedService:
    def run(self, session: Session, *, dry_run: bool = True) -> SeedDatasetPipelineModeReport:
        specs = list_dataset_freshness_specs()
        created = 0
        updated = 0
        for spec in specs:
            draft = self._build_default_mode(spec)
            current = session.get(DatasetPipelineMode, draft.dataset_key)
            if current is None:
                created += 1
                if not dry_run:
                    session.add(
                        DatasetPipelineMode(
                            dataset_key=draft.dataset_key,
                            mode=draft.mode,
                            source_scope=draft.source_scope,
                            raw_enabled=draft.raw_enabled,
                            std_enabled=draft.std_enabled,
                            resolution_enabled=draft.resolution_enabled,
                            serving_enabled=draft.serving_enabled,
                            notes=draft.notes,
                        )
                    )
                continue
            if self._is_same(current, draft):
                continue
            updated += 1
            if not dry_run:
                current.mode = draft.mode
                current.source_scope = draft.source_scope
                current.raw_enabled = draft.raw_enabled
                current.std_enabled = draft.std_enabled
                current.resolution_enabled = draft.resolution_enabled
                current.serving_enabled = draft.serving_enabled
                current.notes = draft.notes

        if not dry_run:
            session.commit()
        return SeedDatasetPipelineModeReport(
            dataset_total=len(specs),
            created=created,
            updated=updated,
            dry_run=dry_run,
        )

    @staticmethod
    def _build_default_mode(spec: DatasetFreshnessSpec) -> _ModeDraft:
        if spec.dataset_key == "stock_basic":
            return _ModeDraft(
                dataset_key=spec.dataset_key,
                mode="multi_source_pipeline",
                source_scope="tushare,biying",
                raw_enabled=True,
                std_enabled=True,
                resolution_enabled=True,
                serving_enabled=True,
                notes="已落地双源标准化+融合发布链路",
            )
        target = spec.target_table
        raw_table = spec.raw_table or ""
        if target.startswith("raw_") or target.startswith("raw."):
            scope = "biying" if raw_table.startswith("raw_biying.") else "tushare"
            return _ModeDraft(
                dataset_key=spec.dataset_key,
                mode="raw_only",
                source_scope=scope,
                raw_enabled=True,
                std_enabled=False,
                resolution_enabled=False,
                serving_enabled=False,
                notes="仅采集原始数据，不进入 serving",
            )
        if target.startswith("core_serving."):
            scope = "biying" if raw_table.startswith("raw_biying.") else "tushare"
            return _ModeDraft(
                dataset_key=spec.dataset_key,
                mode="single_source_direct",
                source_scope=scope,
                raw_enabled=True,
                std_enabled=False,
                resolution_enabled=False,
                serving_enabled=True,
                notes="单源直出 serving（未物化 std）",
            )
        return _ModeDraft(
            dataset_key=spec.dataset_key,
            mode="legacy_core_direct",
            source_scope="tushare",
            raw_enabled=True,
            std_enabled=False,
            resolution_enabled=False,
            serving_enabled=False,
            notes="历史保留路径（core 口径）",
        )

    @staticmethod
    def _is_same(current: DatasetPipelineMode, draft: _ModeDraft) -> bool:
        return (
            current.mode == draft.mode
            and current.source_scope == draft.source_scope
            and bool(current.raw_enabled) == draft.raw_enabled
            and bool(current.std_enabled) == draft.std_enabled
            and bool(current.resolution_enabled) == draft.resolution_enabled
            and bool(current.serving_enabled) == draft.serving_enabled
            and (current.notes or None) == draft.notes
        )
