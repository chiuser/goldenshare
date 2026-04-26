from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

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


class MoneyflowMultiSourceSeedService:
    _dataset_key = "moneyflow"
    _primary_source = "tushare"
    _fallback_sources = ("biying",)
    _all_sources = (_primary_source, *_fallback_sources)

    def run(self, session: Session, *, dry_run: bool = True) -> SeedMoneyflowMultiSourceReport:
        created_mapping_rules = 0
        created_cleansing_rules = 0
        created_source_statuses = 0
        created_resolution_policy = 0
        updated_resolution_policy = 0

        for source_key in self._all_sources:
            if not self._has_active_mapping_rule(session, source_key=source_key):
                created_mapping_rules += 1
                if not dry_run:
                    session.add(
                        StdMappingRule(
                            dataset_key=self._dataset_key,
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
            if not self._has_active_cleansing_rule(session, source_key=source_key):
                created_cleansing_rules += 1
                if not dry_run:
                    session.add(
                        StdCleansingRule(
                            dataset_key=self._dataset_key,
                            source_key=source_key,
                            rule_type="builtin_default",
                            target_fields_json=[],
                            condition_expr=None,
                            action="pass_through",
                            status="active",
                            rule_set_version=1,
                        )
                    )
            if not self._has_source_status(session, source_key=source_key):
                created_source_statuses += 1
                if not dry_run:
                    session.add(
                        DatasetSourceStatus(
                            dataset_key=self._dataset_key,
                            source_key=source_key,
                            is_active=True,
                            reason="moneyflow multi-source skeleton seeded",
                        )
                    )

        policy = session.get(DatasetResolutionPolicy, self._dataset_key)
        if policy is None:
            created_resolution_policy += 1
            if not dry_run:
                session.add(
                    DatasetResolutionPolicy(
                        dataset_key=self._dataset_key,
                        mode="primary_fallback",
                        primary_source_key=self._primary_source,
                        fallback_source_keys=list(self._fallback_sources),
                        field_rules_json={},
                        version=1,
                        enabled=True,
                    )
                )
        else:
            policy_changed = False
            if policy.mode != "primary_fallback":
                policy_changed = True
            if policy.primary_source_key != self._primary_source:
                policy_changed = True
            if tuple(policy.fallback_source_keys or ()) != self._fallback_sources:
                policy_changed = True
            if not bool(policy.enabled):
                policy_changed = True
            if policy_changed:
                updated_resolution_policy += 1
                if not dry_run:
                    policy.mode = "primary_fallback"
                    policy.primary_source_key = self._primary_source
                    policy.fallback_source_keys = list(self._fallback_sources)
                    policy.enabled = True
                    policy.version = max(1, int(policy.version or 1)) + 1

        if not dry_run:
            session.commit()

        return SeedMoneyflowMultiSourceReport(
            dataset_key=self._dataset_key,
            dry_run=dry_run,
            created_mapping_rules=created_mapping_rules,
            created_cleansing_rules=created_cleansing_rules,
            created_source_statuses=created_source_statuses,
            created_resolution_policy=created_resolution_policy,
            updated_resolution_policy=updated_resolution_policy,
        )

    def _has_active_mapping_rule(self, session: Session, *, source_key: str) -> bool:
        return (
            session.scalar(
                select(StdMappingRule.id).where(
                    StdMappingRule.dataset_key == self._dataset_key,
                    StdMappingRule.source_key == source_key,
                    StdMappingRule.status == "active",
                )
            )
            is not None
        )

    def _has_active_cleansing_rule(self, session: Session, *, source_key: str) -> bool:
        return (
            session.scalar(
                select(StdCleansingRule.id).where(
                    StdCleansingRule.dataset_key == self._dataset_key,
                    StdCleansingRule.source_key == source_key,
                    StdCleansingRule.status == "active",
                )
            )
            is not None
        )

    def _has_source_status(self, session: Session, *, source_key: str) -> bool:
        return (
            session.scalar(
                select(DatasetSourceStatus.dataset_key).where(
                    DatasetSourceStatus.dataset_key == self._dataset_key,
                    DatasetSourceStatus.source_key == source_key,
                )
            )
            is not None
        )
