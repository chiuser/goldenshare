from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.orm import Session

from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.schedule import OpsSchedule
from src.foundation.datasets.registry import get_dataset_action_key, get_dataset_definition_by_action_key
from src.ops.action_catalog import get_workflow_definition
from src.app.exceptions import WebAppError


SUPPORTED_TRIGGER_MODES = {"schedule", "probe", "schedule_probe_fallback"}


@dataclass(slots=True, frozen=True)
class ProbeRuleTemplate:
    dataset_key: str
    trigger_mode: str
    workflow_key: str | None
    step_key: str | None
    source_key: str | None
    window_start: str | None
    window_end: str | None
    probe_interval_seconds: int
    max_triggers_per_day: int
    timezone_name: str
    probe_condition_json: dict
    on_success_action_json: dict
    status: str


class ScheduleProbeBindingService:
    def sync_for_schedule(self, session: Session, *, schedule: OpsSchedule, actor_user_id: int | None) -> None:
        trigger_mode = self._normalize_trigger_mode(schedule.trigger_mode)
        session.execute(delete(ProbeRule).where(ProbeRule.schedule_id == schedule.id))
        if schedule.status != "active":
            return
        if trigger_mode not in {"probe", "schedule_probe_fallback"}:
            return

        templates = self._build_templates(schedule=schedule)
        for template in templates:
            session.add(
                ProbeRule(
                    schedule_id=schedule.id,
                    name=f"{schedule.display_name} / {template.dataset_key}",
                    dataset_key=template.dataset_key,
                    trigger_mode=template.trigger_mode,
                    workflow_key=template.workflow_key,
                    step_key=template.step_key,
                    source_key=template.source_key,
                    status=template.status,
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

    def _build_templates(self, *, schedule: OpsSchedule) -> list[ProbeRuleTemplate]:
        config = dict(schedule.probe_config_json or {})
        interval = max(int(config.get("probe_interval_seconds") or 300), 30)
        max_daily = max(int(config.get("max_triggers_per_day") or 1), 1)
        source_key_raw = str(config.get("source_key") or "").strip().lower()
        source_key = None if source_key_raw in {"", "all", "__all__"} else source_key_raw
        window_start = self._normalize_time(config.get("window_start") or "15:30")
        window_end = self._normalize_time(config.get("window_end") or "17:00")
        timezone_name = str(config.get("timezone_name") or schedule.timezone or "Asia/Shanghai").strip() or "Asia/Shanghai"
        condition_kind = str(config.get("condition_kind") or "freshness_latest_open")
        min_rows_in = config.get("min_rows_in")
        condition_json = {"type": condition_kind}
        if min_rows_in is not None and str(min_rows_in).strip() != "":
            condition_json["min_rows_in"] = max(int(min_rows_in), 0)

        dataset_targets = self._resolve_dataset_targets(schedule=schedule, config=config)
        templates: list[ProbeRuleTemplate] = []
        for dataset_key, step_key in dataset_targets:
            action_json = {
                "action_type": "dataset_action",
                "action_key": get_dataset_action_key(dataset_key, "maintain"),
                "request": {
                    "dataset_key": dataset_key,
                    "action": "maintain",
                    "time_input": {"mode": "point"},
                    "filters": {},
                    "run_scope": "probe_triggered",
                },
            }
            if source_key:
                action_json["request"]["filters"]["source_key"] = source_key
            templates.append(
                ProbeRuleTemplate(
                    dataset_key=dataset_key,
                    trigger_mode="dataset_execution",
                    workflow_key=schedule.target_key if schedule.target_type == "workflow" else None,
                    step_key=step_key,
                    source_key=source_key,
                    window_start=window_start,
                    window_end=window_end,
                    probe_interval_seconds=interval,
                    max_triggers_per_day=max_daily,
                    timezone_name=timezone_name,
                    probe_condition_json=condition_json,
                    on_success_action_json=action_json,
                    status="active",
                )
            )
        return templates

    def _resolve_dataset_targets(self, *, schedule: OpsSchedule, config: dict) -> list[tuple[str, str | None]]:
        if schedule.target_type == "dataset_action":
            return [(self._dataset_from_action_target(schedule.target_key), None)]
        if schedule.target_type == "maintenance_action":
            raise WebAppError(status_code=422, code="validation_error", message="Probe schedules require dataset actions or workflows")
        if schedule.target_type == "workflow":
            raw_dataset_keys = [str(item).strip() for item in (config.get("workflow_dataset_keys") or []) if str(item).strip()]
            if raw_dataset_keys:
                return sorted({(item, None) for item in raw_dataset_keys})
            workflow = get_workflow_definition(schedule.target_key)
            if workflow is None:
                raise WebAppError(status_code=404, code="not_found", message="Workflow does not exist")
            dataset_targets = []
            for step in workflow.steps:
                dataset_key = step.dataset_key
                if dataset_key is None:
                    try:
                        definition, _action = get_dataset_definition_by_action_key(step.action_key)
                    except KeyError:
                        continue
                    dataset_key = definition.dataset_key
                dataset_targets.append((dataset_key, step.step_key))
            return sorted(set(dataset_targets))
        raise WebAppError(status_code=422, code="validation_error", message="Unsupported schedule target_type for probe")

    @staticmethod
    def _dataset_from_action_target(target_key: str) -> str:
        try:
            definition, _action = get_dataset_definition_by_action_key(target_key)
        except KeyError as exc:
            raise WebAppError(status_code=422, code="validation_error", message="Invalid dataset action target_key") from exc
        return definition.dataset_key

    @staticmethod
    def _normalize_time(value: object) -> str:
        text = str(value or "").strip()
        if len(text) == 5:
            return text
        if len(text) >= 8:
            return text[:5]
        if len(text) == 4:
            return f"0{text}"
        return "15:30"

    @staticmethod
    def _normalize_trigger_mode(value: str | None) -> str:
        trigger_mode = str(value or "schedule").strip().lower()
        if trigger_mode not in SUPPORTED_TRIGGER_MODES:
            raise WebAppError(status_code=422, code="validation_error", message=f"Unsupported trigger_mode: {trigger_mode}")
        return trigger_mode
