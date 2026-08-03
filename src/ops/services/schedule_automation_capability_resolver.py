from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.foundation.datasets.freshness_policies import CONTINUOUS_OPEN_DAY
from src.foundation.datasets.registry import get_dataset_definition, get_dataset_definition_by_action_key
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
class AutomationCapability:
    version: Literal[1]
    default_trigger_mode: TriggerMode
    trigger_options: tuple[TriggerModeCapability, ...]
    probe_conditions: tuple[ProbeConditionCapability, ...]


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

    def _resolve_dataset_action(self, target_key: str) -> AutomationCapability | None:
        try:
            definition, action = get_dataset_definition_by_action_key(target_key)
        except KeyError:
            return None
        if action != "maintain" or not action_is_schedulable("dataset_action", target_key):
            return None

        remote_condition = self._remote_condition_for_action(target_key)
        if remote_condition is not None:
            return AutomationCapability(
                version=1,
                default_trigger_mode=remote_condition.allowed_trigger_modes[0],
                trigger_options=tuple(
                    TriggerModeCapability(mode=mode, allowed_schedule_types=DEFAULT_SCHEDULE_TYPES)
                    for mode in remote_condition.allowed_trigger_modes
                ),
                probe_conditions=(remote_condition,),
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
                    TriggerModeCapability(mode="schedule", allowed_schedule_types=DEFAULT_SCHEDULE_TYPES),
                    TriggerModeCapability(mode="probe", allowed_schedule_types=DEFAULT_SCHEDULE_TYPES),
                    TriggerModeCapability(mode="schedule_probe_fallback", allowed_schedule_types=DEFAULT_SCHEDULE_TYPES),
                ),
                probe_conditions=(freshness_condition,),
            )
        return self._schedule_only_capability()

    @staticmethod
    def _schedule_only_capability() -> AutomationCapability:
        return AutomationCapability(
            version=1,
            default_trigger_mode="schedule",
            trigger_options=(TriggerModeCapability(mode="schedule", allowed_schedule_types=DEFAULT_SCHEDULE_TYPES),),
            probe_conditions=(),
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
                description="确认上一交易日三个市场明细完整后创建全市场单日维护任务。",
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
