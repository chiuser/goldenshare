from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import list_dataset_definitions
from src.foundation.models.meta.dataset_resolution_policy import DatasetResolutionPolicy
from src.foundation.models.meta.dataset_source_status import DatasetSourceStatus
from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
from src.ops.models.ops.std_mapping_rule import StdMappingRule


@dataclass(slots=True)
class SeedMoneyflowMultiSourceReport:
    dataset_key: str
    dry_run: bool
    created_mapping_rules: int
    created_cleansing_rules: int
    created_source_statuses: int
    created_resolution_policy: int
    updated_resolution_policy: int


@dataclass(frozen=True, slots=True)
class MultiSourceSeedPlan:
    dataset_key: str
    primary_source: str
    fallback_sources: tuple[str, ...]

    @property
    def source_keys(self) -> tuple[str, ...]:
        return (self.primary_source, *self.fallback_sources)


class MoneyflowMultiSourceSeedService:
    def run(self, session: Session, *, dry_run: bool = True) -> SeedMoneyflowMultiSourceReport:
        seed_plan = self._build_seed_plan()
        created_mapping_rules = 0
        created_cleansing_rules = 0
        created_source_statuses = 0
        created_resolution_policy = 0
        updated_resolution_policy = 0

        for source_key in seed_plan.source_keys:
            if not self._has_active_mapping_rule(session, dataset_key=seed_plan.dataset_key, source_key=source_key):
                created_mapping_rules += 1
                if not dry_run:
                    session.add(
                        StdMappingRule(
                            dataset_key=seed_plan.dataset_key,
                            source_key=source_key,
                            src_field="*",
                            std_field="*",
                            src_type=None,
                            std_type=None,
                            transform_fn="identity_pass_through",
                            lineage_preserved=True,
                            status="active",
                            rule_set_version=1,
                        )
                    )
            if not self._has_active_cleansing_rule(session, dataset_key=seed_plan.dataset_key, source_key=source_key):
                created_cleansing_rules += 1
                if not dry_run:
                    session.add(
                        StdCleansingRule(
                            dataset_key=seed_plan.dataset_key,
                            source_key=source_key,
                            rule_type="builtin_default",
                            target_fields_json=[],
                            condition_expr=None,
                            action="pass_through",
                            status="active",
                            rule_set_version=1,
                        )
                    )
            if not self._has_source_status(session, dataset_key=seed_plan.dataset_key, source_key=source_key):
                created_source_statuses += 1
                if not dry_run:
                    session.add(
                        DatasetSourceStatus(
                            dataset_key=seed_plan.dataset_key,
                            source_key=source_key,
                            is_active=True,
                            reason="moneyflow multi-source skeleton seeded",
                        )
                    )

        policy = session.get(DatasetResolutionPolicy, seed_plan.dataset_key)
        if policy is None:
            created_resolution_policy += 1
            if not dry_run:
                session.add(
                    DatasetResolutionPolicy(
                        dataset_key=seed_plan.dataset_key,
                        mode="primary_fallback",
                        primary_source_key=seed_plan.primary_source,
                        fallback_source_keys=list(seed_plan.fallback_sources),
                        field_rules_json={},
                        version=1,
                        enabled=True,
                    )
                )
        else:
            policy_changed = False
            if policy.mode != "primary_fallback":
                policy_changed = True
            if policy.primary_source_key != seed_plan.primary_source:
                policy_changed = True
            if tuple(policy.fallback_source_keys or ()) != seed_plan.fallback_sources:
                policy_changed = True
            if not bool(policy.enabled):
                policy_changed = True
            if policy_changed:
                updated_resolution_policy += 1
                if not dry_run:
                    policy.mode = "primary_fallback"
                    policy.primary_source_key = seed_plan.primary_source
                    policy.fallback_source_keys = list(seed_plan.fallback_sources)
                    policy.enabled = True
                    policy.version = max(1, int(policy.version or 1)) + 1

        if not dry_run:
            session.commit()

        return SeedMoneyflowMultiSourceReport(
            dataset_key=seed_plan.dataset_key,
            dry_run=dry_run,
            created_mapping_rules=created_mapping_rules,
            created_cleansing_rules=created_cleansing_rules,
            created_source_statuses=created_source_statuses,
            created_resolution_policy=created_resolution_policy,
            updated_resolution_policy=updated_resolution_policy,
        )

    @staticmethod
    def _build_seed_plan() -> MultiSourceSeedPlan:
        definitions = [
            definition
            for definition in list_dataset_definitions()
            if definition.logical_key == "moneyflow" and definition.storage.delivery_mode == "multi_source_fusion"
        ]
        if not definitions:
            raise ValueError("资金流多来源数据集分组缺失")
        canonical = min(definitions, key=lambda item: (item.logical_priority, item.dataset_key))
        source_keys = MoneyflowMultiSourceSeedService._source_keys_by_definition_priority(definitions)
        primary_source = canonical.source.source_key_default
        fallback_sources = tuple(source_key for source_key in source_keys if source_key != primary_source)
        if not fallback_sources:
            raise ValueError("资金流多来源数据集组缺少备选来源")
        return MultiSourceSeedPlan(
            dataset_key=canonical.dataset_key,
            primary_source=primary_source,
            fallback_sources=fallback_sources,
        )

    @staticmethod
    def _source_keys_by_definition_priority(definitions: list[DatasetDefinition]) -> tuple[str, ...]:
        source_keys: list[str] = []
        for definition in sorted(definitions, key=lambda item: (item.logical_priority, item.dataset_key)):
            for source_key in definition.source.source_keys:
                if source_key not in source_keys:
                    source_keys.append(source_key)
        return tuple(source_keys)

    @staticmethod
    def _has_active_mapping_rule(session: Session, *, dataset_key: str, source_key: str) -> bool:
        return (
            session.scalar(
                select(StdMappingRule.id).where(
                    StdMappingRule.dataset_key == dataset_key,
                    StdMappingRule.source_key == source_key,
                    StdMappingRule.status == "active",
                )
            )
            is not None
        )

    @staticmethod
    def _has_active_cleansing_rule(session: Session, *, dataset_key: str, source_key: str) -> bool:
        return (
            session.scalar(
                select(StdCleansingRule.id).where(
                    StdCleansingRule.dataset_key == dataset_key,
                    StdCleansingRule.source_key == source_key,
                    StdCleansingRule.status == "active",
                )
            )
            is not None
        )

    @staticmethod
    def _has_source_status(session: Session, *, dataset_key: str, source_key: str) -> bool:
        return (
            session.scalar(
                select(DatasetSourceStatus.dataset_key).where(
                    DatasetSourceStatus.dataset_key == dataset_key,
                    DatasetSourceStatus.source_key == source_key,
                )
            )
            is not None
        )
