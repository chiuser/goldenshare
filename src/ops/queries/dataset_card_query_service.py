from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import list_dataset_definitions
from src.foundation.datasets.source_registry import get_source_display_name
from src.ops.catalog.dataset_catalog_view_resolver import DatasetCatalogViewResolver
from src.ops.layer_snapshot_source_scope import (
    matches_layer_snapshot_source_filter,
    normalize_layer_snapshot_source_key,
)
from src.foundation.models.meta.dataset_resolution_policy import DatasetResolutionPolicy
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
from src.ops.models.ops.std_mapping_rule import StdMappingRule
from src.ops.dataset_definition_projection import (
    LAYER_STAGE_ORDER,
    build_dataset_layer_projection,
    delivery_mode_label,
    delivery_mode_tone,
)
from src.ops.layer_stage_labels import get_layer_stage_display_name
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService
from src.ops.queries.layer_snapshot_query_service import LayerSnapshotQueryService
from src.ops.schemas.dataset_card import (
    DatasetCardGroup,
    DatasetCardItem,
    DatasetCardListResponse,
    DatasetCardSourceStatus,
    DatasetCardStageStatus,
)
from src.ops.schemas.freshness import DatasetFreshnessItem
from src.ops.schemas.layer_snapshot import LayerSnapshotLatestItem


CardStatus = str


@dataclass(frozen=True, slots=True)
class DatasetCardFact:
    dataset_key: str
    logical_key: str
    logical_priority: int
    display_name: str
    domain_key: str
    domain_display_name: str
    cadence: str
    cadence_display_name: str
    source_keys: tuple[str, ...]
    delivery_mode: str
    layer_plan: str
    raw_table: str
    std_table_hint: str | None
    serving_table: str | None
    stage_keys: tuple[str, ...]
    primary_action_key: str | None
    std_mapping_configured: bool
    std_cleansing_configured: bool
    resolution_policy_configured: bool


class DatasetCardQueryService:
    def list_cards(self, session: Session, *, source_key: str | None = None, limit: int = 2000) -> DatasetCardListResponse:
        normalized_source = source_key.strip().lower() if source_key else None
        if normalized_source == "":
            normalized_source = None
        limit = max(1, min(limit, 2000))

        definitions = list_dataset_definitions()
        config_flags = self._config_flags(session, [definition.dataset_key for definition in definitions])
        facts = [
            self._fact_from_definition(definition, config_flags=config_flags.get(definition.dataset_key, (False, False, False)))
            for definition in definitions
        ]
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

        selected_facts = self._select_facts(facts, source_key=normalized_source)
        cards = self._build_cards(
            selected_facts,
            freshness_by_dataset=freshness_by_dataset,
            snapshot_by_dataset=snapshot_by_dataset,
            layer_items=layer_items,
            probe_counts=probe_counts,
            source_key=normalized_source,
        )
        cards.sort(key=lambda item: (item.group_order, item.item_order, item.display_name, item.card_key))
        sliced = cards[:limit]
        return DatasetCardListResponse(total=len(cards), groups=self._group_cards(sliced))

    def _select_facts(
        self,
        facts: list[DatasetCardFact],
        *,
        source_key: str | None,
    ) -> list[DatasetCardFact]:
        if source_key is None:
            return facts

        candidates = [item for item in facts if source_key in item.source_keys]
        deduped: dict[str, DatasetCardFact] = {}
        for item in candidates:
            key = item.logical_key
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = item
                continue
            if (item.logical_priority, item.dataset_key) < (existing.logical_priority, existing.dataset_key):
                deduped[key] = item
        return list(deduped.values())

    def _build_cards(
        self,
        facts: list[DatasetCardFact],
        *,
        freshness_by_dataset: dict[str, DatasetFreshnessItem],
        snapshot_by_dataset: dict[str, DatasetStatusSnapshot],
        layer_items: list[LayerSnapshotLatestItem],
        probe_counts: dict[str, tuple[int, int]],
        source_key: str | None,
    ) -> list[DatasetCardItem]:
        grouped: dict[str, list[DatasetCardFact]] = {}
        for item in facts:
            grouped.setdefault(item.logical_key, []).append(item)

        card_key_by_dataset = {item.dataset_key: item.logical_key for item in facts}
        layer_by_card: dict[str, list[LayerSnapshotLatestItem]] = {}
        for item in layer_items:
            card_key = card_key_by_dataset.get(item.dataset_key)
            if card_key is not None:
                layer_by_card.setdefault(card_key, []).append(item)

        cards: list[DatasetCardItem] = []
        for card_key, members in grouped.items():
            primary = self._primary_member(members)
            member_freshness = [freshness_by_dataset[item.dataset_key] for item in members if item.dataset_key in freshness_by_dataset]
            member_snapshots = [snapshot_by_dataset[item.dataset_key] for item in members if item.dataset_key in snapshot_by_dataset]
            primary_freshness = freshness_by_dataset.get(primary.dataset_key)
            primary_snapshot = snapshot_by_dataset.get(primary.dataset_key)
            layers = layer_by_card.get(card_key, [])
            if source_key is not None:
                layers = [
                    item
                    for item in layers
                    if item.stage != "raw"
                    or matches_layer_snapshot_source_filter(
                        row_source_key=item.source_key,
                        requested_source_key=source_key,
                    )
                ]

            raw_sources = self._raw_sources(
                members,
                layers,
                source_key=source_key,
            )
            stage_statuses = self._stage_statuses(
                primary,
                layers,
                raw_sources=raw_sources,
            )
            active_status = (primary_freshness.active_task_run_status if primary_freshness else None)
            has_active = (active_status or "").lower() in {"queued", "running", "canceling"}
            status = "running" if has_active else self._card_status(members, member_freshness, layers, source_key=source_key)
            probe_total, probe_active = self._combined_probe_counts([item.dataset_key for item in members], probe_counts)
            delivery_mode = self._delivery_mode_for_card(members)
            catalog_item = DatasetCatalogViewResolver().resolve_item(primary.dataset_key)

            cards.append(
                DatasetCardItem(
                    card_key=card_key,
                    dataset_key=card_key,
                    detail_dataset_key=primary.dataset_key,
                    resource_key=primary_freshness.resource_key if primary_freshness else primary.dataset_key,
                    display_name=primary.display_name,
                    group_key=catalog_item.group_key,
                    group_label=catalog_item.group_label,
                    group_order=catalog_item.group_order,
                    item_order=catalog_item.item_order,
                    domain_key=primary.domain_key,
                    domain_display_name=primary.domain_display_name,
                    status=status,
                    freshness_status=self._worse_raw_status([item.freshness_status for item in member_freshness]),
                    delivery_mode=delivery_mode,
                    delivery_mode_label=delivery_mode_label(delivery_mode),
                    delivery_mode_tone=delivery_mode_tone(delivery_mode),
                    layer_plan=primary.layer_plan,
                    cadence=primary.cadence,
                    cadence_display_name=primary.cadence_display_name,
                    raw_table=primary.raw_table,
                    raw_table_label=self._raw_table_label(primary, source_key=source_key),
                    target_table=primary_freshness.target_table if primary_freshness else primary.serving_table,
                    latest_business_date=self._latest_date(
                        [item.latest_business_date for item in member_freshness]
                        + [item.latest_business_date for item in member_snapshots]
                    ),
                    earliest_business_date=self._earliest_date(
                        [item.earliest_business_date for item in member_freshness]
                        + [item.earliest_business_date for item in member_snapshots]
                    ),
                    latest_observed_at=self._latest_datetime(
                        [item.latest_observed_at for item in member_freshness]
                        + [item.latest_observed_at for item in member_snapshots]
                    ),
                    earliest_observed_at=self._earliest_datetime(
                        [item.earliest_observed_at for item in member_freshness]
                        + [item.earliest_observed_at for item in member_snapshots]
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
                    primary_action_key=(primary_freshness.primary_action_key if primary_freshness else None) or (primary_snapshot.primary_action_key if primary_snapshot else None) or primary.primary_action_key,
                    active_task_run_status=active_status,
                    active_task_run_started_at=primary_freshness.active_task_run_started_at if primary_freshness else None,
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
        primary: DatasetCardFact,
        layers: list[LayerSnapshotLatestItem],
        *,
        raw_sources: list[DatasetCardSourceStatus],
    ) -> list[DatasetCardStageStatus]:
        stage_latest: dict[str, LayerSnapshotLatestItem] = {}
        for item in layers:
            previous = stage_latest.get(item.stage)
            if previous is None or item.calculated_at > previous.calculated_at:
                stage_latest[item.stage] = item

        stages = self._expected_stages(primary.stage_keys, layers)
        result: list[DatasetCardStageStatus] = []
        for stage in stages:
            latest = stage_latest.get(stage)
            result.append(
                DatasetCardStageStatus(
                    stage=stage,
                    stage_label=_require_stage_display_name(stage),
                    table_name=self._stage_table_name(stage, primary, raw_sources),
                    source_key=normalize_layer_snapshot_source_key(latest.source_key) if latest else None,
                    source_display_name=_optional_source_display_name(latest.source_key if latest else None),
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
        members: list[DatasetCardFact],
        layers: list[LayerSnapshotLatestItem],
        *,
        source_key: str | None,
    ) -> list[DatasetCardSourceStatus]:
        source_tables: dict[str, str | None] = {}
        for item in members:
            for source in item.source_keys:
                if source_key is not None and source != source_key:
                    continue
                table = self._raw_table_label(item, source_key=source)
                source_tables.setdefault(source, table)

        raw_layers = [item for item in layers if item.stage == "raw"]
        for item in raw_layers:
            source = normalize_layer_snapshot_source_key(item.source_key) or "combined"
            if source_key is not None and not matches_layer_snapshot_source_filter(
                row_source_key=source,
                requested_source_key=source_key,
            ):
                continue
            source_tables.setdefault(source, None)

        result: list[DatasetCardSourceStatus] = []
        for source, table_name in sorted(source_tables.items()):
            latest = self._latest_layer_for_source(raw_layers, source)
            result.append(
                DatasetCardSourceStatus(
                    source_key=source,
                    source_display_name=_require_source_display_name(source),
                    table_name=table_name,
                    status=self._normalize_status(latest.status if latest else None),
                    calculated_at=latest.calculated_at if latest else None,
                )
            )
        if not result:
            table = self._raw_table_label(members[0], source_key=source_key)
            result.append(
                DatasetCardSourceStatus(
                    source_key=source_key or "combined",
                    source_display_name=_require_source_display_name(source_key or "combined"),
                    table_name=table,
                    status="unknown",
                    calculated_at=None,
                )
            )
        return result

    @staticmethod
    def _latest_layer_for_source(raw_layers: list[LayerSnapshotLatestItem], source: str) -> LayerSnapshotLatestItem | None:
        candidates = [
            item
            for item in raw_layers
            if (normalize_layer_snapshot_source_key(item.source_key) or "combined") == source
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.calculated_at)

    def _card_status(
        self,
        members: list[DatasetCardFact],
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
                if item.stage == "raw"
                and matches_layer_snapshot_source_filter(
                    row_source_key=item.source_key,
                    requested_source_key=source_key,
                )
            ]
        if raw_statuses:
            return self._normalize_status(self._worse_raw_status(raw_statuses))
        return self._normalize_status(
            self._worse_raw_status([item.freshness_status for item in freshness_items])
        )

    def _group_cards(self, cards: list[DatasetCardItem]) -> list[DatasetCardGroup]:
        grouped: dict[tuple[int, str, str], list[DatasetCardItem]] = {}
        for item in cards:
            grouped.setdefault((item.group_order, item.group_key, item.group_label), []).append(item)
        return [
            DatasetCardGroup(group_key=group_key, group_label=group_label, group_order=group_order, items=items)
            for (group_order, group_key, group_label), items in sorted(grouped.items(), key=lambda entry: (entry[0][0], entry[0][2]))
        ]

    @staticmethod
    def _primary_member(members: list[DatasetCardFact]) -> DatasetCardFact:
        sorted_members = sorted(
            members,
            key=lambda item: (item.logical_priority, item.dataset_key),
        )
        return sorted_members[0]

    @staticmethod
    def _delivery_mode_for_card(members: list[DatasetCardFact]) -> str:
        modes = {item.delivery_mode for item in members}
        if "multi_source_fusion" in modes:
            return "multi_source_fusion"
        return members[0].delivery_mode

    @staticmethod
    def _expected_stages(stage_keys: tuple[str, ...], layers: list[LayerSnapshotLatestItem]) -> list[str]:
        base = list(stage_keys)
        extra = [
            stage
            for stage in LAYER_STAGE_ORDER
            if stage not in base and any(item.stage == stage for item in layers)
        ]
        return [*base, *extra]

    def _stage_table_name(
        self,
        stage: str,
        primary: DatasetCardFact,
        raw_sources: list[DatasetCardSourceStatus],
    ) -> str | None:
        if stage == "raw":
            return raw_sources[0].table_name if raw_sources else primary.raw_table
        if stage == "std":
            return primary.std_table_hint
        if stage == "serving":
            return primary.serving_table
        return None

    def _raw_table_label(self, item: DatasetCardFact, *, source_key: str | None) -> str | None:
        if item.raw_table is None:
            return None
        if source_key is None:
            return item.raw_table
        if source_key in item.source_keys:
            return item.raw_table
        return None

    def _fact_from_definition(
        self,
        definition: DatasetDefinition,
        *,
        config_flags: tuple[bool, bool, bool],
    ) -> DatasetCardFact:
        projection = build_dataset_layer_projection(definition)
        std_mapping_configured, std_cleansing_configured, resolution_policy_configured = config_flags
        return DatasetCardFact(
            dataset_key=definition.dataset_key,
            logical_key=definition.logical_key,
            logical_priority=definition.logical_priority,
            display_name=definition.display_name,
            domain_key=definition.domain.domain_key,
            domain_display_name=definition.domain.domain_display_name,
            cadence=definition.domain.cadence,
            cadence_display_name=definition.domain.cadence_display_name,
            source_keys=projection.source_keys,
            delivery_mode=projection.delivery_mode,
            layer_plan=projection.layer_plan,
            raw_table=projection.raw_table,
            std_table_hint=projection.std_table_hint,
            serving_table=projection.serving_table,
            stage_keys=projection.stage_keys,
            primary_action_key=self._primary_action_key(definition),
            std_mapping_configured=std_mapping_configured,
            std_cleansing_configured=std_cleansing_configured,
            resolution_policy_configured=resolution_policy_configured,
        )

    @staticmethod
    def _primary_action_key(definition: DatasetDefinition) -> str | None:
        action = definition.capabilities.get_action("maintain")
        if action is None or not action.manual_enabled:
            return None
        return definition.action_key("maintain")

    @staticmethod
    def _normalize_status(status: str | None) -> str:
        key = (status or "").lower()
        if key in {"running", "queued", "canceling"}:
            return "running"
        if key == "failed":
            return "failed"
        if key == "stale":
            return "stale"
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
    def _earliest_datetime(values: list[datetime | None]) -> datetime | None:
        candidates = [value for value in values if value is not None]
        return min(candidates) if candidates else None

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

    @staticmethod
    def _config_flags(session: Session, dataset_keys: list[str]) -> dict[str, tuple[bool, bool, bool]]:
        mapping_keys = set(
            session.scalars(
                select(StdMappingRule.dataset_key).where(
                    StdMappingRule.dataset_key.in_(dataset_keys),
                    StdMappingRule.status == "active",
                )
            ).all()
        )
        cleansing_keys = set(
            session.scalars(
                select(StdCleansingRule.dataset_key).where(
                    StdCleansingRule.dataset_key.in_(dataset_keys),
                    StdCleansingRule.status == "active",
                )
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
        return {
            dataset_key: (
                dataset_key in mapping_keys,
                dataset_key in cleansing_keys,
                dataset_key in resolution_keys,
            )
            for dataset_key in dataset_keys
        }


def _optional_source_display_name(source_key: str | None) -> str | None:
    if not source_key:
        return None
    return _require_source_display_name(source_key)


def _require_source_display_name(source_key: str | None) -> str:
    display_name = get_source_display_name(normalize_layer_snapshot_source_key(source_key))
    if display_name is None:
        raise WebAppError(status_code=422, code="validation_error", message="数据源卡片来源缺少显示名称")
    return display_name


def _require_stage_display_name(stage: str | None) -> str:
    display_name = get_layer_stage_display_name(stage)
    if display_name is None:
        raise WebAppError(status_code=422, code="validation_error", message="数据源卡片层级缺少显示名称")
    return display_name
