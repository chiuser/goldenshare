from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.orm import Session

from src.foundation.datasets.freshness_policies import CONTINUOUS_OPEN_DAY
from src.foundation.ingestion.plan_helpers import split_multi_values
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.schedule import OpsSchedule
from src.foundation.datasets.registry import get_dataset_action_key, get_dataset_definition, get_dataset_definition_by_action_key
from src.ops.action_catalog import get_workflow_definition
from src.app.exceptions import WebAppError
from src.ops.services.index_daily_remote_probe_service import (
    INDEX_DAILY_ACTION_KEY,
    INDEX_DAILY_DATASET_KEY,
    INDEX_DAILY_REMOTE_READY_CONDITION,
)
from src.ops.services.idx_factor_pro_remote_probe_service import (
    IDX_FACTOR_PRO_ACTION_KEY,
    IDX_FACTOR_PRO_DATASET_KEY,
    IDX_FACTOR_PRO_REMOTE_READY_CONDITION,
)
from src.ops.services.index_mins_remote_probe_service import (
    INDEX_MINS_ACTION_KEY,
    INDEX_MINS_ALLOWED_FREQS,
    INDEX_MINS_DATASET_KEY,
    INDEX_MINS_MIN_PROBE_INTERVAL_SECONDS,
    INDEX_MINS_REMOTE_READY_CONDITION,
)
from src.ops.services.kpl_list_remote_probe_service import (
    KPL_LIST_ACTION_KEY,
    KPL_LIST_DATASET_KEY,
    KPL_LIST_REMOTE_READY_CONDITION,
)
from src.ops.services.stk_mins_remote_probe_service import (
    STK_MINS_ACTION_KEY,
    STK_MINS_ALLOWED_FREQS,
    STK_MINS_DATASET_KEY,
    STK_MINS_REMOTE_READY_CONDITION,
)


SUPPORTED_TRIGGER_MODES = {"schedule", "probe", "schedule_probe_fallback"}
FRESHNESS_LATEST_OPEN_CONDITION = "freshness_latest_open"
REMOTE_SOURCE_PROBE_CONDITIONS = {
    STK_MINS_REMOTE_READY_CONDITION,
    INDEX_DAILY_REMOTE_READY_CONDITION,
    INDEX_MINS_REMOTE_READY_CONDITION,
    KPL_LIST_REMOTE_READY_CONDITION,
    IDX_FACTOR_PRO_REMOTE_READY_CONDITION,
}
SUPPORTED_PROBE_CONDITIONS = {FRESHNESS_LATEST_OPEN_CONDITION, *REMOTE_SOURCE_PROBE_CONDITIONS}
TIME_PARAM_KEYS = {"trade_date", "ann_date", "month", "start_date", "end_date", "start_month", "end_month"}
PARAM_RESERVED_KEYS = {"dataset_key", "action", "time_input", "filters"}


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
            self._validate_remote_idx_factor_pro_non_probe_schedule(schedule=schedule)
            return

        templates = self._build_templates(schedule=schedule)
        for template in templates:
            definition = get_dataset_definition(template.dataset_key)
            session.add(
                ProbeRule(
                    schedule_id=schedule.id,
                    name=f"{schedule.display_name} / {definition.display_name}",
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
        source_key = None if source_key_raw in {"", "all", "combined"} else source_key_raw
        window_start = self._normalize_time(config.get("window_start") or "15:30")
        window_end = self._normalize_time(config.get("window_end") or "17:00")
        timezone_name = str(config.get("timezone_name") or schedule.timezone or "Asia/Shanghai").strip() or "Asia/Shanghai"
        condition_kind = str(config.get("condition_kind") or FRESHNESS_LATEST_OPEN_CONDITION)
        if condition_kind not in SUPPORTED_PROBE_CONDITIONS:
            raise WebAppError(status_code=422, code="validation_error", message=f"不支持的探测条件：{condition_kind}")
        condition_json = {"type": condition_kind}

        filters = self._extract_schedule_filters(dict(schedule.params_json or {}))
        if condition_kind == STK_MINS_REMOTE_READY_CONDITION:
            self._validate_remote_stk_mins_schedule(schedule=schedule, filters=filters)
        if condition_kind == INDEX_DAILY_REMOTE_READY_CONDITION:
            self._validate_remote_index_daily_schedule(schedule=schedule)
        if condition_kind == INDEX_MINS_REMOTE_READY_CONDITION:
            self._validate_remote_index_mins_schedule(schedule=schedule, filters=filters, interval=interval)
        if condition_kind == KPL_LIST_REMOTE_READY_CONDITION:
            self._validate_remote_kpl_list_schedule(schedule=schedule)
        if condition_kind == IDX_FACTOR_PRO_REMOTE_READY_CONDITION:
            self._validate_remote_idx_factor_pro_schedule(
                schedule=schedule,
                filters=filters,
                interval=interval,
                max_daily=max_daily,
            )
        dataset_targets = self._resolve_dataset_targets(schedule=schedule, config=config)
        templates: list[ProbeRuleTemplate] = []
        for dataset_key, step_key in dataset_targets:
            if condition_kind == FRESHNESS_LATEST_OPEN_CONDITION:
                self._validate_freshness_latest_open_dataset(dataset_key)
            action_json = {
                "action_type": "dataset_action",
                "action_key": get_dataset_action_key(dataset_key, "maintain"),
                "request": {
                    "time_input": {"mode": "point"},
                    "filters": (
                        {}
                        if condition_kind == IDX_FACTOR_PRO_REMOTE_READY_CONDITION
                        else dict(filters) if condition_kind in REMOTE_SOURCE_PROBE_CONDITIONS else {}
                    ),
                    "run_scope": "probe_triggered",
                },
            }
            templates.append(
                ProbeRuleTemplate(
                    dataset_key=dataset_key,
                    trigger_mode="task_run",
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
            raise WebAppError(status_code=422, code="validation_error", message="探测排程只能绑定数据集维护或工作流")
        if schedule.target_type == "workflow":
            raw_dataset_keys = [str(item).strip() for item in (config.get("workflow_dataset_keys") or []) if str(item).strip()]
            if raw_dataset_keys:
                return sorted({(self._dataset_from_key(item), None) for item in raw_dataset_keys})
            workflow = get_workflow_definition(schedule.target_key)
            if workflow is None:
                raise WebAppError(status_code=404, code="not_found", message="工作流不存在")
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
        raise WebAppError(status_code=422, code="validation_error", message="不支持的探测排程目标类型")

    @staticmethod
    def _dataset_from_action_target(target_key: str) -> str:
        try:
            definition, _action = get_dataset_definition_by_action_key(target_key)
        except KeyError as exc:
            raise WebAppError(status_code=422, code="validation_error", message="数据集维护动作无效") from exc
        return definition.dataset_key

    @staticmethod
    def _dataset_from_key(dataset_key: str) -> str:
        try:
            return get_dataset_definition(dataset_key).dataset_key
        except KeyError as exc:
            raise WebAppError(status_code=422, code="validation_error", message="工作流探测数据集无效") from exc

    @staticmethod
    def _validate_freshness_latest_open_dataset(dataset_key: str) -> None:
        if dataset_key == INDEX_MINS_DATASET_KEY:
            raise WebAppError(
                status_code=422,
                code="validation_error",
                message="指数历史分钟行情必须使用“源站已有指数分钟行情”探测条件",
            )
        definition = get_dataset_definition(dataset_key)
        if definition.observability.freshness_policy != CONTINUOUS_OPEN_DAY:
            raise WebAppError(
                status_code=422,
                code="validation_error",
                message=f"{definition.display_name} 不支持“最新业务日命中最新交易日”探测条件",
            )

    @classmethod
    def _validate_remote_stk_mins_schedule(cls, *, schedule: OpsSchedule, filters: dict) -> None:
        trigger_mode = cls._normalize_trigger_mode(schedule.trigger_mode)
        if trigger_mode not in {"probe", "schedule_probe_fallback"}:
            raise WebAppError(status_code=422, code="validation_error", message="源站分钟行情探测只支持探测触发或定时 + 探测兜底")
        if schedule.target_type != "dataset_action" or schedule.target_key != STK_MINS_ACTION_KEY:
            raise WebAppError(status_code=422, code="validation_error", message="源站分钟行情探测只支持股票历史分钟行情维护")
        if schedule.calendar_policy:
            raise WebAppError(status_code=422, code="validation_error", message="源站分钟行情探测不能与日期策略混用")
        if cls._has_fixed_time_input(dict(schedule.params_json or {})):
            raise WebAppError(status_code=422, code="validation_error", message="源站分钟行情探测不能与固定维护日期混用")
        freqs = split_multi_values(filters.get("freq"))
        if not freqs:
            raise WebAppError(status_code=422, code="validation_error", message="源站分钟行情探测必须配置分钟周期")
        invalid = [item for item in freqs if item not in STK_MINS_ALLOWED_FREQS]
        if invalid:
            raise WebAppError(status_code=422, code="validation_error", message=f"不支持的分钟周期：{', '.join(invalid)}")
        dataset_key = cls._dataset_from_action_target(schedule.target_key)
        if dataset_key != STK_MINS_DATASET_KEY:
            raise WebAppError(status_code=422, code="validation_error", message="源站分钟行情探测只支持股票历史分钟行情维护")

    @classmethod
    def _validate_remote_index_daily_schedule(cls, *, schedule: OpsSchedule) -> None:
        trigger_mode = cls._normalize_trigger_mode(schedule.trigger_mode)
        if trigger_mode not in {"probe", "schedule_probe_fallback"}:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数日线探测只支持探测触发或定时 + 探测兜底")
        if schedule.target_type != "dataset_action" or schedule.target_key != INDEX_DAILY_ACTION_KEY:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数日线探测只支持指数日线行情维护")
        if schedule.calendar_policy:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数日线探测不能与日期策略混用")
        if cls._has_fixed_time_input(dict(schedule.params_json or {})):
            raise WebAppError(status_code=422, code="validation_error", message="源站指数日线探测不能与固定维护日期混用")
        dataset_key = cls._dataset_from_action_target(schedule.target_key)
        if dataset_key != INDEX_DAILY_DATASET_KEY:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数日线探测只支持指数日线行情维护")

    @classmethod
    def _validate_remote_index_mins_schedule(cls, *, schedule: OpsSchedule, filters: dict, interval: int) -> None:
        trigger_mode = cls._normalize_trigger_mode(schedule.trigger_mode)
        if trigger_mode not in {"probe", "schedule_probe_fallback"}:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数分钟行情探测只支持探测触发或定时 + 探测兜底")
        if schedule.target_type != "dataset_action" or schedule.target_key != INDEX_MINS_ACTION_KEY:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数分钟行情探测只支持指数历史分钟行情维护")
        if schedule.calendar_policy:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数分钟行情探测不能与日期策略混用")
        if cls._has_fixed_time_input(dict(schedule.params_json or {})):
            raise WebAppError(status_code=422, code="validation_error", message="源站指数分钟行情探测不能与固定维护日期混用")
        freqs = [str(item).strip() for item in split_multi_values(filters.get("freq")) if str(item).strip()]
        if len(freqs) != len(INDEX_MINS_ALLOWED_FREQS) or set(freqs) != set(INDEX_MINS_ALLOWED_FREQS):
            raise WebAppError(
                status_code=422,
                code="validation_error",
                message="源站指数分钟行情探测必须完整配置 1min/5min/15min/30min/60min",
            )
        if interval < INDEX_MINS_MIN_PROBE_INTERVAL_SECONDS:
            raise WebAppError(
                status_code=422,
                code="validation_error",
                message="源站指数分钟行情探测最小间隔为 300 秒",
            )
        dataset_key = cls._dataset_from_action_target(schedule.target_key)
        if dataset_key != INDEX_MINS_DATASET_KEY:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数分钟行情探测只支持指数历史分钟行情维护")

    @classmethod
    def _validate_remote_kpl_list_schedule(cls, *, schedule: OpsSchedule) -> None:
        trigger_mode = cls._normalize_trigger_mode(schedule.trigger_mode)
        if trigger_mode != "probe":
            raise WebAppError(status_code=422, code="validation_error", message="源站开盘啦榜单探测只支持探测触发")
        if schedule.target_type != "dataset_action" or schedule.target_key != KPL_LIST_ACTION_KEY:
            raise WebAppError(status_code=422, code="validation_error", message="源站开盘啦榜单探测只支持开盘啦榜单维护")
        if schedule.calendar_policy:
            raise WebAppError(status_code=422, code="validation_error", message="源站开盘啦榜单探测不能与日期策略混用")
        if cls._has_fixed_time_input(dict(schedule.params_json or {})):
            raise WebAppError(status_code=422, code="validation_error", message="源站开盘啦榜单探测不能与固定维护日期混用")
        dataset_key = cls._dataset_from_action_target(schedule.target_key)
        if dataset_key != KPL_LIST_DATASET_KEY:
            raise WebAppError(status_code=422, code="validation_error", message="源站开盘啦榜单探测只支持开盘啦榜单维护")

    @classmethod
    def _validate_remote_idx_factor_pro_schedule(
        cls,
        *,
        schedule: OpsSchedule,
        filters: dict,
        interval: int,
        max_daily: int,
    ) -> None:
        trigger_mode = cls._normalize_trigger_mode(schedule.trigger_mode)
        if trigger_mode not in {"probe", "schedule_probe_fallback"}:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数技术因子探测只支持探测触发或定时 + 探测兜底")
        if schedule.target_type != "dataset_action" or schedule.target_key != IDX_FACTOR_PRO_ACTION_KEY:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数技术因子探测只支持指数技术因子（专业版）维护")
        if filters:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数技术因子探测不支持维护参数")
        if schedule.calendar_policy:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数技术因子探测不能与日期策略混用")
        if cls._has_fixed_time_input(dict(schedule.params_json or {})):
            raise WebAppError(status_code=422, code="validation_error", message="源站指数技术因子探测不能与固定维护日期混用")
        if interval < 300:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数技术因子探测最小间隔为 300 秒")
        if max_daily != 1:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数技术因子探测每日最多触发 1 次")
        dataset_key = cls._dataset_from_action_target(schedule.target_key)
        if dataset_key != IDX_FACTOR_PRO_DATASET_KEY:
            raise WebAppError(status_code=422, code="validation_error", message="源站指数技术因子探测只支持指数技术因子（专业版）维护")

    @classmethod
    def _validate_remote_idx_factor_pro_non_probe_schedule(cls, *, schedule: OpsSchedule) -> None:
        config = dict(schedule.probe_config_json or {})
        condition_kind = str(config.get("condition_kind") or FRESHNESS_LATEST_OPEN_CONDITION)
        if condition_kind != IDX_FACTOR_PRO_REMOTE_READY_CONDITION:
            return
        filters = cls._extract_schedule_filters(dict(schedule.params_json or {}))
        interval = max(int(config.get("probe_interval_seconds") or 300), 30)
        max_daily = max(int(config.get("max_triggers_per_day") or 1), 1)
        cls._validate_remote_idx_factor_pro_schedule(
            schedule=schedule,
            filters=filters,
            interval=interval,
            max_daily=max_daily,
        )

    @staticmethod
    def _extract_schedule_filters(params_json: dict) -> dict:
        explicit = params_json.get("filters")
        if isinstance(explicit, dict):
            return dict(explicit)
        return {
            key: value
            for key, value in params_json.items()
            if key not in PARAM_RESERVED_KEYS and key not in TIME_PARAM_KEYS and value not in (None, "")
        }

    @staticmethod
    def _has_fixed_time_input(params_json: dict) -> bool:
        if any(params_json.get(key) not in (None, "") for key in TIME_PARAM_KEYS):
            return True
        time_input = params_json.get("time_input")
        if not isinstance(time_input, dict):
            return False
        if str(time_input.get("mode") or "point") != "point":
            return True
        return any(time_input.get(key) not in (None, "") for key in TIME_PARAM_KEYS)

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
            raise WebAppError(status_code=422, code="validation_error", message=f"不支持的触发方式：{trigger_mode}")
        return trigger_mode
