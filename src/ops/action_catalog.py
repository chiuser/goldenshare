from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.foundation.datasets.models import DatasetDefinition, DatasetInputField
from src.foundation.datasets.registry import (
    get_dataset_definition,
    get_dataset_definition_by_action_key,
)


ParameterType = Literal["string", "date", "month", "integer", "boolean", "enum"]
ActionType = Literal["dataset_action", "maintenance_action", "workflow"]


@dataclass(slots=True, frozen=True)
class ActionParameter:
    key: str
    display_name: str
    param_type: ParameterType
    description: str
    required: bool = False
    options: tuple[str, ...] = ()
    multi_value: bool = False
    default_value: Any | None = None


def dataset_field_default_value(field: DatasetInputField, enum_fanout_defaults: dict[str, tuple[str, ...]]) -> Any | None:
    fanout_default = enum_fanout_defaults.get(field.name)
    if fanout_default:
        return list(fanout_default) if field.multi_value else fanout_default[0]
    return None


@dataclass(slots=True, frozen=True)
class MaintenanceActionDefinition:
    key: str
    display_name: str
    domain_key: str
    domain_display_name: str
    description: str
    target_tables: tuple[str, ...]
    parameters: tuple[ActionParameter, ...] = ()
    default_params: dict[str, Any] = field(default_factory=dict)
    manual_enabled: bool = True
    schedule_enabled: bool = False
    retry_enabled: bool = True


@dataclass(slots=True, frozen=True)
class WorkflowStepDefinition:
    step_key: str
    action_key: str
    display_name: str
    dataset_key: str | None = None
    depends_on: tuple[str, ...] = ()
    default_params: dict[str, Any] = field(default_factory=dict)
    failure_policy_override: str | None = None
    params_override: dict[str, Any] = field(default_factory=dict)
    max_retry_per_unit: int = 2


@dataclass(slots=True, frozen=True)
class WorkflowDefinition:
    key: str
    display_name: str
    description: str
    steps: tuple[WorkflowStepDefinition, ...]
    parameters: tuple[ActionParameter, ...] = ()
    parallel_policy: str = "by_dependency"
    default_schedule_policy: str | None = None
    schedule_enabled: bool = False
    manual_enabled: bool = True
    workflow_profile: str = "point_incremental"
    failure_policy_default: str = "fail_fast"
    probe_trigger_enabled: bool = False
    resume_supported: bool = True


START_DATE_PARAM = ActionParameter(
    key="start_date",
    display_name="开始日期",
    param_type="date",
    description="维护窗口的开始日期。",
)
END_DATE_PARAM = ActionParameter(
    key="end_date",
    display_name="结束日期",
    param_type="date",
    description="维护窗口的结束日期。",
)


MAINTENANCE_ACTION_REGISTRY: dict[str, MaintenanceActionDefinition] = {
    "maintenance.rebuild_dm": MaintenanceActionDefinition(
        key="maintenance.rebuild_dm",
        display_name="刷新数据集市快照",
        domain_key="maintenance",
        domain_display_name="维护动作",
        description="刷新数据集市中的物化视图。",
        target_tables=("dm.equity_daily_snapshot",),
        manual_enabled=True,
        schedule_enabled=True,
        retry_enabled=True,
    ),
    "maintenance.rebuild_index_kline_serving": MaintenanceActionDefinition(
        key="maintenance.rebuild_index_kline_serving",
        display_name="维护指数周线/月线服务表",
        domain_key="maintenance",
        domain_display_name="维护动作",
        description="基于指数日线服务表补齐周线/月线服务表（API 优先，日线派生补缺）。",
        target_tables=("core_serving.index_weekly_serving", "core_serving.index_monthly_serving"),
        parameters=(START_DATE_PARAM, END_DATE_PARAM),
        manual_enabled=True,
        schedule_enabled=False,
        retry_enabled=True,
    ),
}


def _dataset_workflow_step(step_key: str, dataset_key: str) -> WorkflowStepDefinition:
    definition = get_dataset_definition(dataset_key)
    return WorkflowStepDefinition(
        step_key=step_key,
        action_key=definition.action_key("maintain"),
        display_name=definition.display_name,
        dataset_key=definition.dataset_key,
    )


WORKFLOW_DEFINITION_REGISTRY: dict[str, WorkflowDefinition] = {
    "reference_data_refresh": WorkflowDefinition(
        key="reference_data_refresh",
        display_name="基础主数据刷新",
        description="刷新股票、交易日历、ETF 与指数基础信息。",
        steps=(
            _dataset_workflow_step("stock_basic", "stock_basic"),
            _dataset_workflow_step("trade_cal", "trade_cal"),
            _dataset_workflow_step("etf_basic", "etf_basic"),
            _dataset_workflow_step("etf_index", "etf_index"),
            _dataset_workflow_step("index_basic", "index_basic"),
            _dataset_workflow_step("hk_basic", "hk_basic"),
        ),
        schedule_enabled=True,
        manual_enabled=True,
    ),
    "daily_market_close_maintenance": WorkflowDefinition(
        key="daily_market_close_maintenance",
        display_name="每日收盘后维护",
        description="覆盖日线、日指标、资金流、榜单与基金/指数日线的每日维护工作流。",
        steps=(
            _dataset_workflow_step("daily", "daily"),
            _dataset_workflow_step("adj_factor", "adj_factor"),
            _dataset_workflow_step("daily_basic", "daily_basic"),
            _dataset_workflow_step("cyq_perf", "cyq_perf"),
            _dataset_workflow_step("stk_factor_pro", "stk_factor_pro"),
            _dataset_workflow_step("margin", "margin"),
            _dataset_workflow_step("stk_limit", "stk_limit"),
            _dataset_workflow_step("stock_st", "stock_st"),
            _dataset_workflow_step("limit_list", "limit_list_d"),
            _dataset_workflow_step("suspend_d", "suspend_d"),
            _dataset_workflow_step("top_list", "top_list"),
            _dataset_workflow_step("block_trade", "block_trade"),
            _dataset_workflow_step("fund_daily", "fund_daily"),
            _dataset_workflow_step("fund_adj", "fund_adj"),
            _dataset_workflow_step("index_daily", "index_daily"),
            _dataset_workflow_step("ths_daily", "ths_daily"),
            _dataset_workflow_step("dc_index", "dc_index"),
            _dataset_workflow_step("dc_member", "dc_member"),
            _dataset_workflow_step("dc_daily", "dc_daily"),
            _dataset_workflow_step("ths_hot", "ths_hot"),
            _dataset_workflow_step("dc_hot", "dc_hot"),
            _dataset_workflow_step("kpl_list", "kpl_list"),
            _dataset_workflow_step("limit_list_ths", "limit_list_ths"),
            _dataset_workflow_step("limit_step", "limit_step"),
            _dataset_workflow_step("limit_cpt_list", "limit_cpt_list"),
            _dataset_workflow_step("kpl_concept_cons", "kpl_concept_cons"),
        ),
        default_schedule_policy="trading_day_close",
        schedule_enabled=True,
        manual_enabled=True,
    ),
    "daily_moneyflow_maintenance": WorkflowDefinition(
        key="daily_moneyflow_maintenance",
        display_name="每日资金流向维护",
        description="覆盖个股、概念、行业、板块和市场维度的资金流向每日维护工作流。",
        steps=(
            _dataset_workflow_step("moneyflow", "moneyflow"),
            _dataset_workflow_step("moneyflow_ths", "moneyflow_ths"),
            _dataset_workflow_step("moneyflow_dc", "moneyflow_dc"),
            _dataset_workflow_step("moneyflow_cnt_ths", "moneyflow_cnt_ths"),
            _dataset_workflow_step("moneyflow_ind_ths", "moneyflow_ind_ths"),
            _dataset_workflow_step("moneyflow_ind_dc", "moneyflow_ind_dc"),
            _dataset_workflow_step("moneyflow_mkt_dc", "moneyflow_mkt_dc"),
        ),
        schedule_enabled=True,
        manual_enabled=True,
    ),
    "board_reference_refresh": WorkflowDefinition(
        key="board_reference_refresh",
        display_name="板块主数据刷新",
        description="刷新同花顺板块主数据与同花顺板块成分。",
        steps=(
            _dataset_workflow_step("ths_index", "ths_index"),
            _dataset_workflow_step("ths_member", "ths_member"),
        ),
        schedule_enabled=True,
        manual_enabled=True,
    ),
    "index_extension_maintenance": WorkflowDefinition(
        key="index_extension_maintenance",
        display_name="指数扩展数据维护",
        description="批量维护指数日线、周线、月线、日指标和成分权重。",
        steps=(
            _dataset_workflow_step("index_daily", "index_daily"),
            _dataset_workflow_step("index_weekly", "index_weekly"),
            _dataset_workflow_step("index_monthly", "index_monthly"),
            _dataset_workflow_step("index_daily_basic", "index_daily_basic"),
            _dataset_workflow_step("index_weight", "index_weight"),
        ),
        manual_enabled=True,
    ),
    "index_kline_maintenance_pipeline": WorkflowDefinition(
        key="index_kline_maintenance_pipeline",
        display_name="指数K线全链路维护",
        description="按日线→周线→月线→服务表补齐的顺序执行指数K线维护工作流。",
        parameters=(START_DATE_PARAM, END_DATE_PARAM),
        steps=(
            _dataset_workflow_step("index_daily", "index_daily"),
            _dataset_workflow_step("index_weekly", "index_weekly"),
            _dataset_workflow_step("index_monthly", "index_monthly"),
            WorkflowStepDefinition("rebuild_index_serving", "maintenance.rebuild_index_kline_serving", "补齐指数服务表"),
        ),
        manual_enabled=True,
        schedule_enabled=False,
    ),
}


def list_maintenance_actions() -> list[MaintenanceActionDefinition]:
    return [MAINTENANCE_ACTION_REGISTRY[key] for key in sorted(MAINTENANCE_ACTION_REGISTRY)]


def get_maintenance_action(key: str) -> MaintenanceActionDefinition | None:
    return MAINTENANCE_ACTION_REGISTRY.get(key)


def list_workflow_definitions() -> list[WorkflowDefinition]:
    return [WORKFLOW_DEFINITION_REGISTRY[key] for key in sorted(WORKFLOW_DEFINITION_REGISTRY)]


def get_workflow_definition(key: str) -> WorkflowDefinition | None:
    return WORKFLOW_DEFINITION_REGISTRY.get(key)


def get_catalog_target(action_type: str, action_key: str) -> DatasetDefinition | MaintenanceActionDefinition | WorkflowDefinition | None:
    if action_type == "dataset_action":
        try:
            definition, _action = get_dataset_definition_by_action_key(action_key)
            return definition
        except KeyError:
            return None
    if action_type == "maintenance_action":
        return get_maintenance_action(action_key)
    if action_type == "workflow":
        return get_workflow_definition(action_key)
    return None


def get_manual_action_key_for_target(target_type: str, target_key: str) -> str | None:
    if target_type == "dataset_action":
        try:
            get_dataset_definition_by_action_key(target_key)
            return target_key
        except KeyError:
            return None
    if target_type == "workflow":
        return f"workflow:{target_key}" if get_workflow_definition(target_key) is not None else None
    return None


def get_action_display_name(action_type: str, action_key: str) -> str | None:
    if action_type == "dataset_action":
        try:
            definition, action = get_dataset_definition_by_action_key(action_key)
            return definition.action_display_name(action)
        except KeyError:
            return None
    if action_type == "maintenance_action":
        action = get_maintenance_action(action_key)
        return action.display_name if action is not None else None
    if action_type == "workflow":
        workflow = get_workflow_definition(action_key)
        return workflow.display_name if workflow is not None else None
    return None


def get_target_display_name(action_type: str, action_key: str) -> str | None:
    if action_type == "dataset_action":
        try:
            definition, _action = get_dataset_definition_by_action_key(action_key)
            return definition.display_name
        except KeyError:
            return None
    if action_type == "maintenance_action":
        action = get_maintenance_action(action_key)
        return action.display_name if action is not None else None
    if action_type == "workflow":
        workflow = get_workflow_definition(action_key)
        return workflow.display_name if workflow is not None else None
    return None


def action_is_schedulable(action_type: str, action_key: str) -> bool:
    if action_type == "dataset_action":
        try:
            definition, action = get_dataset_definition_by_action_key(action_key)
        except KeyError:
            return False
        capability = definition.capabilities.get_action(action)
        return bool(capability and capability.schedule_enabled)
    if action_type == "maintenance_action":
        action = get_maintenance_action(action_key)
        return bool(action and action.schedule_enabled)
    if action_type == "workflow":
        workflow = get_workflow_definition(action_key)
        return bool(workflow and workflow.schedule_enabled)
    return False
