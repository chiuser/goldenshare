from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.queries.dataset_pipeline_mode_query_service import DatasetPipelineModeQueryService
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService
from src.ops.queries.layer_snapshot_query_service import LayerSnapshotQueryService
from src.ops.schemas.dataset_card import (
    DatasetCardGroup,
    DatasetCardItem,
    DatasetCardListResponse,
    DatasetCardSourceStatus,
    DatasetCardStageStatus,
)
from src.ops.schemas.dataset_pipeline import DatasetPipelineModeItem
from src.ops.schemas.freshness import DatasetFreshnessItem
from src.ops.schemas.layer_snapshot import LayerSnapshotLatestItem


CardStatus = str


class DatasetCardQueryService:
    _LIGHT_TABLE_HINTS = {
        "daily": "core_serving_light.equity_daily_bar_light",
    }

    def list_cards(self, session: Session, *, source_key: str | None = None, limit: int = 2000) -> DatasetCardListResponse:
        normalized_source = source_key.strip().lower() if source_key else None
        if normalized_source == "":
            normalized_source = None
        limit = max(1, min(limit, 2000))

        mode_items = DatasetPipelineModeQueryService().list_modes(session, limit=2000).items
        freshness = OpsFreshnessQueryService().build_freshness(session)
        freshness_by_dataset = {
            item.dataset_key: item
            for group in freshness.groups
            for item in group.items
        }
        snapshot_by_dataset = {
            item.dataset_key: item
            for item in session.scalars(select(DatasetStatusSnapshot)).all()
        }
        layer_items = LayerSnapshotQueryService().list_latest(session, limit=5000).items
        probe_counts = self._probe_counts(session)

        selected_modes = self._select_modes(mode_items, source_key=normalized_source)
        cards = self._build_cards(
            selected_modes,
            freshness_by_dataset=freshness_by_dataset,
            snapshot_by_dataset=snapshot_by_dataset,
            layer_items=layer_items,
            probe_counts=probe_counts,
            source_key=normalized_source,
        )
        cards.sort(key=lambda item: (item.domain_display_name, item.display_name, item.card_key))
        sliced = cards[:limit]
        return DatasetCardListResponse(total=len(cards), groups=self._group_cards(sliced))

    def _select_modes(
        self,
        mode_items: list[DatasetPipelineModeItem],
        *,
        source_key: str | None,
    ) -> list[DatasetPipelineModeItem]:
        if source_key is None:
            return mode_items

        candidates = [item for item in mode_items if self._belongs_to_source(item, source_key)]
        deduped: dict[str, DatasetPipelineModeItem] = {}
        for item in candidates:
            key = self._canonical_dataset_key(item.dataset_key)
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = item
                continue
            current_score = self._source_preference(item, source_key)
            existing_score = self._source_preference(existing, source_key)
            if current_score > existing_score:
                deduped[key] = item
                continue
            if current_score == existing_score and item.dataset_key < existing.dataset_key:
                deduped[key] = item
        return list(deduped.values())

    def _build_cards(
        self,
        mode_items: list[DatasetPipelineModeItem],
        *,
        freshness_by_dataset: dict[str, DatasetFreshnessItem],
        snapshot_by_dataset: dict[str, DatasetStatusSnapshot],
        layer_items: list[LayerSnapshotLatestItem],
        probe_counts: dict[str, tuple[int, int]],
        source_key: str | None,
    ) -> list[DatasetCardItem]:
        grouped: dict[str, list[DatasetPipelineModeItem]] = {}
        for item in mode_items:
            key = self._canonical_dataset_key(item.dataset_key)
            grouped.setdefault(key, []).append(item)

        layer_by_canonical: dict[str, list[LayerSnapshotLatestItem]] = {}
        for item in layer_items:
            canonical = self._canonical_dataset_key(item.dataset_key)
            layer_by_canonical.setdefault(canonical, []).append(item)

        cards: list[DatasetCardItem] = []
        for canonical_key, members in grouped.items():
            primary = self._primary_member(members)
            member_freshness = [freshness_by_dataset[item.dataset_key] for item in members if item.dataset_key in freshness_by_dataset]
            member_snapshots = [snapshot_by_dataset[item.dataset_key] for item in members if item.dataset_key in snapshot_by_dataset]
            primary_freshness = freshness_by_dataset.get(primary.dataset_key)
            primary_snapshot = snapshot_by_dataset.get(primary.dataset_key)
            layers = layer_by_canonical.get(canonical_key, [])
            if source_key is not None:
                layers = [
                    item
                    for item in layers
                    if item.stage != "raw" or item.source_key in {source_key, "__all__"}
                ]

            raw_sources = self._raw_sources(
                canonical_key,
                members,
                layers,
                source_key=source_key,
            )
            stage_statuses = self._stage_statuses(
                canonical_key,
                primary,
                layers,
                raw_sources=raw_sources,
            )
            active_status = (primary_freshness.active_execution_status if primary_freshness else None)
            has_active = (active_status or "").lower() in {"queued", "running", "canceling"}
            status = "running" if has_active else self._card_status(members, member_freshness, layers, source_key=source_key)
            probe_total, probe_active = self._combined_probe_counts([item.dataset_key for item in members], probe_counts)

            cards.append(
                DatasetCardItem(
                    card_key=canonical_key,
                    dataset_key=canonical_key,
                    detail_dataset_key=primary.dataset_key,
                    resource_key=primary_freshness.resource_key if primary_freshness else primary.dataset_key,
                    display_name=primary.display_name,
                    domain_key=primary.domain_key,
                    domain_display_name=primary.domain_display_name,
                    status=status,
                    freshness_status=self._worse_raw_status([*(item.freshness_status for item in members), *(item.freshness_status for item in member_freshness)]),
                    mode=self._mode_for_card(members),
                    mode_label=self._mode_label(self._mode_for_card(members)),
                    mode_tone=self._mode_tone(self._mode_for_card(members)),
                    layer_plan=primary.layer_plan,
                    cadence=primary_freshness.cadence if primary_freshness else "",
                    raw_table=primary.raw_table,
                    raw_table_label=self._raw_table_label(primary, source_key=source_key),
                    target_table=primary_freshness.target_table if primary_freshness else primary.serving_table,
                    latest_business_date=self._latest_date(
                        [item.latest_business_date for item in members]
                        + [item.latest_business_date for item in member_freshness]
                        + [item.latest_business_date for item in member_snapshots]
                    ),
                    earliest_business_date=self._earliest_date(
                        [item.earliest_business_date for item in member_freshness]
                        + [item.earliest_business_date for item in member_snapshots]
                    ),
                    last_sync_date=self._latest_date([item.last_sync_date for item in member_freshness] + [item.last_sync_date for item in member_snapshots]),
                    latest_success_at=self._latest_datetime([item.latest_success_at for item in member_freshness] + [item.latest_success_at for item in member_snapshots]),
                    expected_business_date=self._latest_date([item.expected_business_date for item in member_freshness] + [item.expected_business_date for item in member_snapshots]),
                    lag_days=max(
                        [item.lag_days for item in member_freshness if item.lag_days is not None]
                        + [item.lag_days for item in member_snapshots if item.lag_days is not None],
                        default=None,
                    ),
                    freshness_note=(primary_freshness.freshness_note if primary_freshness else None) or (primary_snapshot.freshness_note if primary_snapshot else None),
                    primary_action_key=(primary_freshness.primary_action_key if primary_freshness else None) or (primary_snapshot.primary_action_key if primary_snapshot else None),
                    active_execution_status=active_status,
                    active_execution_started_at=primary_freshness.active_execution_started_at if primary_freshness else None,
                    auto_schedule_status=primary_freshness.auto_schedule_status if primary_freshness else "none",
                    auto_schedule_total=sum(item.auto_schedule_total for item in member_freshness),
                    auto_schedule_active=sum(item.auto_schedule_active for item in member_freshness),
                    auto_schedule_next_run_at=self._latest_datetime([item.auto_schedule_next_run_at for item in member_freshness]),
                    probe_total=probe_total,
                    probe_active=probe_active,
                    std_mapping_configured=any(item.std_mapping_configured for item in members),
                    std_cleansing_configured=any(item.std_cleansing_configured for item in members),
                    resolution_policy_configured=any(item.resolution_policy_configured for item in members),
                    status_updated_at=self._latest_datetime([item.calculated_at for item in layers]),
                    stage_statuses=stage_statuses,
                    raw_sources=raw_sources,
                )
            )
        return cards

    def _stage_statuses(
        self,
        canonical_key: str,
        primary: DatasetPipelineModeItem,
        layers: list[LayerSnapshotLatestItem],
        *,
        raw_sources: list[DatasetCardSourceStatus],
    ) -> list[DatasetCardStageStatus]:
        stage_latest: dict[str, LayerSnapshotLatestItem] = {}
        for item in layers:
            previous = stage_latest.get(item.stage)
            if previous is None or item.calculated_at > previous.calculated_at:
                stage_latest[item.stage] = item

        stages = self._expected_stages(primary.mode, canonical_key, layers)
        result: list[DatasetCardStageStatus] = []
        for stage in stages:
            latest = stage_latest.get(stage)
            result.append(
                DatasetCardStageStatus(
                    stage=stage,
                    stage_label=self._stage_label(stage),
                    table_name=self._stage_table_name(stage, canonical_key, primary, raw_sources),
                    source_key=latest.source_key if latest else None,
                    status=self._normalize_status(latest.status if latest else None),
                    rows_in=latest.rows_in if latest else None,
                    rows_out=latest.rows_out if latest else None,
                    error_count=latest.error_count if latest else None,
                    lag_seconds=latest.lag_seconds if latest else None,
                    message=latest.message if latest else None,
                    calculated_at=latest.calculated_at if latest else None,
                    last_success_at=latest.last_success_at if latest else None,
                    last_failure_at=latest.last_failure_at if latest else None,
                )
            )
        return result

    def _raw_sources(
        self,
        canonical_key: str,
        members: list[DatasetPipelineModeItem],
        layers: list[LayerSnapshotLatestItem],
        *,
        source_key: str | None,
    ) -> list[DatasetCardSourceStatus]:
        source_tables: dict[str, str | None] = {}
        for item in members:
            for source in self._source_values(item):
                if source_key is not None and source != source_key:
                    continue
                table = self._raw_table_label(item, source_key=source)
                source_tables.setdefault(source, table)

        raw_layers = [item for item in layers if item.stage == "raw"]
        for item in raw_layers:
            source = item.source_key or "__all__"
            if source_key is not None and source not in {source_key, "__all__"}:
                continue
            source_tables.setdefault(source, None)

        result: list[DatasetCardSourceStatus] = []
        for source, table_name in sorted(source_tables.items()):
            latest = self._latest_layer_for_source(raw_layers, source)
            result.append(
                DatasetCardSourceStatus(
                    source_key=source,
                    table_name=table_name,
                    status=self._normalize_status(latest.status if latest else None),
                    calculated_at=latest.calculated_at if latest else None,
                )
            )
        if not result:
            table = self._raw_table_label(members[0], source_key=source_key)
            result.append(
                DatasetCardSourceStatus(
                    source_key=source_key or "__all__",
                    table_name=table,
                    status="unknown",
                    calculated_at=None,
                )
            )
        return result

    @staticmethod
    def _latest_layer_for_source(raw_layers: list[LayerSnapshotLatestItem], source: str) -> LayerSnapshotLatestItem | None:
        candidates = [item for item in raw_layers if (item.source_key or "__all__") == source]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.calculated_at)

    def _card_status(
        self,
        members: list[DatasetPipelineModeItem],
        freshness_items: list[DatasetFreshnessItem],
        layers: list[LayerSnapshotLatestItem],
        *,
        source_key: str | None,
    ) -> CardStatus:
        raw_statuses = []
        if source_key is not None:
            raw_statuses = [
                item.status
                for item in layers
                if item.stage == "raw" and item.source_key in {source_key, "__all__"}
            ]
        if raw_statuses:
            return self._normalize_status(self._worse_raw_status(raw_statuses))
        return self._normalize_status(
            self._worse_raw_status([*(item.freshness_status for item in members), *(item.freshness_status for item in freshness_items)])
        )

    @staticmethod
    def _group_cards(cards: list[DatasetCardItem]) -> list[DatasetCardGroup]:
        grouped: dict[tuple[str, str], list[DatasetCardItem]] = {}
        for item in cards:
            grouped.setdefault((item.domain_key, item.domain_display_name), []).append(item)
        return [
            DatasetCardGroup(domain_key=domain_key, domain_display_name=domain_display_name, items=items)
            for (domain_key, domain_display_name), items in sorted(grouped.items(), key=lambda entry: entry[0][1])
        ]

    @staticmethod
    def _primary_member(members: list[DatasetPipelineModeItem]) -> DatasetPipelineModeItem:
        sorted_members = sorted(
            members,
            key=lambda item: (
                item.dataset_key.lower().startswith("biying_") or item.dataset_key.lower().startswith("tushare_"),
                item.dataset_key,
            ),
        )
        return sorted_members[0]

    @staticmethod
    def _canonical_dataset_key(raw_key: str) -> str:
        lower = raw_key.lower()
        if lower.startswith("biying_"):
            return raw_key[len("biying_") :]
        if lower.startswith("tushare_"):
            return raw_key[len("tushare_") :]
        return raw_key

    @staticmethod
    def _source_values(item: DatasetPipelineModeItem) -> list[str]:
        scope_values = [part.strip().lower() for part in item.source_scope.split(",") if part.strip()]
        if scope_values and "unknown" not in scope_values:
            return sorted(set(scope_values))
        dataset_key = item.dataset_key.lower()
        raw_table = (item.raw_table or "").lower()
        if dataset_key.startswith("biying_") or raw_table.startswith("raw_biying."):
            return ["biying"]
        if dataset_key.startswith("tushare_") or raw_table.startswith("raw_tushare."):
            return ["tushare"]
        return []

    def _belongs_to_source(self, item: DatasetPipelineModeItem, source_key: str) -> bool:
        return source_key in self._source_values(item)

    @staticmethod
    def _source_preference(item: DatasetPipelineModeItem, source_key: str) -> int:
        dataset_key = item.dataset_key.lower()
        raw_table = (item.raw_table or "").lower()
        source_scope = item.source_scope.lower()
        if source_key == "biying":
            if dataset_key.startswith("biying_"):
                return 300
            if raw_table.startswith("raw_biying."):
                return 200
            if "biying" in source_scope:
                return 100
            return 0
        if dataset_key.startswith("biying_"):
            return 0
        if raw_table.startswith("raw_tushare.") and not dataset_key.startswith("tushare_"):
            return 300
        if dataset_key.startswith("tushare_"):
            return 200
        if "tushare" in source_scope:
            return 100
        return 0

    @staticmethod
    def _mode_for_card(members: list[DatasetPipelineModeItem]) -> str:
        modes = {item.mode for item in members}
        if "multi_source_pipeline" in modes:
            return "multi_source_pipeline"
        return members[0].mode

    @staticmethod
    def _mode_label(mode: str) -> str:
        if mode == "single_source_direct":
            return "单源直出"
        if mode == "multi_source_pipeline":
            return "多源流水线"
        if mode == "raw_only":
            return "仅原始层"
        if mode == "legacy_core_direct":
            return "直接维护"
        return "未定义"

    @staticmethod
    def _mode_tone(mode: str) -> str:
        if mode == "single_source_direct":
            return "success"
        if mode == "multi_source_pipeline":
            return "info"
        if mode == "raw_only":
            return "neutral"
        if mode == "legacy_core_direct":
            return "warning"
        return "neutral"

    @staticmethod
    def _expected_stages(mode: str, canonical_key: str, layers: list[LayerSnapshotLatestItem]) -> list[str]:
        if mode == "multi_source_pipeline":
            base = ["raw", "std", "resolution", "serving"]
        elif mode == "single_source_direct":
            base = ["raw", "serving"]
        elif mode in {"raw_only", "legacy_core_direct"}:
            base = ["raw"]
        else:
            base = ["raw", "serving"]
        if canonical_key == "daily" or any(item.stage == "light" for item in layers):
            return [*base, "light"]
        return base

    @staticmethod
    def _stage_label(stage: str) -> str:
        if stage == "raw":
            return "原始层"
        if stage == "std":
            return "标准层"
        if stage == "resolution":
            return "融合层"
        if stage == "light":
            return "轻量层"
        if stage == "serving":
            return "服务层"
        return stage

    def _stage_table_name(
        self,
        stage: str,
        canonical_key: str,
        primary: DatasetPipelineModeItem,
        raw_sources: list[DatasetCardSourceStatus],
    ) -> str | None:
        if stage == "raw":
            return raw_sources[0].table_name if raw_sources else primary.raw_table
        if stage == "std":
            return primary.std_table_hint
        if stage == "serving":
            return primary.serving_table
        if stage == "light":
            return self._LIGHT_TABLE_HINTS.get(canonical_key)
        return None

    def _raw_table_label(self, item: DatasetPipelineModeItem, *, source_key: str | None) -> str | None:
        if item.raw_table is None:
            return None
        if source_key is None:
            return item.raw_table
        raw_table = item.raw_table.lower()
        if source_key == "biying" and raw_table.startswith("raw_biying."):
            return item.raw_table
        if source_key == "tushare" and raw_table.startswith("raw_tushare."):
            return item.raw_table
        values = self._source_values(item)
        if len(values) == 1 and values[0] == source_key:
            return item.raw_table
        return None

    @staticmethod
    def _normalize_status(status: str | None) -> str:
        key = (status or "").lower()
        if key in {"running", "queued", "canceling"}:
            return "running"
        if key in {"failed", "stale"}:
            return "failed"
        if key in {"warning", "lagging"}:
            return "warning"
        if key in {"healthy", "fresh", "success"}:
            return "healthy"
        if key == "disabled":
            return "disabled"
        return "unknown"

    @staticmethod
    def _worse_raw_status(statuses: list[str | None]) -> str:
        rank = {
            "failed": 5,
            "stale": 4,
            "warning": 3,
            "lagging": 3,
            "unknown": 2,
            "disabled": 1,
            "healthy": 0,
            "fresh": 0,
            "success": 0,
        }
        if not statuses:
            return "unknown"
        return max(statuses, key=lambda item: rank.get((item or "unknown").lower(), 2)) or "unknown"

    @staticmethod
    def _latest_date(values):  # type: ignore[no-untyped-def]
        candidates = [value for value in values if value is not None]
        return max(candidates) if candidates else None

    @staticmethod
    def _earliest_date(values):  # type: ignore[no-untyped-def]
        candidates = [value for value in values if value is not None]
        return min(candidates) if candidates else None

    @staticmethod
    def _latest_datetime(values: list[datetime | None]) -> datetime | None:
        candidates = [value for value in values if value is not None]
        return max(candidates) if candidates else None

    @staticmethod
    def _combined_probe_counts(dataset_keys: list[str], probe_counts: dict[str, tuple[int, int]]) -> tuple[int, int]:
        total = 0
        active = 0
        for key in dataset_keys:
            item_total, item_active = probe_counts.get(key, (0, 0))
            total += item_total
            active += item_active
        return total, active

    @staticmethod
    def _probe_counts(session: Session) -> dict[str, tuple[int, int]]:
        rows = session.execute(
            select(
                ProbeRule.dataset_key,
                func.count(ProbeRule.id),
                func.sum(case((ProbeRule.status == "active", 1), else_=0)),
            ).group_by(ProbeRule.dataset_key)
        ).all()
        return {str(dataset_key): (int(total or 0), int(active or 0)) for dataset_key, total, active in rows}
