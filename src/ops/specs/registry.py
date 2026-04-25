from __future__ import annotations

from src.ops.specs.dataset_freshness_spec import DatasetFreshnessSpec
from src.ops.specs.job_spec import JobSpec, ParameterSpec
from src.ops.specs.observed_dataset_registry import OBSERVED_DATE_MODEL_REGISTRY
from src.ops.specs.workflow_spec import WorkflowSpec, WorkflowStepSpec
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.runtime_registry import SYNC_SERVICE_REGISTRY


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


WORKFLOW_SPEC_REGISTRY: dict[str, WorkflowSpec] = {
    "reference_data_refresh": WorkflowSpec(
        key="reference_data_refresh",
        display_name="基础主数据刷新",
        description="刷新股票、交易日历、ETF 与指数基础信息。",
        steps=(
            WorkflowStepSpec("stock_basic", "stock_basic.maintain", "股票主数据", dataset_key="stock_basic"),
            WorkflowStepSpec("trade_cal", "trade_cal.maintain", "交易日历", dataset_key="trade_cal"),
            WorkflowStepSpec("etf_basic", "etf_basic.maintain", "ETF 基本信息", dataset_key="etf_basic"),
            WorkflowStepSpec("etf_index", "etf_index.maintain", "ETF 基准指数列表", dataset_key="etf_index"),
            WorkflowStepSpec("index_basic", "index_basic.maintain", "指数基本信息", dataset_key="index_basic"),
            WorkflowStepSpec("hk_basic", "hk_basic.maintain", "港股列表", dataset_key="hk_basic"),
        ),
        supports_schedule=True,
        supports_manual_run=True,
    ),
    "daily_market_close_sync": WorkflowSpec(
        key="daily_market_close_sync",
        display_name="每日收盘后同步",
        description="覆盖日线、日指标、资金流、榜单与基金/指数日线的每日同步工作流。",
        steps=(
            WorkflowStepSpec("daily", "daily.maintain", "股票日线", dataset_key="daily"),
            WorkflowStepSpec("adj_factor", "adj_factor.maintain", "复权因子", dataset_key="adj_factor"),
            WorkflowStepSpec("daily_basic", "daily_basic.maintain", "股票日指标", dataset_key="daily_basic"),
            WorkflowStepSpec("cyq_perf", "cyq_perf.maintain", "每日筹码及胜率", dataset_key="cyq_perf"),
            WorkflowStepSpec("stk_factor_pro", "stk_factor_pro.maintain", "股票技术面因子(专业版)", dataset_key="stk_factor_pro"),
            WorkflowStepSpec("margin", "margin.maintain", "融资融券交易汇总", dataset_key="margin"),
            WorkflowStepSpec("stk_limit", "stk_limit.maintain", "每日涨跌停价格", dataset_key="stk_limit"),
            WorkflowStepSpec("stock_st", "stock_st.maintain", "ST股票列表", dataset_key="stock_st"),
            WorkflowStepSpec("limit_list", "limit_list_d.maintain", "涨跌停榜", dataset_key="limit_list_d"),
            WorkflowStepSpec("suspend_d", "suspend_d.maintain", "每日停复牌信息", dataset_key="suspend_d"),
            WorkflowStepSpec("top_list", "top_list.maintain", "龙虎榜", dataset_key="top_list"),
            WorkflowStepSpec("block_trade", "block_trade.maintain", "大宗交易", dataset_key="block_trade"),
            WorkflowStepSpec("fund_daily", "fund_daily.maintain", "基金日线", dataset_key="fund_daily"),
            WorkflowStepSpec("fund_adj", "fund_adj.maintain", "基金复权因子", dataset_key="fund_adj"),
            WorkflowStepSpec("index_daily", "index_daily.maintain", "指数日线", dataset_key="index_daily"),
            WorkflowStepSpec("ths_daily", "ths_daily.maintain", "同花顺板块行情", dataset_key="ths_daily"),
            WorkflowStepSpec("dc_index", "dc_index.maintain", "东方财富概念板块", dataset_key="dc_index"),
            WorkflowStepSpec("dc_member", "dc_member.maintain", "东方财富板块成分", dataset_key="dc_member"),
            WorkflowStepSpec("dc_daily", "dc_daily.maintain", "东方财富板块行情", dataset_key="dc_daily"),
            WorkflowStepSpec("ths_hot", "ths_hot.maintain", "同花顺热榜", dataset_key="ths_hot"),
            WorkflowStepSpec("dc_hot", "dc_hot.maintain", "东方财富热榜", dataset_key="dc_hot"),
            WorkflowStepSpec("kpl_list", "kpl_list.maintain", "开盘啦榜单", dataset_key="kpl_list"),
            WorkflowStepSpec("limit_list_ths", "limit_list_ths.maintain", "同花顺涨跌停榜单", dataset_key="limit_list_ths"),
            WorkflowStepSpec("limit_step", "limit_step.maintain", "涨停天梯", dataset_key="limit_step"),
            WorkflowStepSpec("limit_cpt_list", "limit_cpt_list.maintain", "最强板块统计", dataset_key="limit_cpt_list"),
            WorkflowStepSpec("kpl_concept_cons", "kpl_concept_cons.maintain", "开盘啦题材成分", dataset_key="kpl_concept_cons"),
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
            WorkflowStepSpec("moneyflow", "moneyflow.maintain", "资金流向（基础）", dataset_key="moneyflow"),
            WorkflowStepSpec("moneyflow_ths", "moneyflow_ths.maintain", "个股资金流向（同花顺）", dataset_key="moneyflow_ths"),
            WorkflowStepSpec("moneyflow_dc", "moneyflow_dc.maintain", "个股资金流向（东方财富）", dataset_key="moneyflow_dc"),
            WorkflowStepSpec("moneyflow_cnt_ths", "moneyflow_cnt_ths.maintain", "概念板块资金流向（同花顺）", dataset_key="moneyflow_cnt_ths"),
            WorkflowStepSpec("moneyflow_ind_ths", "moneyflow_ind_ths.maintain", "行业资金流向（同花顺）", dataset_key="moneyflow_ind_ths"),
            WorkflowStepSpec("moneyflow_ind_dc", "moneyflow_ind_dc.maintain", "板块资金流向（东方财富）", dataset_key="moneyflow_ind_dc"),
            WorkflowStepSpec("moneyflow_mkt_dc", "moneyflow_mkt_dc.maintain", "市场资金流向（东方财富）", dataset_key="moneyflow_mkt_dc"),
        ),
        supports_schedule=True,
        supports_manual_run=True,
    ),
    "board_reference_refresh": WorkflowSpec(
        key="board_reference_refresh",
        display_name="板块主数据刷新",
        description="刷新同花顺板块主数据与同花顺板块成分。",
        steps=(
            WorkflowStepSpec("ths_index", "ths_index.maintain", "同花顺概念和行业指数", dataset_key="ths_index"),
            WorkflowStepSpec("ths_member", "ths_member.maintain", "同花顺板块成分", dataset_key="ths_member"),
        ),
        supports_schedule=True,
        supports_manual_run=True,
    ),
    "index_extension_backfill": WorkflowSpec(
        key="index_extension_backfill",
        display_name="指数扩展数据补齐",
        description="批量回补指数日线、周线、月线、日指标和成分权重。",
        steps=(
            WorkflowStepSpec("index_daily", "index_daily.maintain", "指数日线", dataset_key="index_daily"),
            WorkflowStepSpec("index_weekly", "index_weekly.maintain", "指数周线", dataset_key="index_weekly"),
            WorkflowStepSpec("index_monthly", "index_monthly.maintain", "指数月线", dataset_key="index_monthly"),
            WorkflowStepSpec("index_daily_basic", "index_daily_basic.maintain", "指数日指标", dataset_key="index_daily_basic"),
            WorkflowStepSpec("index_weight", "index_weight.maintain", "指数权重", dataset_key="index_weight"),
        ),
        supports_manual_run=True,
    ),
    "index_kline_sync_pipeline": WorkflowSpec(
        key="index_kline_sync_pipeline",
        display_name="指数K线全链路同步",
        description="按日线→周线→月线→服务表补齐的顺序执行指数K线同步工作流。",
        supported_params=(START_DATE_PARAM, END_DATE_PARAM),
        steps=(
            WorkflowStepSpec("sync_index_daily", "index_daily.maintain", "同步指数日线", dataset_key="index_daily"),
            WorkflowStepSpec("sync_index_weekly", "index_weekly.maintain", "同步指数周线", dataset_key="index_weekly"),
            WorkflowStepSpec("sync_index_monthly", "index_monthly.maintain", "同步指数月线", dataset_key="index_monthly"),
            WorkflowStepSpec("rebuild_index_serving", "maintenance.rebuild_index_kline_serving", "补齐指数服务表"),
        ),
        supports_manual_run=True,
        supports_schedule=False,
    ),
}


DATASET_FRESHNESS_METADATA: dict[str, tuple[str, str, str, str]] = {
    "biying_equity_daily": ("BIYING 股票日线", "equity", "股票", "daily"),
    "biying_moneyflow": ("BIYING 资金流向", "equity", "股票", "daily"),
    "stock_basic": ("股票主数据", "reference_data", "基础主数据", "reference"),
    "hk_basic": ("港股列表", "reference_data", "基础主数据", "reference"),
    "us_basic": ("美股列表", "reference_data", "基础主数据", "reference"),
    "trade_cal": ("交易日历", "reference_data", "基础主数据", "reference"),
    "etf_basic": ("ETF 基本信息", "reference_data", "基础主数据", "reference"),
    "etf_index": ("ETF 基准指数列表", "reference_data", "基础主数据", "reference"),
    "broker_recommend": ("券商每月荐股", "reference_data", "基础主数据", "monthly"),
    "index_basic": ("指数主数据", "reference_data", "基础主数据", "reference"),
    "daily": ("股票日线", "equity", "股票", "daily"),
    "adj_factor": ("复权因子", "equity", "股票", "daily"),
    "daily_basic": ("股票日指标", "equity", "股票", "daily"),
    "cyq_perf": ("每日筹码及胜率", "equity", "股票", "daily"),
    "stk_factor_pro": ("股票技术面因子(专业版)", "equity", "股票", "daily"),
    "moneyflow": ("资金流向（基础）", "moneyflow", "资金流向", "daily"),
    "moneyflow_ths": ("个股资金流向（同花顺）", "moneyflow", "资金流向", "daily"),
    "moneyflow_dc": ("个股资金流向（东方财富）", "moneyflow", "资金流向", "daily"),
    "moneyflow_cnt_ths": ("概念板块资金流向（同花顺）", "moneyflow", "资金流向", "daily"),
    "moneyflow_ind_ths": ("行业资金流向（同花顺）", "moneyflow", "资金流向", "daily"),
    "moneyflow_ind_dc": ("板块资金流向（东方财富）", "moneyflow", "资金流向", "daily"),
    "moneyflow_mkt_dc": ("市场资金流向（东方财富）", "moneyflow", "资金流向", "daily"),
    "margin": ("融资融券交易汇总", "equity", "股票", "daily"),
    "top_list": ("龙虎榜", "equity", "股票", "daily"),
    "block_trade": ("大宗交易", "equity", "股票", "daily"),
    "limit_list_d": ("涨跌停榜", "equity", "股票", "daily"),
    "stk_limit": ("每日涨跌停价格", "equity", "股票", "daily"),
    "stock_st": ("ST股票列表", "equity", "股票", "daily"),
    "stk_nineturn": ("神奇九转指标", "equity", "股票", "daily"),
    "stk_mins": ("股票历史分钟行情", "equity", "股票", "daily"),
    "suspend_d": ("每日停复牌信息", "equity", "股票", "daily"),
    "stk_period_bar_week": ("股票周线", "equity", "股票", "weekly"),
    "stk_period_bar_month": ("股票月线", "equity", "股票", "monthly"),
    "stk_period_bar_adj_week": ("股票复权周线", "equity", "股票", "weekly"),
    "stk_period_bar_adj_month": ("股票复权月线", "equity", "股票", "monthly"),
    "fund_daily": ("基金日线", "fund", "ETF/Fund", "daily"),
    "fund_adj": ("基金复权因子", "fund", "ETF/Fund", "daily"),
    "index_daily": ("指数日线", "index", "指数", "daily"),
    "index_weekly": ("指数周线", "index", "指数", "weekly"),
    "index_monthly": ("指数月线", "index", "指数", "monthly"),
    "index_daily_basic": ("指数日指标", "index", "指数", "daily"),
    "index_weight": ("指数成分权重", "index", "指数", "monthly"),
    "ths_index": ("同花顺概念和行业指数", "board", "板块", "reference"),
    "ths_member": ("同花顺板块成分", "board", "板块", "reference"),
    "ths_daily": ("同花顺板块行情", "board", "板块", "daily"),
    "dc_index": ("东方财富概念板块", "board", "板块", "daily"),
    "dc_member": ("东方财富板块成分", "board", "板块", "daily"),
    "dc_daily": ("东方财富板块行情", "board", "板块", "daily"),
    "ths_hot": ("同花顺热榜", "ranking", "榜单", "daily"),
    "dc_hot": ("东方财富热榜", "ranking", "榜单", "daily"),
    "kpl_list": ("开盘啦榜单", "ranking", "榜单", "daily"),
    "limit_list_ths": ("同花顺涨跌停榜单", "ranking", "榜单", "daily"),
    "limit_step": ("涨停天梯", "ranking", "榜单", "daily"),
    "limit_cpt_list": ("最强板块统计", "ranking", "榜单", "daily"),
    "kpl_concept_cons": ("开盘啦题材成分", "board", "板块", "daily"),
    "dividend": ("分红送转", "event", "低频事件", "event"),
    "stk_holdernumber": ("股东户数", "event", "低频事件", "event"),
}


DATASET_FRESHNESS_SPEC_REGISTRY: dict[str, DatasetFreshnessSpec] = {}
DATASET_FRESHNESS_BY_JOB_NAME: dict[str, DatasetFreshnessSpec] = {}


def _primary_execution_spec_key_for_resource(resource: str) -> str | None:
    try:
        get_dataset_definition(resource)
    except KeyError:
        return None
    return f"{resource}.maintain"


def _raw_table_for_resource(resource: str) -> str | None:
    if resource == "stk_period_bar_week" or resource == "stk_period_bar_month":
        return "raw_tushare.stk_period_bar"
    if resource == "stk_period_bar_adj_week" or resource == "stk_period_bar_adj_month":
        return "raw_tushare.stk_period_bar_adj"
    if resource == "index_weekly":
        return "raw_tushare.index_weekly_bar"
    if resource == "index_monthly":
        return "raw_tushare.index_monthly_bar"
    if resource == "limit_list_d":
        return "raw_tushare.limit_list"
    if resource == "stk_holdernumber":
        return "raw_tushare.holdernumber"
    if resource.startswith("biying_"):
        return f"raw_biying.{resource.removeprefix('biying_')}"
    return f"raw_tushare.{resource}"


def find_missing_freshness_metadata_resources(
    *,
    sync_resources: list[str] | tuple[str, ...],
    metadata: dict[str, tuple[str, str, str, str]],
) -> list[str]:
    return sorted(resource for resource in sync_resources if resource not in metadata)


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


_missing_freshness_metadata = find_missing_freshness_metadata_resources(
    sync_resources=tuple(sorted(SYNC_SERVICE_REGISTRY)),
    metadata=DATASET_FRESHNESS_METADATA,
)
if _missing_freshness_metadata:
    joined_missing = ", ".join(_missing_freshness_metadata)
    raise RuntimeError(f"Missing DATASET_FRESHNESS_METADATA entries for sync resources: {joined_missing}")

for _resource, _service_cls in SYNC_SERVICE_REGISTRY.items():
    _display_name, _domain_key, _domain_display_name, _cadence = DATASET_FRESHNESS_METADATA[_resource]
    _observed_date_column = get_sync_v2_contract(_resource).date_model.observed_field
    _spec = DatasetFreshnessSpec(
        dataset_key=_resource,
        resource_key=_resource,
        job_name=_service_cls.job_name,
        display_name=_display_name,
        domain_key=_domain_key,
        domain_display_name=_domain_display_name,
        target_table=_service_cls.target_table,
        cadence=_cadence,  # type: ignore[arg-type]
        raw_table=_raw_table_for_resource(_resource),
        observed_date_column=_observed_date_column,
        primary_execution_spec_key=_primary_execution_spec_key_for_resource(_resource),
    )
    DATASET_FRESHNESS_SPEC_REGISTRY[_resource] = _spec
    DATASET_FRESHNESS_BY_JOB_NAME[_spec.job_name] = _spec

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
        dataset_key = _dataset_key_from_action_spec_key(spec_key)
        try:
            return get_dataset_definition(dataset_key)  # type: ignore[return-value]
        except KeyError:
            return None
    if spec_type == "job":
        return get_job_spec(spec_key)
    if spec_type == "workflow":
        return get_workflow_spec(spec_key)
    return None


def get_ops_spec_display_name(spec_type: str, spec_key: str) -> str | None:
    if spec_type == "dataset_action":
        dataset_key = _dataset_key_from_action_spec_key(spec_key)
        try:
            definition = get_dataset_definition(dataset_key)
        except KeyError:
            return None
        return f"维护{definition.display_name}"
    spec = get_ops_spec(spec_type, spec_key)
    return spec.display_name if spec is not None else None


def ops_spec_supports_schedule(spec_type: str, spec_key: str) -> bool:
    if spec_type == "dataset_action":
        dataset_key = _dataset_key_from_action_spec_key(spec_key)
        try:
            action = get_dataset_definition(dataset_key).capabilities.get_action("maintain")
        except KeyError:
            return False
        return bool(action and action.schedule_enabled)
    spec = get_ops_spec(spec_type, spec_key)
    return bool(spec is not None and getattr(spec, "supports_schedule", False))


def _dataset_key_from_action_spec_key(spec_key: str) -> str:
    return spec_key.rsplit(".", 1)[0] if spec_key.endswith(".maintain") else spec_key


def list_dataset_freshness_specs() -> list[DatasetFreshnessSpec]:
    return [DATASET_FRESHNESS_SPEC_REGISTRY[key] for key in sorted(DATASET_FRESHNESS_SPEC_REGISTRY)]


def get_dataset_freshness_spec(resource_key: str) -> DatasetFreshnessSpec | None:
    return DATASET_FRESHNESS_SPEC_REGISTRY.get(resource_key)


def get_dataset_freshness_spec_by_job_name(job_name: str) -> DatasetFreshnessSpec | None:
    return DATASET_FRESHNESS_BY_JOB_NAME.get(job_name)
