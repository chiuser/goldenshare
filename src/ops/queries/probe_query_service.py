from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, aliased

from src.app.models.app_user import AppUser
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.probe_run_log import ProbeRunLog
from src.app.exceptions import WebAppError
from src.ops.schemas.probe import (
    ProbeRuleDetailResponse,
    ProbeRuleListItem,
    ProbeRuleListResponse,
    ProbeRunLogItem,
    ProbeRunLogListResponse,
)


class ProbeQueryService:
    def list_probe_rules(
        self,
        session: Session,
        *,
        status: str | None = None,
        dataset_key: str | None = None,
        source_key: str | None = None,
        schedule_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProbeRuleListResponse:
        limit = max(1, min(limit, 200))
        filters = []
        if status:
            filters.append(ProbeRule.status == status)
        if dataset_key:
            filters.append(ProbeRule.dataset_key == dataset_key)
        if source_key:
            filters.append(ProbeRule.source_key == source_key)
        if schedule_id is not None:
            filters.append(ProbeRule.schedule_id == schedule_id)

        count_stmt = select(func.count()).select_from(ProbeRule)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = session.scalar(count_stmt) or 0

        stmt = select(ProbeRule).order_by(desc(ProbeRule.updated_at), desc(ProbeRule.id)).limit(limit).offset(offset)
        if filters:
            stmt = stmt.where(*filters)

        rows = session.scalars(stmt).all()
        return ProbeRuleListResponse(total=total, items=[self._list_item(rule) for rule in rows])

    def get_probe_rule_detail(self, session: Session, probe_rule_id: int) -> ProbeRuleDetailResponse:
        created_by = aliased(AppUser)
        updated_by = aliased(AppUser)
        stmt = (
            select(ProbeRule, created_by.username, updated_by.username)
            .outerjoin(created_by, created_by.id == ProbeRule.created_by_user_id)
            .outerjoin(updated_by, updated_by.id == ProbeRule.updated_by_user_id)
            .where(ProbeRule.id == probe_rule_id)
        )
        row = session.execute(stmt).one_or_none()
        if row is None:
            raise WebAppError(status_code=404, code="not_found", message="Probe rule does not exist")
        rule, created_by_username, updated_by_username = row
        item = self._list_item(rule)
        return ProbeRuleDetailResponse(
            **item.model_dump(),
            created_by_username=created_by_username,
            updated_by_username=updated_by_username,
        )

    def list_probe_run_logs(
        self,
        session: Session,
        *,
        probe_rule_id: int | None = None,
        status: str | None = None,
        dataset_key: str | None = None,
        source_key: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ProbeRunLogListResponse:
        limit = max(1, min(limit, 500))

        filters = []
        if probe_rule_id is not None:
            filters.append(ProbeRunLog.probe_rule_id == probe_rule_id)
        if status:
            filters.append(ProbeRunLog.status == status)
        if dataset_key:
            filters.append(ProbeRule.dataset_key == dataset_key)
        if source_key:
            filters.append(ProbeRule.source_key == source_key)

        count_stmt = select(func.count()).select_from(ProbeRunLog).join(ProbeRule, ProbeRule.id == ProbeRunLog.probe_rule_id)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = session.scalar(count_stmt) or 0

        stmt = (
            select(ProbeRunLog, ProbeRule.name, ProbeRule.dataset_key, ProbeRule.source_key)
            .join(ProbeRule, ProbeRule.id == ProbeRunLog.probe_rule_id)
            .order_by(desc(ProbeRunLog.probed_at), desc(ProbeRunLog.id))
            .limit(limit)
            .offset(offset)
        )
        if filters:
            stmt = stmt.where(*filters)
        rows = session.execute(stmt).all()

        return ProbeRunLogListResponse(
            total=total,
            items=[
                ProbeRunLogItem(
                    id=log.id,
                    probe_rule_id=log.probe_rule_id,
                    probe_rule_name=rule_name,
                    dataset_key=resolved_dataset_key,
                    source_key=resolved_source_key,
                    status=log.status,
                    condition_matched=log.condition_matched,
                    message=log.message,
                    payload_json=dict(log.payload_json or {}),
                    probed_at=log.probed_at,
                    triggered_execution_id=log.triggered_execution_id,
                    duration_ms=log.duration_ms,
                    rule_version=log.rule_version,
                    result_code=log.result_code,
                    result_reason=log.result_reason,
                    correlation_id=log.correlation_id,
                )
                for log, rule_name, resolved_dataset_key, resolved_source_key in rows
            ],
        )

    @staticmethod
    def _list_item(rule: ProbeRule) -> ProbeRuleListItem:
        return ProbeRuleListItem(
            id=rule.id,
            schedule_id=rule.schedule_id,
            name=rule.name,
            dataset_key=rule.dataset_key,
            trigger_mode=rule.trigger_mode,
            workflow_key=rule.workflow_key,
            step_key=rule.step_key,
            rule_version=rule.rule_version,
            source_key=rule.source_key,
            status=rule.status,
            window_start=rule.window_start,
            window_end=rule.window_end,
            probe_interval_seconds=rule.probe_interval_seconds,
            probe_condition_json=dict(rule.probe_condition_json or {}),
            on_success_action_json=dict(rule.on_success_action_json or {}),
            max_triggers_per_day=rule.max_triggers_per_day,
            timezone_name=rule.timezone_name,
            last_probed_at=rule.last_probed_at,
            last_triggered_at=rule.last_triggered_at,
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )
