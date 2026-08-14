from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from src.foundation.datasets.freshness_policies import CONTINUOUS_OPEN_DAY
from src.foundation.ingestion.plan_helpers import split_multi_values
from src.foundation.datasets.registry import get_dataset_definition, get_dataset_definition_by_action_key
from src.app.exceptions import WebAppError
from src.ops.action_catalog import action_is_schedulable, get_maintenance_action, get_workflow_definition
from src.ops.services.idx_factor_pro_remote_probe_service import (
    IDX_FACTOR_PRO_ACTION_KEY,
    IDX_FACTOR_PRO_REMOTE_READY_CONDITION,
)
from src.ops.services.index_daily_remote_probe_service import (
    INDEX_DAILY_ACTION_KEY,
    INDEX_DAILY_REMOTE_READY_CONDITION,
)
from src.ops.services.index_mins_remote_probe_service import (
    INDEX_MINS_ACTION_KEY,
    INDEX_MINS_ALLOWED_FREQS,
    INDEX_MINS_MIN_PROBE_INTERVAL_SECONDS,
    INDEX_MINS_REMOTE_READY_CONDITION,
)
from src.ops.services.kpl_list_remote_probe_service import (
    KPL_LIST_ACTION_KEY,
    KPL_LIST_REMOTE_READY_CONDITION,
)
from src.ops.services.margin_detail_remote_probe_service import (
    MARGIN_DETAIL_ACTION_KEY,
    MARGIN_DETAIL_REMOTE_READY_CONDITION,
)
from src.ops.services.margin_remote_probe_service import MARGIN_ACTION_KEY, MARGIN_REMOTE_READY_CONDITION
from src.ops.services.stk_mins_remote_probe_service import (
    STK_MINS_ACTION_KEY,
    STK_MINS_ALLOWED_FREQS,
    STK_MINS_REMOTE_READY_CONDITION,
)
from src.ops.services.dataset_schedule_time_policy_resolver import (
    DatasetScheduleTimePolicyCapability,
    DatasetScheduleTimePolicyResolver,
)

if TYPE_CHECKING:
    from src.foundation.datasets.models import DatasetDefinition
    from src.ops.models.ops.schedule import OpsSchedule


TriggerMode = Literal["schedule", "probe", "schedule_probe_fallback"]
ScheduleType = Literal["cron", "once"]
FRESHNESS_LATEST_OPEN_CONDITION = "freshness_latest_open"
SUPPORTED_TRIGGER_MODES = frozenset({"schedule", "probe", "schedule_probe_fallback"})
REMOTE_SOURCE_PROBE_CONDITIONS = frozenset(
    {
        STK_MINS_REMOTE_READY_CONDITION,
        INDEX_DAILY_REMOTE_READY_CONDITION,
        INDEX_MINS_REMOTE_READY_CONDITION,
        KPL_LIST_REMOTE_READY_CONDITION,
        IDX_FACTOR_PRO_REMOTE_READY_CONDITION,
        MARGIN_REMOTE_READY_CONDITION,
        MARGIN_DETAIL_REMOTE_READY_CONDITION,
    }
)
SUPPORTED_PROBE_CONDITIONS = frozenset({FRESHNESS_LATEST_OPEN_CONDITION, *REMOTE_SOURCE_PROBE_CONDITIONS})
DEFAULT_SCHEDULE_TYPES: tuple[ScheduleType, ...] = ("cron", "once")
TIME_PARAM_KEYS = {"trade_date", "ann_date", "month", "start_date", "end_date", "start_month", "end_month"}
PARAM_RESERVED_KEYS = {"dataset_key", "action", "time_input", "filters", "schedule_policy_params"}
DEFAULT_PROBE_WINDOW_START = "15:30"
DEFAULT_PROBE_WINDOW_END = "17:00"
DEFAULT_PROBE_INTERVAL_SECONDS = 300
DEFAULT_MAX_TRIGGERS_PER_DAY = 1
MINIMUM_PROBE_INTERVAL_SECONDS = 30


@dataclass(frozen=True, slots=True)
class TriggerModeCapability:
    mode: TriggerMode
    allowed_schedule_types: tuple[ScheduleType, ...]


@dataclass(frozen=True, slots=True)
class FilterCapability:
    mode: Literal["dataset_default", "forbidden", "required_allowed_values"]
    required_fields: tuple[str, ...] = ()
    allowed_values: tuple[tuple[str, tuple[str, ...]], ...] = ()
    require_complete_allowed_values: bool = False


@dataclass(frozen=True, slots=True)
class ProbeWindowCapability:
    mode: Literal["operator_default", "fixed"]
    start: str | None = None
    end: str | None = None


@dataclass(frozen=True, slots=True)
class ProbeIntegerCapability:
    mode: Literal["operator_default", "minimum", "fixed"]
    value: int | None = None


@dataclass(frozen=True, slots=True)
class ProbeConfigCapability:
    source: Literal["system_default"]
    source_label: str
    window: ProbeWindowCapability
    probe_interval_seconds: ProbeIntegerCapability
    max_triggers_per_day: ProbeIntegerCapability


@dataclass(frozen=True, slots=True)
class ProbeConditionCapability:
    kind: str
    label: str
    description: str
    allowed_trigger_modes: tuple[Literal["probe", "schedule_probe_fallback"], ...]
    calendar_policy: Literal["dataset_default", "forbidden"]
    time_input: Literal["dataset_default", "forbidden"]
    filters: FilterCapability
    probe: ProbeConfigCapability


@dataclass(frozen=True, slots=True)
class FixedScheduleCapability:
    cron_expr: str
    timezone: str
    display_text: str


@dataclass(frozen=True, slots=True)
class AutomationCapability:
    version: Literal[1]
    default_trigger_mode: TriggerMode
    trigger_options: tuple[TriggerModeCapability, ...]
    probe_conditions: tuple[ProbeConditionCapability, ...]
    calendar_policy_rules: tuple[DatasetScheduleTimePolicyCapability, ...]
    time_input_contract: "AutomationTimeInputContract | None" = None
    fixed_schedule: FixedScheduleCapability | None = None


@dataclass(frozen=True, slots=True)
class AutomationTimeInputContract:
    supported_modes: tuple[Literal["none", "point", "range"], ...]
    point_field: str | None
    range_start_field: str | None
    range_end_field: str | None
    granularity: Literal["none", "day", "month"]


@dataclass(frozen=True, slots=True)
class ValidatedAutomationIntent:
    """A validated automatic-task configuration, ready for a binding to persist."""

    capability: AutomationCapability
    trigger_mode: TriggerMode
    dataset_key: str | None
    condition: ProbeConditionCapability | None
    source_key: str | None
    window_start: str | None
    window_end: str | None
    probe_interval_seconds: int | None
    max_triggers_per_day: int | None
    timezone_name: str | None
    filters: dict


def _operator_probe_config(
    *,
    minimum_interval: int | None = None,
    fixed_window: tuple[str, str] | None = None,
    fixed_interval: int | None = None,
    fixed_max_triggers: int | None = None,
) -> ProbeConfigCapability:
    return ProbeConfigCapability(
        source="system_default",
        source_label="系统默认来源",
        window=(
            ProbeWindowCapability(mode="fixed", start=fixed_window[0], end=fixed_window[1])
            if fixed_window is not None
            else ProbeWindowCapability(mode="operator_default")
        ),
        probe_interval_seconds=(
            ProbeIntegerCapability(mode="fixed", value=fixed_interval)
            if fixed_interval is not None
            else ProbeIntegerCapability(mode="minimum", value=minimum_interval)
            if minimum_interval is not None
            else ProbeIntegerCapability(mode="operator_default")
        ),
        max_triggers_per_day=(
            ProbeIntegerCapability(mode="fixed", value=fixed_max_triggers)
            if fixed_max_triggers is not None
            else ProbeIntegerCapability(mode="operator_default")
        ),
    )


class ScheduleAutomationCapabilityResolver:
    """The single, target-context source of automatic-task configuration capability."""

    def resolve(self, *, target_type: str, target_key: str) -> AutomationCapability | None:
        if target_type == "dataset_action":
            return self._resolve_dataset_action(target_key)
        if target_type == "maintenance_action":
            action = get_maintenance_action(target_key)
            if action is None or not action.schedule_enabled:
                return None
            if action.readiness_condition is not None:
                initial_check = str(action.readiness_policy["initial_check_local_time"])
                hour_text, minute_text = initial_check.split(":", maxsplit=2)[:2]
                hour = int(hour_text)
                minute = int(minute_text)
                timezone_name = str(action.readiness_policy["timezone"])
                return self._schedule_only_capability(
                    allowed_schedule_types=("cron",),
                    fixed_schedule=FixedScheduleCapability(
                        cron_expr=f"{minute} {hour} * * 1-5",
                        timezone=timezone_name,
                        display_text=f"工作日 {hour:02d}:{minute:02d}（北京时间）",
                    ),
                )
            return self._schedule_only_capability()
        if target_type == "workflow":
            workflow = get_workflow_definition(target_key)
            if workflow is None or not workflow.schedule_enabled:
                return None
            return self._schedule_only_capability()
        return None

    def system_source_for(self, *, condition_kind: str, dataset_key: str) -> str:
        definition = get_dataset_definition(dataset_key)
        if condition_kind not in SUPPORTED_PROBE_CONDITIONS:
            raise ValueError(f"不支持的探测条件：{condition_kind}")
        if condition_kind in REMOTE_SOURCE_PROBE_CONDITIONS:
            expected_action_key = self.action_key_for_remote_condition(condition_kind)
            if definition.action_key("maintain") != expected_action_key:
                raise ValueError("源端探测条件与数据集维护动作不匹配")
        return definition.source.source_key_default

    def validate_schedule(self, schedule: OpsSchedule) -> ValidatedAutomationIntent:
        """Validate an active automatic-task intent without mutating schedules or rules."""
        capability = self.resolve(target_type=schedule.target_type, target_key=schedule.target_key)
        if capability is None:
            raise WebAppError(status_code=422, code="capability.missing", message="自动任务目标不支持排程")

        trigger_mode = self._normalize_trigger_mode(schedule.trigger_mode)
        allowed_modes = {option.mode for option in capability.trigger_options}
        if trigger_mode not in allowed_modes:
            raise WebAppError(status_code=422, code="trigger_mode.forbidden", message="该自动任务目标不支持所选触发方式")

        config = dict(schedule.probe_config_json or {})
        if trigger_mode == "schedule":
            if config:
                raise WebAppError(status_code=422, code="probe_config.forbidden", message="普通定时触发不支持探测配置")
            self._validate_schedule_policy_contract(schedule=schedule, capability=capability)
            return ValidatedAutomationIntent(
                capability=capability,
                trigger_mode=trigger_mode,
                dataset_key=None,
                condition=None,
                source_key=None,
                window_start=None,
                window_end=None,
                probe_interval_seconds=None,
                max_triggers_per_day=None,
                timezone_name=None,
                filters={},
            )

        if schedule.target_type != "dataset_action":
            raise WebAppError(status_code=422, code="probe_rule.target_forbidden", message="探测触发只能绑定数据集维护动作")
        if not config:
            raise WebAppError(status_code=422, code="probe_config.required", message="探测触发必须配置探测条件")

        condition_kind = str(config.get("condition_kind") or "").strip()
        condition = next((item for item in capability.probe_conditions if item.kind == condition_kind), None)
        if condition is None:
            raise WebAppError(status_code=422, code="condition.unsupported", message="该自动任务目标不支持所选探测条件")
        if trigger_mode not in condition.allowed_trigger_modes:
            raise WebAppError(status_code=422, code="trigger_mode.forbidden", message="探测条件不支持所选触发方式")

        dataset_key = self._dataset_key_for_action(schedule.target_key)
        filters = self._extract_schedule_filters(dict(schedule.params_json or {}))
        self._validate_condition_scope(schedule=schedule, dataset_key=dataset_key, condition=condition, filters=filters)
        window_start, window_end = self._resolve_probe_window(config=config, condition=condition)
        probe_interval_seconds = self._resolve_probe_integer(
            config=config,
            field_name="probe_interval_seconds",
            capability=condition.probe.probe_interval_seconds,
            default=DEFAULT_PROBE_INTERVAL_SECONDS,
            minimum=MINIMUM_PROBE_INTERVAL_SECONDS,
        )
        max_triggers_per_day = self._resolve_probe_integer(
            config=config,
            field_name="max_triggers_per_day",
            capability=condition.probe.max_triggers_per_day,
            default=DEFAULT_MAX_TRIGGERS_PER_DAY,
            minimum=1,
        )
        return ValidatedAutomationIntent(
            capability=capability,
            trigger_mode=trigger_mode,
            dataset_key=dataset_key,
            condition=condition,
            source_key=self.system_source_for(condition_kind=condition.kind, dataset_key=dataset_key),
            window_start=window_start,
            window_end=window_end,
            probe_interval_seconds=probe_interval_seconds,
            max_triggers_per_day=max_triggers_per_day,
            timezone_name=str(config.get("timezone_name") or schedule.timezone or "Asia/Shanghai").strip() or "Asia/Shanghai",
            filters=filters,
        )

    @staticmethod
    def _validate_schedule_policy_contract(*, schedule: OpsSchedule, capability: AutomationCapability) -> None:
        configured_policy = str(schedule.calendar_policy or "").strip() or None
        declared_rules = tuple(rule for rule in capability.calendar_policy_rules if rule.declared_by_action)
        if declared_rules and configured_policy is None:
            raise WebAppError(
                status_code=422,
                code="calendar_policy.required",
                message=f"该自动任务必须使用系统声明的日期策略：{declared_rules[0].policy}",
            )
        if configured_policy is None:
            return
        rule = next((item for item in capability.calendar_policy_rules if item.policy == configured_policy), None)
        if rule is None:
            raise WebAppError(status_code=422, code="calendar_policy.forbidden", message="自动任务日期策略不在 capability 允许范围内")
        if schedule.schedule_type not in rule.schedule_types:
            raise WebAppError(status_code=422, code="schedule_type.forbidden", message="自动任务执行方式不支持该日期策略")
        configured_params = dict(schedule.params_json or {}).get("schedule_policy_params")
        values = configured_params if isinstance(configured_params, dict) else {}
        if configured_params not in (None, {}) and not isinstance(configured_params, dict):
            raise WebAppError(status_code=422, code="calendar_policy.params_invalid", message="日期策略参数必须是对象")
        declared_params = {field.name: field for field in rule.policy_parameters}
        unexpected = sorted(set(values) - set(declared_params))
        if unexpected:
            raise WebAppError(status_code=422, code="calendar_policy.params_invalid", message="日期策略包含未声明参数")
        missing = [field.display_label for field in declared_params.values() if field.required and values.get(field.name) in (None, "")]
        if missing:
            raise WebAppError(
                status_code=422,
                code="calendar_policy.params_required",
                message=f"日期策略缺少必填参数：{'、'.join(missing)}",
            )

    @staticmethod
    def action_key_for_remote_condition(condition_kind: str) -> str | None:
        return {
            STK_MINS_REMOTE_READY_CONDITION: STK_MINS_ACTION_KEY,
            INDEX_DAILY_REMOTE_READY_CONDITION: INDEX_DAILY_ACTION_KEY,
            INDEX_MINS_REMOTE_READY_CONDITION: INDEX_MINS_ACTION_KEY,
            KPL_LIST_REMOTE_READY_CONDITION: KPL_LIST_ACTION_KEY,
            IDX_FACTOR_PRO_REMOTE_READY_CONDITION: IDX_FACTOR_PRO_ACTION_KEY,
            MARGIN_REMOTE_READY_CONDITION: MARGIN_ACTION_KEY,
            MARGIN_DETAIL_REMOTE_READY_CONDITION: MARGIN_DETAIL_ACTION_KEY,
        }.get(condition_kind)

    @staticmethod
    def _normalize_trigger_mode(value: str | None) -> TriggerMode:
        mode = str(value or "schedule").strip().lower()
        if mode not in SUPPORTED_TRIGGER_MODES:
            raise WebAppError(status_code=422, code="trigger_mode.forbidden", message=f"不支持的触发方式：{mode}")
        return mode  # type: ignore[return-value]

    @staticmethod
    def _dataset_key_for_action(target_key: str) -> str:
        try:
            definition, action = get_dataset_definition_by_action_key(target_key)
        except KeyError as exc:
            raise WebAppError(status_code=422, code="capability.missing", message="数据集维护动作无效") from exc
        if action != "maintain":
            raise WebAppError(status_code=422, code="capability.missing", message="探测触发只能绑定数据集维护动作")
        return definition.dataset_key

    def _validate_condition_scope(
        self,
        *,
        schedule: OpsSchedule,
        dataset_key: str,
        condition: ProbeConditionCapability,
        filters: dict,
    ) -> None:
        expected_action_key = self.action_key_for_remote_condition(condition.kind)
        if expected_action_key is not None and schedule.target_key != expected_action_key:
            raise WebAppError(status_code=422, code="condition.unsupported", message="源端探测条件与数据集维护动作不匹配")
        if condition.kind == FRESHNESS_LATEST_OPEN_CONDITION:
            definition = get_dataset_definition(dataset_key)
            if definition.observability.freshness_policy != CONTINUOUS_OPEN_DAY:
                raise WebAppError(
                    status_code=422,
                    code="condition.unsupported",
                    message=f"{definition.display_name} 不支持“最新业务日命中最新交易日”探测条件",
                )
        if condition.calendar_policy == "forbidden" and schedule.calendar_policy:
            raise WebAppError(status_code=422, code="calendar_policy.forbidden", message="该源端探测不能与日期策略混用")
        if condition.time_input == "forbidden" and self._has_fixed_time_input(dict(schedule.params_json or {})):
            raise WebAppError(status_code=422, code="time_input.forbidden", message="该源端探测不能与固定维护日期混用")
        self._validate_filters(filters=filters, capability=condition.filters)

    @staticmethod
    def _validate_filters(*, filters: dict, capability: FilterCapability) -> None:
        if capability.mode == "dataset_default":
            return
        if capability.mode == "forbidden":
            if filters:
                raise WebAppError(status_code=422, code="filters.forbidden", message="该源端探测不支持维护参数")
            return
        allowed_values = {field: set(values) for field, values in capability.allowed_values}
        for field in capability.required_fields:
            values = [str(value).strip() for value in split_multi_values(filters.get(field)) if str(value).strip()]
            if not values:
                raise WebAppError(status_code=422, code="filters.incomplete", message=f"该源端探测必须配置参数：{field}")
            allowed = allowed_values.get(field, set())
            if allowed and any(value not in allowed for value in values):
                raise WebAppError(status_code=422, code="filters.incomplete", message=f"参数 {field} 包含不支持的取值")
            if capability.require_complete_allowed_values and (len(values) != len(allowed) or set(values) != allowed):
                raise WebAppError(status_code=422, code="filters.incomplete", message=f"参数 {field} 必须完整配置允许取值")
        unexpected_fields = set(filters) - set(capability.required_fields)
        if unexpected_fields:
            raise WebAppError(status_code=422, code="filters.forbidden", message="该源端探测包含不支持的维护参数")

    @staticmethod
    def _resolve_probe_window(*, config: dict, condition: ProbeConditionCapability) -> tuple[str, str]:
        configured_start = ScheduleAutomationCapabilityResolver._normalize_time(
            config.get("window_start") or DEFAULT_PROBE_WINDOW_START
        )
        configured_end = ScheduleAutomationCapabilityResolver._normalize_time(
            config.get("window_end") or DEFAULT_PROBE_WINDOW_END
        )
        capability = condition.probe.window
        if capability.mode != "fixed":
            return configured_start, configured_end
        assert capability.start is not None and capability.end is not None
        if configured_start != capability.start or configured_end != capability.end:
            raise WebAppError(status_code=422, code="probe_window.forbidden", message="该源端探测窗口由系统固定")
        return capability.start, capability.end

    @staticmethod
    def _resolve_probe_integer(
        *,
        config: dict,
        field_name: str,
        capability: ProbeIntegerCapability,
        default: int,
        minimum: int,
    ) -> int:
        try:
            configured = int(config.get(field_name) or default)
        except (TypeError, ValueError) as exc:
            raise WebAppError(status_code=422, code="probe_config.invalid", message=f"探测配置 {field_name} 必须是整数") from exc
        if configured < minimum:
            raise WebAppError(status_code=422, code="probe_config.invalid", message=f"探测配置 {field_name} 不能小于 {minimum}")
        if capability.mode == "fixed":
            assert capability.value is not None
            if configured != capability.value:
                raise WebAppError(status_code=422, code="probe_config.forbidden", message=f"探测配置 {field_name} 由系统固定")
            return capability.value
        if capability.mode == "minimum":
            assert capability.value is not None
            if configured < capability.value:
                raise WebAppError(
                    status_code=422,
                    code="probe_config.invalid",
                    message=f"探测配置 {field_name} 不能小于 {capability.value}",
                )
        return configured

    @staticmethod
    def _extract_schedule_filters(params_json: dict) -> dict:
        declared_filters = params_json.get("filters")
        if isinstance(declared_filters, dict):
            return {str(key): value for key, value in declared_filters.items() if value not in (None, "", [], {})}
        return {
            str(key): value
            for key, value in params_json.items()
            if key not in PARAM_RESERVED_KEYS and key not in TIME_PARAM_KEYS and value not in (None, "", [], {})
        }

    @staticmethod
    def _has_fixed_time_input(params_json: dict) -> bool:
        if any(params_json.get(key) not in (None, "") for key in TIME_PARAM_KEYS):
            return True
        time_input = params_json.get("time_input")
        return isinstance(time_input, dict) and any(time_input.get(key) not in (None, "") for key in TIME_PARAM_KEYS)

    @staticmethod
    def _normalize_time(value: object) -> str:
        text = str(value or "").strip()
        if len(text) == 5 and text[2] == ":":
            hour, minute = text.split(":")
        elif len(text) == 8 and text[2] == ":" and text[5] == ":":
            hour, minute, second = text.split(":")
            if second != "00":
                raise WebAppError(status_code=422, code="probe_config.invalid", message="探测窗口时间必须精确到分钟")
        else:
            raise WebAppError(status_code=422, code="probe_config.invalid", message="探测窗口时间格式必须为 HH:mm")
        try:
            normalized_hour = int(hour)
            normalized_minute = int(minute)
        except ValueError as exc:
            raise WebAppError(status_code=422, code="probe_config.invalid", message="探测窗口时间格式必须为 HH:mm") from exc
        if not 0 <= normalized_hour <= 23 or not 0 <= normalized_minute <= 59:
            raise WebAppError(status_code=422, code="probe_config.invalid", message="探测窗口时间格式必须为 HH:mm")
        return f"{normalized_hour:02d}:{normalized_minute:02d}"

    def _resolve_dataset_action(self, target_key: str) -> AutomationCapability | None:
        try:
            definition, action = get_dataset_definition_by_action_key(target_key)
        except KeyError:
            return None
        if action != "maintain" or not action_is_schedulable("dataset_action", target_key):
            return None
        calendar_policy_rules = DatasetScheduleTimePolicyResolver().resolve(
            definition=definition,
            action=action,
        )
        declared_schedule_types = tuple(
            dict.fromkeys(
                schedule_type
                for rule in calendar_policy_rules
                if rule.declared_by_action
                for schedule_type in rule.schedule_types
            )
        )
        allowed_schedule_types = declared_schedule_types or DEFAULT_SCHEDULE_TYPES
        time_input_contract = self._time_input_contract(definition=definition, action=action)

        remote_condition = self._remote_condition_for_action(target_key)
        if remote_condition is not None:
            return AutomationCapability(
                version=1,
                default_trigger_mode=remote_condition.allowed_trigger_modes[0],
                trigger_options=tuple(
                    TriggerModeCapability(mode=mode, allowed_schedule_types=allowed_schedule_types)
                    for mode in remote_condition.allowed_trigger_modes
                ),
                probe_conditions=(remote_condition,),
                calendar_policy_rules=calendar_policy_rules,
                time_input_contract=time_input_contract,
            )

        if definition.observability.freshness_policy == CONTINUOUS_OPEN_DAY:
            freshness_condition = ProbeConditionCapability(
                kind=FRESHNESS_LATEST_OPEN_CONDITION,
                label="最新业务日命中最新交易日",
                description="最新业务日达到最新开市交易日后创建维护任务。",
                allowed_trigger_modes=("probe", "schedule_probe_fallback"),
                calendar_policy="dataset_default",
                time_input="dataset_default",
                filters=FilterCapability(mode="dataset_default"),
                probe=_operator_probe_config(),
            )
            return AutomationCapability(
                version=1,
                default_trigger_mode="schedule",
                trigger_options=(
                    TriggerModeCapability(mode="schedule", allowed_schedule_types=allowed_schedule_types),
                    TriggerModeCapability(mode="probe", allowed_schedule_types=DEFAULT_SCHEDULE_TYPES),
                    TriggerModeCapability(mode="schedule_probe_fallback", allowed_schedule_types=DEFAULT_SCHEDULE_TYPES),
                ),
                probe_conditions=(freshness_condition,),
                calendar_policy_rules=calendar_policy_rules,
                time_input_contract=time_input_contract,
            )
        return self._schedule_only_capability(
            calendar_policy_rules=calendar_policy_rules,
            time_input_contract=time_input_contract,
            allowed_schedule_types=allowed_schedule_types,
        )

    @staticmethod
    def _schedule_only_capability(
        *,
        calendar_policy_rules: tuple[DatasetScheduleTimePolicyCapability, ...] = (),
        time_input_contract: AutomationTimeInputContract | None = None,
        allowed_schedule_types: tuple[ScheduleType, ...] = DEFAULT_SCHEDULE_TYPES,
        fixed_schedule: FixedScheduleCapability | None = None,
    ) -> AutomationCapability:
        return AutomationCapability(
            version=1,
            default_trigger_mode="schedule",
            trigger_options=(TriggerModeCapability(mode="schedule", allowed_schedule_types=allowed_schedule_types),),
            probe_conditions=(),
            calendar_policy_rules=calendar_policy_rules,
            time_input_contract=time_input_contract,
            fixed_schedule=fixed_schedule,
        )

    @staticmethod
    def _time_input_contract(*, definition: DatasetDefinition, action: str) -> AutomationTimeInputContract:
        capability = definition.capabilities.get_action(action)
        modes = tuple(capability.supported_time_modes) if capability is not None else ()
        time_fields = {field.name for field in definition.input_model.time_fields}
        point_field = next((field for field in ("ann_date", "trade_date", "month") if field in time_fields), None)
        if {"start_date", "end_date"}.issubset(time_fields):
            range_start_field, range_end_field = "start_date", "end_date"
        elif {"start_month", "end_month"}.issubset(time_fields):
            range_start_field, range_end_field = "start_month", "end_month"
        else:
            range_start_field, range_end_field = None, None
        granularity: Literal["none", "day", "month"]
        if point_field == "month" or range_start_field == "start_month":
            granularity = "month"
        elif point_field is not None or range_start_field is not None:
            granularity = "day"
        else:
            granularity = "none"
        return AutomationTimeInputContract(
            supported_modes=modes,  # type: ignore[arg-type]
            point_field=point_field,
            range_start_field=range_start_field,
            range_end_field=range_end_field,
            granularity=granularity,
        )

    @staticmethod
    def _remote_condition_for_action(action_key: str) -> ProbeConditionCapability | None:
        probe = _operator_probe_config()
        conditions = {
            STK_MINS_ACTION_KEY: ProbeConditionCapability(
                kind=STK_MINS_REMOTE_READY_CONDITION,
                label="源站已有股票分钟行情",
                description="源站返回全部已选分钟周期后创建维护任务。",
                allowed_trigger_modes=("probe", "schedule_probe_fallback"),
                calendar_policy="forbidden",
                time_input="forbidden",
                filters=FilterCapability(
                    mode="required_allowed_values",
                    required_fields=("freq",),
                    allowed_values=(("freq", tuple(STK_MINS_ALLOWED_FREQS)),),
                ),
                probe=probe,
            ),
            INDEX_DAILY_ACTION_KEY: ProbeConditionCapability(
                kind=INDEX_DAILY_REMOTE_READY_CONDITION,
                label="源站已有指数日线行情",
                description="源站返回目标交易日指数日线样本后创建维护任务。",
                allowed_trigger_modes=("probe", "schedule_probe_fallback"),
                calendar_policy="forbidden",
                time_input="forbidden",
                filters=FilterCapability(mode="dataset_default"),
                probe=probe,
            ),
            INDEX_MINS_ACTION_KEY: ProbeConditionCapability(
                kind=INDEX_MINS_REMOTE_READY_CONDITION,
                label="源站已有指数分钟行情",
                description="源站返回完整五个分钟周期后创建维护任务。",
                allowed_trigger_modes=("probe", "schedule_probe_fallback"),
                calendar_policy="forbidden",
                time_input="forbidden",
                filters=FilterCapability(
                    mode="required_allowed_values",
                    required_fields=("freq",),
                    allowed_values=(("freq", tuple(INDEX_MINS_ALLOWED_FREQS)),),
                    require_complete_allowed_values=True,
                ),
                probe=_operator_probe_config(minimum_interval=INDEX_MINS_MIN_PROBE_INTERVAL_SECONDS),
            ),
            KPL_LIST_ACTION_KEY: ProbeConditionCapability(
                kind=KPL_LIST_REMOTE_READY_CONDITION,
                label="源站已有开盘啦榜单",
                description="源站发布目标交易日开盘啦榜单后创建维护任务。",
                allowed_trigger_modes=("probe",),
                calendar_policy="forbidden",
                time_input="forbidden",
                filters=FilterCapability(mode="dataset_default"),
                probe=probe,
            ),
            IDX_FACTOR_PRO_ACTION_KEY: ProbeConditionCapability(
                kind=IDX_FACTOR_PRO_REMOTE_READY_CONDITION,
                label="源站已有指数技术因子",
                description="源站发布目标交易日指数技术因子后创建维护任务。",
                allowed_trigger_modes=("probe", "schedule_probe_fallback"),
                calendar_policy="forbidden",
                time_input="forbidden",
                filters=FilterCapability(mode="forbidden"),
                probe=_operator_probe_config(minimum_interval=300, fixed_max_triggers=1),
            ),
            MARGIN_ACTION_KEY: ProbeConditionCapability(
                kind=MARGIN_REMOTE_READY_CONDITION,
                label="源站已完整发布融资融券汇总",
                description="确认上一交易日三个交易所汇总完整后创建维护任务。",
                allowed_trigger_modes=("probe",),
                calendar_policy="forbidden",
                time_input="forbidden",
                filters=FilterCapability(mode="forbidden"),
                probe=_operator_probe_config(
                    fixed_window=("09:00", "09:30"), fixed_interval=300, fixed_max_triggers=1
                ),
            ),
            MARGIN_DETAIL_ACTION_KEY: ProbeConditionCapability(
                kind=MARGIN_DETAIL_REMOTE_READY_CONDITION,
                label="源站已完整发布融资融券交易明细",
                description="确认三个市场代表证券均已返回上一开市日数据后，创建全市场单日维护任务。",
                allowed_trigger_modes=("probe",),
                calendar_policy="forbidden",
                time_input="forbidden",
                filters=FilterCapability(mode="forbidden"),
                probe=_operator_probe_config(
                    fixed_window=("09:00", "09:30"), fixed_interval=300, fixed_max_triggers=1
                ),
            ),
        }
        return conditions.get(action_key)
