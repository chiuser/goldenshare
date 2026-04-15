from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.orm import Session

from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.job_schedule import JobSchedule
from src.operations.specs import get_job_spec, get_workflow_spec
from src.platform.exceptions import WebAppError


SUPPORTED_TRIGGER_MODES = {"schedule", "probe", "schedule_probe_fallback"}


@dataclass(slots=True, frozen=True)
class ProbeRuleTemplate:
    dataset_key: str
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
    def sync_for_schedule(self, session: Session, *, schedule: JobSchedule, actor_user_id: int | None) -> None:
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
                    source_key=template.source_key,
                    status=template.status,
                    window_start=template.window_start,
                    window_end=template.window_end,
                    probe_interval_seconds=template.probe_interval_seconds,
                    probe_condition_json=template.probe_condition_json,
                    on_success_action_json=template.on_success_action_json,
                    max_triggers_per_day=template.max_triggers_per_day,
                    timezone_name=template.timezone_name,
                    created_by_user_id=actor_user_id,
                    updated_by_user_id=actor_user_id,
                )
            )

    def _build_templates(self, *, schedule: JobSchedule) -> list[ProbeRuleTemplate]:
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

        dataset_keys = self._resolve_dataset_keys(schedule=schedule, config=config)
        templates: list[ProbeRuleTemplate] = []
        for dataset_key in dataset_keys:
            action_json = {
                "spec_type": "job",
                "spec_key": self._resolve_probe_job_spec(dataset_key),
                "params_json": {"run_scope": "probe_triggered"},
            }
            if source_key:
                action_json["params_json"]["source_key"] = source_key
            templates.append(
                ProbeRuleTemplate(
                    dataset_key=dataset_key,
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

    def _resolve_dataset_keys(self, *, schedule: JobSchedule, config: dict) -> list[str]:
        if schedule.spec_type == "job":
            return [self._dataset_from_job_spec(schedule.spec_key)]
        if schedule.spec_type == "workflow":
            raw_dataset_keys = [str(item).strip() for item in (config.get("workflow_dataset_keys") or []) if str(item).strip()]
            if raw_dataset_keys:
                return sorted(set(raw_dataset_keys))
            workflow = get_workflow_spec(schedule.spec_key)
            if workflow is None:
                raise WebAppError(status_code=404, code="not_found", message="Workflow spec does not exist")
            dataset_keys = [self._dataset_from_job_spec(step.job_key) for step in workflow.steps]
            return sorted(set(dataset_keys))
        raise WebAppError(status_code=422, code="validation_error", message="Unsupported schedule spec_type for probe")

    @staticmethod
    def _dataset_from_job_spec(spec_key: str) -> str:
        _, sep, resource = spec_key.partition(".")
        if not sep or not resource:
            raise WebAppError(status_code=422, code="validation_error", message="Invalid job spec_key")
        return resource

    @staticmethod
    def _resolve_probe_job_spec(dataset_key: str) -> str:
        preferred = f"sync_daily.{dataset_key}"
        if get_job_spec(preferred) is not None:
            return preferred
        fallback = f"sync_history.{dataset_key}"
        if get_job_spec(fallback) is not None:
            return fallback
        raise WebAppError(
            status_code=422,
            code="validation_error",
            message=f"数据集 {dataset_key} 缺少可用于探测触发的任务规格（sync_daily/sync_history）",
        )

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
