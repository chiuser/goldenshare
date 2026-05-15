from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import list_dataset_definitions
from src.ops.catalog.dataset_catalog_view_resolver import DatasetCatalogViewResolver
from src.foundation.models.meta.dataset_resolution_policy import DatasetResolutionPolicy
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
from src.ops.models.ops.std_mapping_rule import StdMappingRule
from src.ops.dataset_definition_projection import (
    delivery_mode_label,
    delivery_mode_tone,
)
from src.ops.catalog.biz_table_catalog import BIZ_TABLE_SOURCE_KEY
from src.ops.queries.biz_table_card_query_service import BizTableCardQueryService
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService
from src.ops.schemas.dataset_card import (
    DatasetCardGroup,
    DatasetCardItem,
    DatasetCardListResponse,
)
from src.ops.schemas.freshness import DatasetFreshnessItem


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
    raw_table: str | None
    serving_table: str | None
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
        if normalized_source == BIZ_TABLE_SOURCE_KEY:
            return BizTableCardQueryService().list_cards(session, limit=limit)

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
        probe_counts = self._probe_counts(session)

        selected_facts = self._select_facts(facts, source_key=normalized_source)
        cards = self._build_cards(
            selected_facts,
            freshness_by_dataset=freshness_by_dataset,
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
        probe_counts: dict[str, tuple[int, int]],
        source_key: str | None,
    ) -> list[DatasetCardItem]:
        grouped: dict[str, list[DatasetCardFact]] = {}
        for item in facts:
            grouped.setdefault(item.logical_key, []).append(item)

        cards: list[DatasetCardItem] = []
        for card_key, members in grouped.items():
            primary = self._primary_member(members)
            member_freshness = [freshness_by_dataset[item.dataset_key] for item in members if item.dataset_key in freshness_by_dataset]
            primary_freshness = freshness_by_dataset.get(primary.dataset_key)
            active_status = (primary_freshness.active_task_run_status if primary_freshness else None)
            has_active = (active_status or "").lower() in {"queued", "running", "canceling"}
            status = "running" if has_active else self._card_status(member_freshness)
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
                    latest_business_date=self._latest_date([item.latest_business_date for item in member_freshness]),
                    earliest_business_date=self._earliest_date([item.earliest_business_date for item in member_freshness]),
                    latest_observed_at=self._latest_datetime([item.latest_observed_at for item in member_freshness]),
                    earliest_observed_at=self._earliest_datetime([item.earliest_observed_at for item in member_freshness]),
                    last_sync_date=self._latest_date([item.last_sync_date for item in member_freshness]),
                    latest_success_at=self._latest_datetime([item.latest_success_at for item in member_freshness]),
                    expected_business_date=self._latest_date([item.expected_business_date for item in member_freshness]),
                    lag_days=max(
                        [item.lag_days for item in member_freshness if item.lag_days is not None],
                        default=None,
                    ),
                    freshness_note=primary_freshness.freshness_note if primary_freshness else None,
                    primary_action_key=(primary_freshness.primary_action_key if primary_freshness else None) or primary.primary_action_key,
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
                )
            )
        return cards

    def _card_status(self, freshness_items: list[DatasetFreshnessItem]) -> CardStatus:
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
            source_keys=definition.source.source_keys,
            delivery_mode=definition.storage.delivery_mode,
            layer_plan=definition.storage.layer_plan,
            raw_table=definition.storage.raw_table,
            serving_table=definition.storage.serving_table,
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
