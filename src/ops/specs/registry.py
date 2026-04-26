from __future__ import annotations

from src.ops.specs.dataset_freshness_spec import DatasetFreshnessSpec
from src.ops.specs.job_spec import JobSpec, ParameterSpec
from src.ops.specs.observed_dataset_registry import OBSERVED_DATE_MODEL_REGISTRY
from src.ops.specs.workflow_spec import WorkflowSpec, WorkflowStepSpec
from src.foundation.datasets.registry import (
    get_dataset_definition,
    get_dataset_definition_by_action_key,
    list_dataset_definitions,
)
from src.foundation.ingestion.runtime_registry import DATASET_RUNTIME_REGISTRY


START_DATE_PARAM = ParameterSpec(
    key="start_date",
    display_name="开始日期",
    param_type="date",
    description="维护窗口的开始日期。",
)
END_DATE_PARAM = ParameterSpec(
    key="end_date",
    display_name="结束日期",
    param_type="date",
    description="维护窗口的结束日期。",
)


JOB_SPEC_REGISTRY: dict[str, JobSpec] = {}

JOB_SPEC_REGISTRY["maintenance.rebuild_dm"] = JobSpec(
    key="maintenance.rebuild_dm",
    display_name="维护动作 / rebuild_dm",
    category="maintenance",
    description="刷新数据集市中的物化视图。",
    strategy_type="maintenance_action",
    executor_kind="maintenance",
    target_tables=("dm.equity_daily_snapshot",),
    supports_manual_run=True,
    supports_schedule=True,
    supports_retry=True,
)

JOB_SPEC_REGISTRY["maintenance.rebuild_index_kline_serving"] = JobSpec(
    key="maintenance.rebuild_index_kline_serving",
    display_name="维护动作 / rebuild_index_kline_serving",
    category="maintenance",
    description="基于指数日线服务表补齐周线/月线服务表（API 优先，日线派生补缺）。",
    strategy_type="maintenance_action",
    executor_kind="maintenance",
    target_tables=("core_serving.index_weekly_serving", "core_serving.index_monthly_serving"),
    supported_params=(START_DATE_PARAM, END_DATE_PARAM),
    supports_manual_run=True,
    supports_schedule=False,
    supports_retry=True,
)


def _dataset_workflow_step(step_key: str, dataset_key: str) -> WorkflowStepSpec:
    definition = get_dataset_definition(dataset_key)
    return WorkflowStepSpec(
        step_key=step_key,
        job_key=definition.action_key("maintain"),
        display_name=definition.display_name,
        dataset_key=definition.dataset_key,
    )


WORKFLOW_SPEC_REGISTRY: dict[str, WorkflowSpec] = {
    "reference_data_refresh": WorkflowSpec(
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
        supports_schedule=True,
        supports_manual_run=True,
    ),
    "daily_market_close_sync": WorkflowSpec(
        key="daily_market_close_sync",
        display_name="每日收盘后同步",
        description="覆盖日线、日指标、资金流、榜单与基金/指数日线的每日同步工作流。",
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
        supports_schedule=True,
        supports_manual_run=True,
    ),
    "daily_moneyflow_sync": WorkflowSpec(
        key="daily_moneyflow_sync",
        display_name="每日资金流向同步",
        description="覆盖个股、概念、行业、板块和市场维度的资金流向每日同步工作流。",
        steps=(
            _dataset_workflow_step("moneyflow", "moneyflow"),
            _dataset_workflow_step("moneyflow_ths", "moneyflow_ths"),
            _dataset_workflow_step("moneyflow_dc", "moneyflow_dc"),
            _dataset_workflow_step("moneyflow_cnt_ths", "moneyflow_cnt_ths"),
            _dataset_workflow_step("moneyflow_ind_ths", "moneyflow_ind_ths"),
            _dataset_workflow_step("moneyflow_ind_dc", "moneyflow_ind_dc"),
            _dataset_workflow_step("moneyflow_mkt_dc", "moneyflow_mkt_dc"),
        ),
        supports_schedule=True,
        supports_manual_run=True,
    ),
    "board_reference_refresh": WorkflowSpec(
        key="board_reference_refresh",
        display_name="板块主数据刷新",
        description="刷新同花顺板块主数据与同花顺板块成分。",
        steps=(
            _dataset_workflow_step("ths_index", "ths_index"),
            _dataset_workflow_step("ths_member", "ths_member"),
        ),
        supports_schedule=True,
        supports_manual_run=True,
    ),
    "index_extension_backfill": WorkflowSpec(
        key="index_extension_backfill",
        display_name="指数扩展数据补齐",
        description="批量回补指数日线、周线、月线、日指标和成分权重。",
        steps=(
            _dataset_workflow_step("index_daily", "index_daily"),
            _dataset_workflow_step("index_weekly", "index_weekly"),
            _dataset_workflow_step("index_monthly", "index_monthly"),
            _dataset_workflow_step("index_daily_basic", "index_daily_basic"),
            _dataset_workflow_step("index_weight", "index_weight"),
        ),
        supports_manual_run=True,
    ),
    "index_kline_sync_pipeline": WorkflowSpec(
        key="index_kline_sync_pipeline",
        display_name="指数K线全链路同步",
        description="按日线→周线→月线→服务表补齐的顺序执行指数K线同步工作流。",
        supported_params=(START_DATE_PARAM, END_DATE_PARAM),
        steps=(
            _dataset_workflow_step("index_daily", "index_daily"),
            _dataset_workflow_step("index_weekly", "index_weekly"),
            _dataset_workflow_step("index_monthly", "index_monthly"),
            WorkflowStepSpec("rebuild_index_serving", "maintenance.rebuild_index_kline_serving", "补齐指数服务表"),
        ),
        supports_manual_run=True,
        supports_schedule=False,
    ),
}


DATASET_FRESHNESS_SPEC_REGISTRY: dict[str, DatasetFreshnessSpec] = {}


def validate_dataset_freshness_registry(
    specs: dict[str, DatasetFreshnessSpec],
    *,
    observed_model_registry: dict[str, type],
) -> list[str]:
    errors: list[str] = []
    missing_models: list[str] = []
    missing_columns: list[str] = []
    for resource_key, spec in sorted(specs.items()):
        if spec.observed_date_column is None:
            continue
        model = observed_model_registry.get(spec.target_table)
        if model is None:
            missing_models.append(resource_key)
            continue
        if not hasattr(model, spec.observed_date_column):
            missing_columns.append(f"{resource_key}({spec.target_table}.{spec.observed_date_column})")
    if missing_models:
        errors.append(f"Missing observed model mapping: {', '.join(missing_models)}")
    if missing_columns:
        errors.append(f"Missing observed date column on mapped model: {', '.join(missing_columns)}")
    return errors


for _definition in list_dataset_definitions():
    _resource = _definition.dataset_key
    _runtime_spec = DATASET_RUNTIME_REGISTRY[_resource]
    _observed_date_column = _definition.date_model.observed_field
    _spec = DatasetFreshnessSpec(
        dataset_key=_resource,
        resource_key=_resource,
        display_name=_definition.display_name,
        domain_key=_definition.domain.domain_key,
        domain_display_name=_definition.domain.domain_display_name,
        target_table=_runtime_spec.target_table,
        cadence=_definition.domain.cadence,  # type: ignore[arg-type]
        raw_table=_definition.storage.raw_table,
        observed_date_column=_observed_date_column,
        primary_action_key=_definition.action_key("maintain") if _definition.capabilities.get_action("maintain") else None,
    )
    DATASET_FRESHNESS_SPEC_REGISTRY[_resource] = _spec

_dataset_freshness_registry_errors = validate_dataset_freshness_registry(
    DATASET_FRESHNESS_SPEC_REGISTRY,
    observed_model_registry=OBSERVED_DATE_MODEL_REGISTRY,
)
if _dataset_freshness_registry_errors:
    raise RuntimeError("Invalid DATASET_FRESHNESS_SPEC_REGISTRY: " + "; ".join(_dataset_freshness_registry_errors))


def list_job_specs() -> list[JobSpec]:
    return [JOB_SPEC_REGISTRY[key] for key in sorted(JOB_SPEC_REGISTRY)]


def get_job_spec(key: str) -> JobSpec | None:
    return JOB_SPEC_REGISTRY.get(key)


def list_workflow_specs() -> list[WorkflowSpec]:
    return [WORKFLOW_SPEC_REGISTRY[key] for key in sorted(WORKFLOW_SPEC_REGISTRY)]


def get_workflow_spec(key: str) -> WorkflowSpec | None:
    return WORKFLOW_SPEC_REGISTRY.get(key)


def get_ops_spec(spec_type: str, spec_key: str) -> JobSpec | WorkflowSpec | None:
    if spec_type == "dataset_action":
        try:
            definition, _action = get_dataset_definition_by_action_key(spec_key)
            return definition  # type: ignore[return-value]
        except KeyError:
            return None
    if spec_type == "job":
        return get_job_spec(spec_key)
    if spec_type == "workflow":
        return get_workflow_spec(spec_key)
    return None


def get_ops_spec_display_name(spec_type: str, spec_key: str) -> str | None:
    if spec_type == "dataset_action":
        try:
            definition, action = get_dataset_definition_by_action_key(spec_key)
        except KeyError:
            return None
        return definition.action_display_name(action)
    spec = get_ops_spec(spec_type, spec_key)
    return spec.display_name if spec is not None else None


def get_ops_spec_target_display_name(spec_type: str, spec_key: str) -> str | None:
    if spec_type == "dataset_action":
        try:
            definition, _action = get_dataset_definition_by_action_key(spec_key)
            return definition.display_name
        except KeyError:
            return None
    spec = get_ops_spec(spec_type, spec_key)
    return spec.display_name if spec is not None else None


def ops_spec_supports_schedule(spec_type: str, spec_key: str) -> bool:
    if spec_type == "dataset_action":
        try:
            definition, action_name = get_dataset_definition_by_action_key(spec_key)
            action = definition.capabilities.get_action(action_name)
        except KeyError:
            return False
        return bool(action and action.schedule_enabled)
    spec = get_ops_spec(spec_type, spec_key)
    return bool(spec is not None and getattr(spec, "supports_schedule", False))


def list_dataset_freshness_specs() -> list[DatasetFreshnessSpec]:
    return [DATASET_FRESHNESS_SPEC_REGISTRY[key] for key in sorted(DATASET_FRESHNESS_SPEC_REGISTRY)]


def get_dataset_freshness_spec(resource_key: str) -> DatasetFreshnessSpec | None:
    return DATASET_FRESHNESS_SPEC_REGISTRY.get(resource_key)
