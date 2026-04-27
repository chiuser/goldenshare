from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.foundation.datasets.source_registry import get_source_display_name
from src.ops.dataset_labels import get_dataset_display_name
from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
from src.ops.models.ops.std_mapping_rule import StdMappingRule
from src.ops.schemas.std_rule import (
    StdCleansingRuleItem,
    StdCleansingRuleListResponse,
    StdMappingRuleItem,
    StdMappingRuleListResponse,
)


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
        return StdMappingRuleListResponse(
            total=total,
            items=[
                StdMappingRuleItem(
                    id=row.id,
                    dataset_key=row.dataset_key,
                    dataset_display_name=_require_dataset_display_name(row.dataset_key),
                    source_key=row.source_key,
                    source_display_name=_require_source_display_name(row.source_key),
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
        return StdCleansingRuleListResponse(
            total=total,
            items=[
                StdCleansingRuleItem(
                    id=row.id,
                    dataset_key=row.dataset_key,
                    dataset_display_name=_require_dataset_display_name(row.dataset_key),
                    source_key=row.source_key,
                    source_display_name=_require_source_display_name(row.source_key),
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


def _require_dataset_display_name(dataset_key: str | None) -> str:
    display_name = get_dataset_display_name(dataset_key)
    if display_name is None:
        raise WebAppError(status_code=422, code="validation_error", message="Std rule dataset display name is unavailable")
    return display_name


def _require_source_display_name(source_key: str | None) -> str:
    display_name = get_source_display_name(source_key)
    if display_name is None:
        raise WebAppError(status_code=422, code="validation_error", message="Std rule source display name is unavailable")
    return display_name
