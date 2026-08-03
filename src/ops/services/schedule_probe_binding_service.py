from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.orm import Session

from src.foundation.datasets.registry import get_dataset_action_key, get_dataset_definition
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.services.schedule_automation_capability_resolver import (
    REMOTE_SOURCE_PROBE_CONDITIONS,
    ScheduleAutomationCapabilityResolver,
    ValidatedAutomationIntent,
)


@dataclass(slots=True, frozen=True)
class ProbeRuleTemplate:
    dataset_key: str
    source_key: str
    window_start: str
    window_end: str
    probe_interval_seconds: int
    max_triggers_per_day: int
    timezone_name: str
    probe_condition_json: dict
    on_success_action_json: dict


class ScheduleProbeBindingService:
    """Persist at most one dataset probe rule from a validated automation intent."""

    def __init__(self) -> None:
        self.capability_resolver = ScheduleAutomationCapabilityResolver()

    def sync_for_schedule(self, session: Session, *, schedule: OpsSchedule, actor_user_id: int | None) -> None:
        # A pause must remain possible even when a legacy schedule no longer meets
        # current rules.  It only removes the subordinate rule and never validates.
        if schedule.status != "active":
            session.execute(delete(ProbeRule).where(ProbeRule.schedule_id == schedule.id))
            return

        intent = self.capability_resolver.validate_schedule(schedule)
        session.execute(delete(ProbeRule).where(ProbeRule.schedule_id == schedule.id))
        template = self.build_template(intent)
        if template is None:
            return

        definition = get_dataset_definition(template.dataset_key)
        session.add(
            ProbeRule(
                schedule_id=schedule.id,
                name=f"{schedule.display_name} / {definition.display_name}",
                dataset_key=template.dataset_key,
                trigger_mode="task_run",
                workflow_key=None,
                step_key=None,
                source_key=template.source_key,
                status="active",
                window_start=template.window_start,
                window_end=template.window_end,
                probe_interval_seconds=template.probe_interval_seconds,
                probe_condition_json=template.probe_condition_json,
                on_success_action_json=template.on_success_action_json,
                max_triggers_per_day=template.max_triggers_per_day,
                timezone_name=template.timezone_name,
                rule_version=1,
                created_by_user_id=actor_user_id,
                updated_by_user_id=actor_user_id,
            )
        )

    @staticmethod
    def build_template(intent: ValidatedAutomationIntent) -> ProbeRuleTemplate | None:
        if intent.condition is None:
            return None
        assert intent.dataset_key is not None
        assert intent.source_key is not None
        assert intent.window_start is not None
        assert intent.window_end is not None
        assert intent.probe_interval_seconds is not None
        assert intent.max_triggers_per_day is not None
        assert intent.timezone_name is not None

        filters = (
            dict(intent.filters)
            if intent.condition.kind in REMOTE_SOURCE_PROBE_CONDITIONS
            and intent.condition.filters.mode != "forbidden"
            else {}
        )
        return ProbeRuleTemplate(
            dataset_key=intent.dataset_key,
            source_key=intent.source_key,
            window_start=intent.window_start,
            window_end=intent.window_end,
            probe_interval_seconds=intent.probe_interval_seconds,
            max_triggers_per_day=intent.max_triggers_per_day,
            timezone_name=intent.timezone_name,
            probe_condition_json={"type": intent.condition.kind},
            on_success_action_json={
                "action_type": "dataset_action",
                "action_key": get_dataset_action_key(intent.dataset_key, "maintain"),
                "request": {
                    "time_input": {"mode": "point"},
                    "filters": filters,
                    "run_scope": "probe_triggered",
                },
            },
        )
