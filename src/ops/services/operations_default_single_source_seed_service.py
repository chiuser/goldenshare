from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.meta.dataset_resolution_policy import DatasetResolutionPolicy
from src.foundation.models.meta.dataset_source_status import DatasetSourceStatus
from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
from src.ops.models.ops.std_mapping_rule import StdMappingRule
from src.ops.specs import list_dataset_freshness_specs


DISABLED_DEFAULT_DATASET_KEYS: set[str] = set()


@dataclass(slots=True)
class SeedDefaultSingleSourceReport:
    source_key: str
    dataset_total: int
    created_mapping_rules: int
    created_cleansing_rules: int
    created_resolution_policies: int
    created_source_statuses: int
    dry_run: bool


class DefaultSingleSourceSeedService:
    def run(
        self,
        session: Session,
        *,
        source_key: str = "tushare",
        dry_run: bool = True,
    ) -> SeedDefaultSingleSourceReport:
        dataset_keys = self._default_dataset_keys(source_key=source_key)
        created_mapping_rules = 0
        created_cleansing_rules = 0
        created_resolution_policies = 0
        created_source_statuses = 0

        for dataset_key in dataset_keys:
            if not self._has_mapping_rule(session, dataset_key=dataset_key, source_key=source_key):
                created_mapping_rules += 1
                if not dry_run:
                    session.add(
                        StdMappingRule(
                            dataset_key=dataset_key,
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
            if not self._has_cleansing_rule(session, dataset_key=dataset_key, source_key=source_key):
                created_cleansing_rules += 1
                if not dry_run:
                    session.add(
                        StdCleansingRule(
                            dataset_key=dataset_key,
                            source_key=source_key,
                            rule_type="builtin_default",
                            target_fields_json=[],
                            condition_expr=None,
                            action="pass_through",
                            status="active",
                            rule_set_version=1,
                        )
                    )
            if not self._has_resolution_policy(session, dataset_key=dataset_key):
                created_resolution_policies += 1
                if not dry_run:
                    session.add(
                        DatasetResolutionPolicy(
                            dataset_key=dataset_key,
                            mode="primary_fallback",
                            primary_source_key=source_key,
                            fallback_source_keys=[],
                            field_rules_json={},
                            version=1,
                            enabled=True,
                        )
                    )
            if not self._has_source_status(session, dataset_key=dataset_key, source_key=source_key):
                created_source_statuses += 1
                if not dry_run:
                    session.add(
                        DatasetSourceStatus(
                            dataset_key=dataset_key,
                            source_key=source_key,
                            is_active=True,
                            reason="default single-source seeded",
                        )
                    )

        if not dry_run:
            session.commit()

        return SeedDefaultSingleSourceReport(
            source_key=source_key,
            dataset_total=len(dataset_keys),
            created_mapping_rules=created_mapping_rules,
            created_cleansing_rules=created_cleansing_rules,
            created_resolution_policies=created_resolution_policies,
            created_source_statuses=created_source_statuses,
            dry_run=dry_run,
        )

    @staticmethod
    def _default_dataset_keys(*, source_key: str) -> list[str]:
        source_raw_prefix = f"raw_{source_key}."
        return sorted(
            spec.dataset_key
            for spec in list_dataset_freshness_specs()
            if spec.dataset_key not in DISABLED_DEFAULT_DATASET_KEYS
            and spec.raw_table is not None
            and spec.raw_table.startswith(source_raw_prefix)
        )

    @staticmethod
    def _has_mapping_rule(session: Session, *, dataset_key: str, source_key: str) -> bool:
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
    def _has_cleansing_rule(session: Session, *, dataset_key: str, source_key: str) -> bool:
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
    def _has_resolution_policy(session: Session, *, dataset_key: str) -> bool:
        return (
            session.scalar(
                select(DatasetResolutionPolicy.dataset_key).where(DatasetResolutionPolicy.dataset_key == dataset_key)
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
