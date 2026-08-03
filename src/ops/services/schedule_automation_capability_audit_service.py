from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.services.schedule_automation_capability_resolver import (
    ScheduleAutomationCapabilityResolver,
    ValidatedAutomationIntent,
)
from src.ops.services.schedule_probe_binding_service import ProbeRuleTemplate, ScheduleProbeBindingService


DEFAULT_AUDIT_BATCH_SIZE = 100
DEFAULT_AUDIT_MAX_RECORDS = 100


@dataclass(frozen=True, slots=True)
class ScheduleAuditRecord:
    id: int
    target_type: str
    target_key: str
    status: str
    schedule_type: str
    trigger_mode: str
    timezone: str
    calendar_policy: str | None
    probe_config_json: dict
    params_json: dict


@dataclass(frozen=True, slots=True)
class ProbeRuleAuditRecord:
    id: int
    schedule_id: int | None
    dataset_key: str
    source_key: str | None
    status: str
    window_start: str | None
    window_end: str | None
    probe_interval_seconds: int
    probe_condition_json: dict
    on_success_action_json: dict
    max_triggers_per_day: int
    timezone_name: str
    trigger_mode: str
    workflow_key: str | None
    step_key: str | None


@dataclass(frozen=True, slots=True)
class ScheduleAutomationCapabilityAuditIssue:
    code: str
    message: str
    entity_type: str
    entity_id: int | None
    schedule_id: int | None = None
    probe_rule_id: int | None = None
    fields: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["fields"] = list(self.fields)
        return payload


@dataclass(frozen=True, slots=True)
class ScheduleAutomationCapabilityAuditReport:
    schedule_count: int
    probe_rule_count: int
    schedule_pages: int
    probe_rule_pages: int
    batch_size: int
    max_records: int
    expected_schedule_count: int | None
    expected_probe_rule_count: int | None
    issues: tuple[ScheduleAutomationCapabilityAuditIssue, ...]

    @property
    def passed(self) -> bool:
        return not self.issues

    def to_json(self) -> str:
        return json.dumps(
            {
                "passed": self.passed,
                "schedule_count": self.schedule_count,
                "probe_rule_count": self.probe_rule_count,
                "schedule_pages": self.schedule_pages,
                "probe_rule_pages": self.probe_rule_pages,
                "batch_size": self.batch_size,
                "max_records": self.max_records,
                "expected_schedule_count": self.expected_schedule_count,
                "expected_probe_rule_count": self.expected_probe_rule_count,
                "issues": [item.to_dict() for item in self.issues],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )


class ScheduleAutomationCapabilityAuditService:
    """Read-only contract audit for persisted automatic schedules and probe rules."""

    def __init__(self) -> None:
        self.capability_resolver = ScheduleAutomationCapabilityResolver()

    def audit(
        self,
        session: Session,
        *,
        batch_size: int = DEFAULT_AUDIT_BATCH_SIZE,
        max_records: int = DEFAULT_AUDIT_MAX_RECORDS,
        expected_schedule_count: int | None = None,
        expected_probe_rule_count: int | None = None,
    ) -> ScheduleAutomationCapabilityAuditReport:
        self._validate_bounds(batch_size=batch_size, max_records=max_records)
        schedules, schedule_pages, schedules_truncated = self._load_schedules(
            session,
            batch_size=batch_size,
            max_records=max_records,
        )
        probe_rules, probe_rule_pages, probe_rules_truncated = self._load_probe_rules(
            session,
            batch_size=batch_size,
            max_records=max_records,
        )
        issues: list[ScheduleAutomationCapabilityAuditIssue] = []
        if schedules_truncated:
            issues.append(self._scan_limit_issue(entity_type="schedule", max_records=max_records))
        if probe_rules_truncated:
            issues.append(self._scan_limit_issue(entity_type="probe_rule", max_records=max_records))
        if expected_schedule_count is not None and len(schedules) != expected_schedule_count:
            issues.append(
                ScheduleAutomationCapabilityAuditIssue(
                    code="schedule.count_mismatch",
                    message=f"自动任务数量不符合预期：实际 {len(schedules)}，预期 {expected_schedule_count}",
                    entity_type="audit",
                    entity_id=None,
                )
            )
        if expected_probe_rule_count is not None and len(probe_rules) != expected_probe_rule_count:
            issues.append(
                ScheduleAutomationCapabilityAuditIssue(
                    code="probe_rule.count_mismatch",
                    message=f"探测规则数量不符合预期：实际 {len(probe_rules)}，预期 {expected_probe_rule_count}",
                    entity_type="audit",
                    entity_id=None,
                )
            )

        rules_by_schedule: dict[int, list[ProbeRuleAuditRecord]] = defaultdict(list)
        schedules_by_id = {item.id: item for item in schedules}
        for rule in probe_rules:
            if rule.schedule_id is None or rule.schedule_id not in schedules_by_id:
                issues.append(
                    ScheduleAutomationCapabilityAuditIssue(
                        code="probe_rule.orphan",
                        message="探测规则没有可审计的父自动任务",
                        entity_type="probe_rule",
                        entity_id=rule.id,
                        probe_rule_id=rule.id,
                    )
                )
                self._audit_forbidden_rule_target(rule, issues=issues)
                continue
            rules_by_schedule[rule.schedule_id].append(rule)

        for schedule in schedules:
            rules = rules_by_schedule.get(schedule.id, [])
            intent = self._audit_schedule(schedule, issues=issues)
            template = ScheduleProbeBindingService.build_template(intent) if intent is not None else None
            self._audit_schedule_rules(schedule=schedule, rules=rules, template=template, issues=issues)

        return ScheduleAutomationCapabilityAuditReport(
            schedule_count=len(schedules),
            probe_rule_count=len(probe_rules),
            schedule_pages=schedule_pages,
            probe_rule_pages=probe_rule_pages,
            batch_size=batch_size,
            max_records=max_records,
            expected_schedule_count=expected_schedule_count,
            expected_probe_rule_count=expected_probe_rule_count,
            issues=tuple(issues),
        )

    @staticmethod
    def _validate_bounds(*, batch_size: int, max_records: int) -> None:
        if not 1 <= batch_size <= 1_000:
            raise ValueError("batch_size 必须在 1 到 1000 之间")
        if not 1 <= max_records <= 1_000:
            raise ValueError("max_records 必须在 1 到 1000 之间")

    @staticmethod
    def _scan_limit_issue(*, entity_type: str, max_records: int) -> ScheduleAutomationCapabilityAuditIssue:
        return ScheduleAutomationCapabilityAuditIssue(
            code="audit.scan_limit_exceeded",
            message=f"{entity_type} 超出本次只读审计上限 {max_records}，未继续扫描",
            entity_type="audit",
            entity_id=None,
        )

    def _audit_schedule(
        self,
        schedule: ScheduleAuditRecord,
        *,
        issues: list[ScheduleAutomationCapabilityAuditIssue],
    ) -> ValidatedAutomationIntent | None:
        if schedule.status != "active":
            return None
        try:
            intent = self.capability_resolver.validate_schedule(schedule)  # type: ignore[arg-type]
        except WebAppError as exc:
            issues.append(
                ScheduleAutomationCapabilityAuditIssue(
                    code=exc.code,
                    message=exc.message,
                    entity_type="schedule",
                    entity_id=schedule.id,
                    schedule_id=schedule.id,
                )
            )
            return None

        allowed_schedule_types = {
            schedule_type
            for option in intent.capability.trigger_options
            if option.mode == intent.trigger_mode
            for schedule_type in option.allowed_schedule_types
        }
        if schedule.schedule_type not in allowed_schedule_types:
            issues.append(
                ScheduleAutomationCapabilityAuditIssue(
                    code="schedule_type.forbidden",
                    message="自动任务的排程类型不在 capability 允许范围内",
                    entity_type="schedule",
                    entity_id=schedule.id,
                    schedule_id=schedule.id,
                    fields=("schedule_type",),
                )
            )

        config = dict(schedule.probe_config_json or {})
        configured_source = str(config.get("source_key") or "").strip()
        if intent.source_key is not None and configured_source and configured_source != intent.source_key:
            issues.append(
                ScheduleAutomationCapabilityAuditIssue(
                    code="source_key.operator_forbidden",
                    message="持久化探测来源与系统默认来源不一致",
                    entity_type="schedule",
                    entity_id=schedule.id,
                    schedule_id=schedule.id,
                    fields=("probe_config_json.source_key",),
                )
            )
        if config.get("workflow_dataset_keys"):
            issues.append(
                ScheduleAutomationCapabilityAuditIssue(
                    code="workflow_dataset_keys.operator_forbidden",
                    message="自动任务包含已禁止的工作流探测目标配置",
                    entity_type="schedule",
                    entity_id=schedule.id,
                    schedule_id=schedule.id,
                    fields=("probe_config_json.workflow_dataset_keys",),
                )
            )
        return intent

    def _audit_schedule_rules(
        self,
        *,
        schedule: ScheduleAuditRecord,
        rules: list[ProbeRuleAuditRecord],
        template: ProbeRuleTemplate | None,
        issues: list[ScheduleAutomationCapabilityAuditIssue],
    ) -> None:
        if template is None:
            for rule in rules:
                self._audit_forbidden_rule_target(
                    rule,
                    issues=issues,
                    schedule_id=schedule.id,
                    parent_target_type=schedule.target_type,
                )
                if schedule.target_type == "dataset_action" and rule.workflow_key is None and rule.step_key is None:
                    issues.append(
                        ScheduleAutomationCapabilityAuditIssue(
                            code="probe_rule.mismatch",
                            message="当前自动任务不应绑定探测规则",
                            entity_type="probe_rule",
                            entity_id=rule.id,
                            schedule_id=schedule.id,
                            probe_rule_id=rule.id,
                        )
                    )
            return

        if not rules:
            issues.append(
                ScheduleAutomationCapabilityAuditIssue(
                    code="probe_rule.missing",
                    message="探测自动任务缺少系统生成的探测规则",
                    entity_type="schedule",
                    entity_id=schedule.id,
                    schedule_id=schedule.id,
                )
            )
            return
        if len(rules) > 1:
            issues.append(
                ScheduleAutomationCapabilityAuditIssue(
                    code="probe_rule.mismatch",
                    message=f"探测自动任务应仅有一条规则，实际为 {len(rules)} 条",
                    entity_type="schedule",
                    entity_id=schedule.id,
                    schedule_id=schedule.id,
                )
            )
        for rule in rules:
            self._audit_forbidden_rule_target(
                rule,
                issues=issues,
                schedule_id=schedule.id,
                parent_target_type=schedule.target_type,
            )
            fields = self._rule_mismatch_fields(rule, template=template)
            if fields:
                issues.append(
                    ScheduleAutomationCapabilityAuditIssue(
                        code="probe_rule.mismatch",
                        message="探测规则与自动任务 capability 派生结果不一致",
                        entity_type="probe_rule",
                        entity_id=rule.id,
                        schedule_id=schedule.id,
                        probe_rule_id=rule.id,
                        fields=fields,
                    )
                )

    @staticmethod
    def _audit_forbidden_rule_target(
        rule: ProbeRuleAuditRecord,
        *,
        issues: list[ScheduleAutomationCapabilityAuditIssue],
        schedule_id: int | None = None,
        parent_target_type: str | None = None,
    ) -> None:
        fields = [
            field_name
            for field_name, value in (("workflow_key", rule.workflow_key), ("step_key", rule.step_key))
            if value is not None
        ]
        if parent_target_type in {"workflow", "maintenance_action"}:
            fields.append("parent_schedule.target_type")
        if not fields:
            return
        issues.append(
            ScheduleAutomationCapabilityAuditIssue(
                code="probe_rule.target_forbidden",
                message="探测规则不能绑定工作流或工作流步骤",
                entity_type="probe_rule",
                entity_id=rule.id,
                schedule_id=schedule_id,
                probe_rule_id=rule.id,
                fields=tuple(fields),
            )
        )

    @staticmethod
    def _rule_mismatch_fields(rule: ProbeRuleAuditRecord, *, template: ProbeRuleTemplate) -> tuple[str, ...]:
        expected = {
            "dataset_key": template.dataset_key,
            "source_key": template.source_key,
            "status": "active",
            "window_start": template.window_start,
            "window_end": template.window_end,
            "probe_interval_seconds": template.probe_interval_seconds,
            "probe_condition_json": template.probe_condition_json,
            "on_success_action_json": template.on_success_action_json,
            "max_triggers_per_day": template.max_triggers_per_day,
            "timezone_name": template.timezone_name,
            "trigger_mode": "task_run",
            "workflow_key": None,
            "step_key": None,
        }
        return tuple(field_name for field_name, expected_value in expected.items() if getattr(rule, field_name) != expected_value)

    @staticmethod
    def _load_schedules(
        session: Session,
        *,
        batch_size: int,
        max_records: int,
    ) -> tuple[list[ScheduleAuditRecord], int, bool]:
        rows: list[ScheduleAuditRecord] = []
        pages = 0
        last_id: int | None = None
        while len(rows) < max_records:
            statement = select(
                OpsSchedule.id.label("id"),
                OpsSchedule.target_type.label("target_type"),
                OpsSchedule.target_key.label("target_key"),
                OpsSchedule.status.label("status"),
                OpsSchedule.schedule_type.label("schedule_type"),
                OpsSchedule.trigger_mode.label("trigger_mode"),
                OpsSchedule.timezone.label("timezone"),
                OpsSchedule.calendar_policy.label("calendar_policy"),
                OpsSchedule.probe_config_json.label("probe_config_json"),
                OpsSchedule.params_json.label("params_json"),
            ).order_by(OpsSchedule.id.asc()).limit(min(batch_size, max_records - len(rows)))
            if last_id is not None:
                statement = statement.where(OpsSchedule.id > last_id)
            batch = list(session.execute(statement).mappings())
            if not batch:
                return rows, pages, False
            pages += 1
            for item in batch:
                rows.append(ScheduleAuditRecord(**dict(item)))
            last_id = rows[-1].id
            if len(batch) < batch_size:
                return rows, pages, False
        has_more = session.execute(
            select(OpsSchedule.id).where(OpsSchedule.id > last_id).order_by(OpsSchedule.id.asc()).limit(1)
        ).first() is not None
        return rows, pages, has_more

    @staticmethod
    def _load_probe_rules(
        session: Session,
        *,
        batch_size: int,
        max_records: int,
    ) -> tuple[list[ProbeRuleAuditRecord], int, bool]:
        rows: list[ProbeRuleAuditRecord] = []
        pages = 0
        last_id: int | None = None
        while len(rows) < max_records:
            statement = select(
                ProbeRule.id.label("id"),
                ProbeRule.schedule_id.label("schedule_id"),
                ProbeRule.dataset_key.label("dataset_key"),
                ProbeRule.source_key.label("source_key"),
                ProbeRule.status.label("status"),
                ProbeRule.window_start.label("window_start"),
                ProbeRule.window_end.label("window_end"),
                ProbeRule.probe_interval_seconds.label("probe_interval_seconds"),
                ProbeRule.probe_condition_json.label("probe_condition_json"),
                ProbeRule.on_success_action_json.label("on_success_action_json"),
                ProbeRule.max_triggers_per_day.label("max_triggers_per_day"),
                ProbeRule.timezone_name.label("timezone_name"),
                ProbeRule.trigger_mode.label("trigger_mode"),
                ProbeRule.workflow_key.label("workflow_key"),
                ProbeRule.step_key.label("step_key"),
            ).order_by(ProbeRule.id.asc()).limit(min(batch_size, max_records - len(rows)))
            if last_id is not None:
                statement = statement.where(ProbeRule.id > last_id)
            batch = list(session.execute(statement).mappings())
            if not batch:
                return rows, pages, False
            pages += 1
            for item in batch:
                rows.append(ProbeRuleAuditRecord(**dict(item)))
            last_id = rows[-1].id
            if len(batch) < batch_size:
                return rows, pages, False
        has_more = session.execute(
            select(ProbeRule.id).where(ProbeRule.id > last_id).order_by(ProbeRule.id.asc()).limit(1)
        ).first() is not None
        return rows, pages, has_more
