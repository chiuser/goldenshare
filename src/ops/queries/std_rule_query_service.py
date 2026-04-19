from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
from src.ops.models.ops.std_mapping_rule import StdMappingRule
from src.ops.specs import list_dataset_freshness_specs
from src.ops.schemas.std_rule import (
    StdCleansingRuleItem,
    StdCleansingRuleListResponse,
    StdMappingRuleItem,
    StdMappingRuleListResponse,
)


DISABLED_DEFAULT_DATASET_KEYS: set[str] = set()


class StdRuleQueryService:
    def list_mapping_rules(
        self,
        session: Session,
        *,
        dataset_key: str | None = None,
        source_key: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> StdMappingRuleListResponse:
        limit = max(1, min(limit, 500))
        filters = []
        if dataset_key:
            filters.append(StdMappingRule.dataset_key == dataset_key)
        if source_key:
            filters.append(StdMappingRule.source_key == source_key)
        if status:
            filters.append(StdMappingRule.status == status)
        count_stmt = select(func.count()).select_from(StdMappingRule)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = session.scalar(count_stmt) or 0

        stmt = select(StdMappingRule).order_by(desc(StdMappingRule.updated_at), desc(StdMappingRule.id)).limit(limit).offset(offset)
        if filters:
            stmt = stmt.where(*filters)
        rows = session.scalars(stmt).all()
        if not rows:
            fallback = self._default_mapping_rules(
                dataset_key=dataset_key,
                source_key=source_key,
                status=status,
                limit=limit,
                offset=offset,
            )
            if fallback is not None:
                return fallback
        return StdMappingRuleListResponse(
            total=total,
            items=[
                StdMappingRuleItem(
                    id=row.id,
                    dataset_key=row.dataset_key,
                    source_key=row.source_key,
                    src_field=row.src_field,
                    std_field=row.std_field,
                    src_type=row.src_type,
                    std_type=row.std_type,
                    transform_fn=row.transform_fn,
                    lineage_preserved=row.lineage_preserved,
                    status=row.status,
                    rule_set_version=row.rule_set_version,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ],
        )

    def list_cleansing_rules(
        self,
        session: Session,
        *,
        dataset_key: str | None = None,
        source_key: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> StdCleansingRuleListResponse:
        limit = max(1, min(limit, 500))
        filters = []
        if dataset_key:
            filters.append(StdCleansingRule.dataset_key == dataset_key)
        if source_key:
            filters.append(StdCleansingRule.source_key == source_key)
        if status:
            filters.append(StdCleansingRule.status == status)
        count_stmt = select(func.count()).select_from(StdCleansingRule)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = session.scalar(count_stmt) or 0

        stmt = select(StdCleansingRule).order_by(desc(StdCleansingRule.updated_at), desc(StdCleansingRule.id)).limit(limit).offset(offset)
        if filters:
            stmt = stmt.where(*filters)
        rows = session.scalars(stmt).all()
        if not rows:
            fallback = self._default_cleansing_rules(
                dataset_key=dataset_key,
                source_key=source_key,
                status=status,
                limit=limit,
                offset=offset,
            )
            if fallback is not None:
                return fallback
        return StdCleansingRuleListResponse(
            total=total,
            items=[
                StdCleansingRuleItem(
                    id=row.id,
                    dataset_key=row.dataset_key,
                    source_key=row.source_key,
                    rule_type=row.rule_type,
                    target_fields_json=list(row.target_fields_json or []),
                    condition_expr=row.condition_expr,
                    action=row.action,
                    status=row.status,
                    rule_set_version=row.rule_set_version,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ],
        )

    @staticmethod
    def get_mapping_rule(session: Session, rule_id: int) -> StdMappingRule:
        rule = session.scalar(select(StdMappingRule).where(StdMappingRule.id == rule_id))
        if rule is None:
            raise WebAppError(status_code=404, code="not_found", message="Std mapping rule does not exist")
        return rule

    @staticmethod
    def get_cleansing_rule(session: Session, rule_id: int) -> StdCleansingRule:
        rule = session.scalar(select(StdCleansingRule).where(StdCleansingRule.id == rule_id))
        if rule is None:
            raise WebAppError(status_code=404, code="not_found", message="Std cleansing rule does not exist")
        return rule

    @staticmethod
    def _default_dataset_keys(dataset_key: str | None) -> list[str]:
        all_keys = sorted(
            spec.dataset_key
            for spec in list_dataset_freshness_specs()
            if spec.dataset_key not in DISABLED_DEFAULT_DATASET_KEYS
        )
        if dataset_key:
            return [dataset_key] if dataset_key in all_keys else []
        return all_keys

    def _default_mapping_rules(
        self,
        *,
        dataset_key: str | None,
        source_key: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> StdMappingRuleListResponse | None:
        if source_key not in (None, "tushare"):
            return StdMappingRuleListResponse(items=[], total=0)
        if status not in (None, "active"):
            return StdMappingRuleListResponse(items=[], total=0)
        keys = self._default_dataset_keys(dataset_key)
        now = datetime.now(timezone.utc)
        items = [
            StdMappingRuleItem(
                id=-(100000 + idx),
                dataset_key=key,
                source_key="tushare",
                src_field="*",
                std_field="*",
                src_type=None,
                std_type=None,
                transform_fn="identity_pass_through",
                lineage_preserved=True,
                status="active",
                rule_set_version=1,
                created_at=now,
                updated_at=now,
            )
            for idx, key in enumerate(keys, start=1)
        ]
        total = len(items)
        return StdMappingRuleListResponse(items=items[offset : offset + limit], total=total)

    def _default_cleansing_rules(
        self,
        *,
        dataset_key: str | None,
        source_key: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> StdCleansingRuleListResponse | None:
        if source_key not in (None, "tushare"):
            return StdCleansingRuleListResponse(items=[], total=0)
        if status not in (None, "active"):
            return StdCleansingRuleListResponse(items=[], total=0)
        keys = self._default_dataset_keys(dataset_key)
        now = datetime.now(timezone.utc)
        items = [
            StdCleansingRuleItem(
                id=-(200000 + idx),
                dataset_key=key,
                source_key="tushare",
                rule_type="builtin_default",
                target_fields_json=[],
                condition_expr=None,
                action="pass_through",
                status="active",
                rule_set_version=1,
                created_at=now,
                updated_at=now,
            )
            for idx, key in enumerate(keys, start=1)
        ]
        total = len(items)
        return StdCleansingRuleListResponse(items=items[offset : offset + limit], total=total)
