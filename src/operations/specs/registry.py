from __future__ import annotations

from src.operations.specs.dataset_freshness_spec import DatasetFreshnessSpec
from src.operations.specs.job_spec import JobSpec, ParameterSpec
from src.operations.specs.workflow_spec import WorkflowSpec, WorkflowStepSpec
from src.foundation.services.sync.registry import SYNC_SERVICE_REGISTRY


TRADE_DATE_PARAM = ParameterSpec(
    key="trade_date",
    display_name="交易日期",
    param_type="date",
    description="指定单个交易日执行增量同步。",
)
START_DATE_PARAM = ParameterSpec(
    key="start_date",
    display_name="开始日期",
    param_type="date",
    description="历史回补或区间同步的开始日期。",
)
END_DATE_PARAM = ParameterSpec(
    key="end_date",
    display_name="结束日期",
    param_type="date",
    description="历史回补或区间同步的结束日期。",
)
MONTH_PARAM = ParameterSpec(
    key="month",
    display_name="月份",
    param_type="month",
    description="指定单个月份执行同步，格式 YYYY-MM。",
)
START_MONTH_PARAM = ParameterSpec(
    key="start_month",
    display_name="开始月份",
    param_type="month",
    description="历史回补起始月份，格式 YYYY-MM。",
)
END_MONTH_PARAM = ParameterSpec(
    key="end_month",
    display_name="结束月份",
    param_type="month",
    description="历史回补结束月份，格式 YYYY-MM。",
)
EXCHANGE_PARAM = ParameterSpec(
    key="exchange",
    display_name="交易所",
    param_type="enum",
    description="用于交易日历或按交易日回补的交易所参数。",
    options=("SSE", "SZSE"),
)
ETF_EXCHANGE_PARAM = ParameterSpec(
    key="exchange",
    display_name="交易所",
    param_type="enum",
    description="用于 ETF 基本信息筛选交易所。",
    options=("SH", "SZ"),
    multi_value=True,
)
LIMIT_LIST_EXCHANGE_PARAM = ParameterSpec(
    key="exchange",
    display_name="交易所",
    param_type="enum",
    description="用于涨跌停和炸板数据筛选交易所。",
    options=("SH", "SZ", "BJ"),
    multi_value=True,
)
LIMIT_TYPE_PARAM = ParameterSpec(
    key="limit_type",
    display_name="涨跌停类型",
    param_type="enum",
    description="用于筛选涨停(U)、跌停(D)或炸板(Z)数据。",
    options=("U", "D", "Z"),
    multi_value=True,
)
LIMIT_LIST_THS_LIMIT_TYPE_PARAM = ParameterSpec(
    key="limit_type",
    display_name="榜单类型",
    param_type="enum",
    description="用于同花顺涨跌停榜单筛选榜单类型。",
    options=("涨停池", "连板池", "冲刺涨停", "炸板池", "跌停池"),
    multi_value=True,
)
LIMIT_LIST_THS_MARKET_PARAM = ParameterSpec(
    key="market",
    display_name="市场类型",
    param_type="enum",
    description="用于同花顺涨跌停榜单筛选市场类型。",
    options=("HS", "GEM", "STAR"),
    multi_value=True,
)
LIST_STATUS_PARAM = ParameterSpec(
    key="list_status",
    display_name="上市状态",
    param_type="enum",
    description="用于港股列表筛选上市状态。",
    options=("L", "D", "P"),
    multi_value=True,
)
ETF_LIST_STATUS_PARAM = ParameterSpec(
    key="list_status",
    display_name="上市状态",
    param_type="enum",
    description="用于 ETF 基本信息筛选上市状态。",
    options=("L", "D", "P"),
    multi_value=True,
)
CLASSIFY_PARAM = ParameterSpec(
    key="classify",
    display_name="分类",
    param_type="enum",
    description="用于美股列表筛选证券分类。",
    options=("ADR", "GDR", "EQT"),
    multi_value=True,
)
TS_CODE_PARAM = ParameterSpec(
    key="ts_code",
    display_name="证券代码",
    param_type="string",
    description="用于按单证券或单指数执行同步。",
)
INDEX_CODE_PARAM = ParameterSpec(
    key="index_code",
    display_name="指数代码",
    param_type="string",
    description="用于指数成分权重等按 index_code 执行的任务。",
)
CON_CODE_PARAM = ParameterSpec(
    key="con_code",
    display_name="板块代码",
    param_type="string",
    description="用于按板块代码或概念代码精确同步。",
)
THS_TYPE_PARAM = ParameterSpec(
    key="type",
    display_name="指数类型",
    param_type="string",
    description="用于区分同花顺概念或行业指数类型。",
)
IDX_TYPE_PARAM = ParameterSpec(
    key="idx_type",
    display_name="板块类型",
    param_type="string",
    description="用于区分东方财富板块类型。",
)
MARKET_PARAM = ParameterSpec(
    key="market",
    display_name="市场标识",
    param_type="enum",
    description="用于热榜类数据的市场过滤，例如 A股、港股或美股。",
    options=("A", "HK", "US"),
    multi_value=True,
)
THS_HOT_MARKET_PARAM = ParameterSpec(
    key="market",
    display_name="热榜类型",
    param_type="enum",
    description="同花顺热榜类型，可多选：热股、ETF、可转债、行业板块、概念板块、期货、港股、热基、美股。",
    options=("热股", "ETF", "可转债", "行业板块", "概念板块", "期货", "港股", "热基", "美股"),
    multi_value=True,
)
HOT_TYPE_PARAM = ParameterSpec(
    key="hot_type",
    display_name="热榜类型",
    param_type="string",
    description="用于东方财富热榜的榜单类型过滤。",
)
IS_NEW_PARAM = ParameterSpec(
    key="is_new",
    display_name="最新标记",
    param_type="enum",
    description="用于控制是否拉取日终最终版(Y)或小时级快照(N)热榜。",
    options=("Y", "N"),
)
DC_HOT_MARKET_PARAM = ParameterSpec(
    key="market",
    display_name="市场类型",
    param_type="enum",
    description="东方财富热榜市场类型，可多选：A股市场、ETF基金、港股市场、美股市场。",
    options=("A股市场", "ETF基金", "港股市场", "美股市场"),
    multi_value=True,
)
DC_HOT_TYPE_PARAM = ParameterSpec(
    key="hot_type",
    display_name="热点类型",
    param_type="enum",
    description="东方财富热榜榜单类型，可多选：人气榜、飙升榜。",
    options=("人气榜", "飙升榜"),
    multi_value=True,
)
TAG_PARAM = ParameterSpec(
    key="tag",
    display_name="榜单标签",
    param_type="enum",
    description="用于开盘啦榜单标签过滤，可多选：涨停、炸板、跌停、自然涨停、竞价。不传时接口默认返回涨停。",
    options=("涨停", "炸板", "跌停", "自然涨停", "竞价"),
    multi_value=True,
)
OFFSET_PARAM = ParameterSpec(
    key="offset",
    display_name="起始偏移",
    param_type="integer",
    description="用于分段回补时跳过前 N 个执行单元。",
)
LIMIT_PARAM = ParameterSpec(
    key="limit",
    display_name="处理上限",
    param_type="integer",
    description="用于限制单次回补的执行单元数量。",
)


DAILY_SYNC_RESOURCES = (
    "daily",
    "equity_price_restore_factor",
    "adj_factor",
    "daily_basic",
    "moneyflow",
    "limit_list_d",
    "top_list",
    "block_trade",
    "fund_daily",
    "fund_adj",
    "index_daily",
    "ths_daily",
    "dc_index",
    "dc_member",
    "dc_daily",
    "ths_hot",
    "dc_hot",
    "kpl_list",
    "kpl_concept_cons",
    "limit_list_ths",
    "limit_step",
    "limit_cpt_list",
    "broker_recommend",
)

SCHEDULED_FULL_REFRESH_RESOURCES = {
    "stock_basic",
    "hk_basic",
    "us_basic",
    "trade_cal",
    "etf_basic",
    "etf_index",
    "index_basic",
    "ths_index",
    "ths_member",
}

SECURITY_RANGE_RESOURCES = {
    "daily",
    "adj_factor",
    "index_daily",
    "index_daily_basic",
    "index_weekly",
    "index_monthly",
    "stk_period_bar_week",
    "stk_period_bar_month",
    "stk_period_bar_adj_week",
    "stk_period_bar_adj_month",
}

TRADE_DATE_RANGE_RESOURCES = {
    "equity_price_restore_factor",
    "daily_basic",
    "moneyflow",
    "top_list",
    "block_trade",
    "fund_adj",
    "fund_daily",
    "limit_list_d",
    "dc_member",
    "ths_hot",
    "dc_hot",
    "kpl_concept_cons",
    "limit_list_ths",
    "limit_step",
    "limit_cpt_list",
}

DIRECT_DATE_RANGE_RESOURCES = {
    "ths_daily",
    "dc_index",
    "dc_daily",
    "kpl_list",
}

CODE_ONLY_RESOURCES = {
    "dividend",
    "stk_holdernumber",
    "stock_basic",
    "index_basic",
    "ths_index",
    "ths_member",
}


def _service_target_table(resource: str) -> str:
    return SYNC_SERVICE_REGISTRY[resource].target_table


def _history_params_for_resource(resource: str) -> tuple[ParameterSpec, ...]:
    if resource == "trade_cal":
        return (START_DATE_PARAM, END_DATE_PARAM, EXCHANGE_PARAM)
    if resource == "hk_basic":
        return (LIST_STATUS_PARAM,)
    if resource == "us_basic":
        return (CLASSIFY_PARAM,)
    if resource == "index_weight":
        return (INDEX_CODE_PARAM, START_DATE_PARAM, END_DATE_PARAM)
    if resource == "ths_index":
        return (TS_CODE_PARAM, EXCHANGE_PARAM, THS_TYPE_PARAM)
    if resource == "ths_member":
        return (TS_CODE_PARAM, CON_CODE_PARAM)
    if resource in SECURITY_RANGE_RESOURCES:
        return (TS_CODE_PARAM, START_DATE_PARAM, END_DATE_PARAM)
    if resource == "dc_index":
        return (TS_CODE_PARAM, START_DATE_PARAM, END_DATE_PARAM, IDX_TYPE_PARAM)
    if resource == "dc_daily":
        return (TS_CODE_PARAM, START_DATE_PARAM, END_DATE_PARAM, IDX_TYPE_PARAM)
    if resource == "dc_member":
        return (TRADE_DATE_PARAM, TS_CODE_PARAM, CON_CODE_PARAM)
    if resource == "ths_hot":
        return (TRADE_DATE_PARAM, START_DATE_PARAM, END_DATE_PARAM, TS_CODE_PARAM, THS_HOT_MARKET_PARAM, IS_NEW_PARAM)
    if resource == "dc_hot":
        return (TRADE_DATE_PARAM, START_DATE_PARAM, END_DATE_PARAM, TS_CODE_PARAM, DC_HOT_MARKET_PARAM, DC_HOT_TYPE_PARAM, IS_NEW_PARAM)
    if resource == "limit_list_ths":
        return (TRADE_DATE_PARAM, START_DATE_PARAM, END_DATE_PARAM, LIMIT_LIST_THS_LIMIT_TYPE_PARAM, LIMIT_LIST_THS_MARKET_PARAM)
    if resource in {"limit_step", "limit_cpt_list"}:
        return (TRADE_DATE_PARAM, START_DATE_PARAM, END_DATE_PARAM)
    if resource == "kpl_list":
        return (TRADE_DATE_PARAM, START_DATE_PARAM, END_DATE_PARAM, TAG_PARAM)
    if resource == "kpl_concept_cons":
        return (TRADE_DATE_PARAM, TS_CODE_PARAM, CON_CODE_PARAM)
    if resource == "limit_list_d":
        return (TRADE_DATE_PARAM, START_DATE_PARAM, END_DATE_PARAM, LIMIT_TYPE_PARAM, LIMIT_LIST_EXCHANGE_PARAM)
    if resource in TRADE_DATE_RANGE_RESOURCES:
        return (START_DATE_PARAM, END_DATE_PARAM)
    if resource in CODE_ONLY_RESOURCES:
        return (TS_CODE_PARAM,) if resource in {"dividend", "stk_holdernumber"} else ()
    if resource == "etf_basic":
        return (ETF_LIST_STATUS_PARAM, ETF_EXCHANGE_PARAM)
    if resource == "etf_index":
        return ()
    if resource == "broker_recommend":
        return ()
    return ()


def _sync_history_job_spec(resource: str) -> JobSpec:
    schedule_enabled = resource in SCHEDULED_FULL_REFRESH_RESOURCES
    display_name = f"历史同步 / {resource}"
    return JobSpec(
        key=f"sync_history.{resource}",
        display_name=display_name,
        category="sync_history",
        description=f"执行资源 {resource} 的全量或定向历史同步。",
        strategy_type="full_refresh",
        executor_kind="sync_service",
        target_tables=(_service_target_table(resource),),
        supported_params=_history_params_for_resource(resource),
        supports_manual_run=True,
        supports_schedule=schedule_enabled,
        supports_retry=True,
    )


def _sync_daily_job_spec(resource: str) -> JobSpec:
    supported_params = (TRADE_DATE_PARAM,)
    if resource in {"ths_daily", "dc_index", "dc_daily"}:
        extras: tuple[ParameterSpec, ...] = (TS_CODE_PARAM,)
        if resource in {"dc_index", "dc_daily"}:
            extras = (TS_CODE_PARAM, IDX_TYPE_PARAM)
        supported_params = (TRADE_DATE_PARAM, *extras)
    elif resource == "ths_hot":
        supported_params = (TRADE_DATE_PARAM, TS_CODE_PARAM, THS_HOT_MARKET_PARAM, IS_NEW_PARAM)
    elif resource == "dc_hot":
        supported_params = (TRADE_DATE_PARAM, TS_CODE_PARAM, DC_HOT_MARKET_PARAM, DC_HOT_TYPE_PARAM, IS_NEW_PARAM)
    elif resource == "limit_list_ths":
        supported_params = (TRADE_DATE_PARAM, LIMIT_LIST_THS_LIMIT_TYPE_PARAM, LIMIT_LIST_THS_MARKET_PARAM)
    elif resource == "kpl_list":
        supported_params = (TRADE_DATE_PARAM, TAG_PARAM)
    elif resource == "kpl_concept_cons":
        supported_params = (TRADE_DATE_PARAM, TS_CODE_PARAM, CON_CODE_PARAM)
    elif resource == "limit_list_d":
        supported_params = (TRADE_DATE_PARAM, LIMIT_TYPE_PARAM, LIMIT_LIST_EXCHANGE_PARAM)
    elif resource == "dc_member":
        supported_params = (TRADE_DATE_PARAM, TS_CODE_PARAM, CON_CODE_PARAM)
    elif resource == "broker_recommend":
        supported_params = (MONTH_PARAM,)
    return JobSpec(
        key=f"sync_daily.{resource}",
        display_name=f"日常同步 / {resource}",
        category="sync_daily",
        description=f"针对资源 {resource} 执行按交易日增量同步。",
        strategy_type="incremental_by_date",
        executor_kind="sync_service",
        target_tables=(_service_target_table(resource),),
        supported_params=supported_params,
        supports_manual_run=True,
        supports_schedule=True,
        supports_retry=True,
    )


def _backfill_job_spec(
    *,
    prefix: str,
    resource: str,
    display_name: str,
    description: str,
    strategy_type: str,
    supported_params: tuple[ParameterSpec, ...],
) -> JobSpec:
    return JobSpec(
        key=f"{prefix}.{resource}",
        display_name=display_name,
        category=prefix,
        description=description,
        strategy_type=strategy_type,  # type: ignore[arg-type]
        executor_kind="history_backfill_service",
        target_tables=(_service_target_table(resource),),
        supported_params=supported_params,
        supports_manual_run=True,
        supports_schedule=False,
        supports_retry=True,
    )


JOB_SPEC_REGISTRY: dict[str, JobSpec] = {}

for _resource in sorted(SYNC_SERVICE_REGISTRY):
    JOB_SPEC_REGISTRY[f"sync_history.{_resource}"] = _sync_history_job_spec(_resource)

for _resource in DAILY_SYNC_RESOURCES:
    JOB_SPEC_REGISTRY[f"sync_daily.{_resource}"] = _sync_daily_job_spec(_resource)

JOB_SPEC_REGISTRY["backfill_trade_cal.trade_cal"] = JobSpec(
    key="backfill_trade_cal.trade_cal",
    display_name="交易日历回补 / trade_cal",
    category="backfill_trade_cal",
    description="按日期区间回补交易日历。",
    strategy_type="backfill_by_trade_date",
    executor_kind="history_backfill_service",
    target_tables=(_service_target_table("trade_cal"),),
    supported_params=(START_DATE_PARAM, END_DATE_PARAM, EXCHANGE_PARAM),
    supports_manual_run=True,
    supports_schedule=False,
    supports_retry=True,
)

for _resource in (
    "daily",
    "adj_factor",
    "stk_period_bar_week",
    "stk_period_bar_month",
    "stk_period_bar_adj_week",
    "stk_period_bar_adj_month",
):
    JOB_SPEC_REGISTRY[f"backfill_equity_series.{_resource}"] = _backfill_job_spec(
        prefix="backfill_equity_series",
        resource=_resource,
        display_name=f"股票纵向回补 / {_resource}",
        description=f"从股票代码池读取证券列表，按证券纵向回补资源 {_resource}。",
        strategy_type="backfill_by_security",
        supported_params=(START_DATE_PARAM, END_DATE_PARAM, OFFSET_PARAM, LIMIT_PARAM),
    )

for _resource in ("daily_basic", "moneyflow", "top_list", "block_trade", "limit_list_d", "ths_hot", "dc_hot", "kpl_concept_cons", "limit_list_ths", "limit_step", "limit_cpt_list"):
    _supported_params: tuple[ParameterSpec, ...] = (START_DATE_PARAM, END_DATE_PARAM, EXCHANGE_PARAM, OFFSET_PARAM, LIMIT_PARAM)
    if _resource == "limit_list_d":
        _supported_params = (
            START_DATE_PARAM,
            END_DATE_PARAM,
            LIMIT_TYPE_PARAM,
            LIMIT_LIST_EXCHANGE_PARAM,
            OFFSET_PARAM,
            LIMIT_PARAM,
        )
    elif _resource == "ths_hot":
        _supported_params = (
            START_DATE_PARAM,
            END_DATE_PARAM,
            EXCHANGE_PARAM,
            TS_CODE_PARAM,
            THS_HOT_MARKET_PARAM,
            IS_NEW_PARAM,
            OFFSET_PARAM,
            LIMIT_PARAM,
        )
    elif _resource == "dc_hot":
        _supported_params = (
            START_DATE_PARAM,
            END_DATE_PARAM,
            TS_CODE_PARAM,
            DC_HOT_MARKET_PARAM,
            DC_HOT_TYPE_PARAM,
            IS_NEW_PARAM,
            OFFSET_PARAM,
            LIMIT_PARAM,
        )
    elif _resource == "limit_list_ths":
        _supported_params = (
            START_DATE_PARAM,
            END_DATE_PARAM,
            LIMIT_LIST_THS_LIMIT_TYPE_PARAM,
            LIMIT_LIST_THS_MARKET_PARAM,
            OFFSET_PARAM,
            LIMIT_PARAM,
        )
    elif _resource in {"limit_step", "limit_cpt_list"}:
        _supported_params = (
            START_DATE_PARAM,
            END_DATE_PARAM,
            OFFSET_PARAM,
            LIMIT_PARAM,
        )
    elif _resource == "kpl_concept_cons":
        _supported_params = (
            START_DATE_PARAM,
            END_DATE_PARAM,
            EXCHANGE_PARAM,
            TS_CODE_PARAM,
            CON_CODE_PARAM,
            OFFSET_PARAM,
            LIMIT_PARAM,
        )
    JOB_SPEC_REGISTRY[f"backfill_by_trade_date.{_resource}"] = _backfill_job_spec(
        prefix="backfill_by_trade_date",
        resource=_resource,
        display_name=f"按交易日回补 / {_resource}",
        description=f"按开市日期区间回补资源 {_resource}。",
        strategy_type="backfill_by_trade_date",
        supported_params=_supported_params,
    )

JOB_SPEC_REGISTRY["backfill_by_trade_date.dc_member"] = _backfill_job_spec(
    prefix="backfill_by_trade_date",
    resource="dc_member",
    display_name="按交易日回补 / dc_member",
    description="按交易日区间回补东方财富板块成分。",
    strategy_type="backfill_by_trade_date",
    supported_params=(START_DATE_PARAM, END_DATE_PARAM, TS_CODE_PARAM, CON_CODE_PARAM),
)

for _resource in ("ths_daily", "dc_index", "dc_daily", "kpl_list"):
    _extra_params: tuple[ParameterSpec, ...] = (TS_CODE_PARAM,)
    if _resource in {"dc_index", "dc_daily"}:
        _extra_params = (TS_CODE_PARAM, IDX_TYPE_PARAM)
    elif _resource == "kpl_list":
        _extra_params = (TAG_PARAM, TRADE_DATE_PARAM)
    JOB_SPEC_REGISTRY[f"backfill_by_date_range.{_resource}"] = JobSpec(
        key=f"backfill_by_date_range.{_resource}",
        display_name=f"按日期区间回补 / {_resource}",
        category="backfill_by_date_range",
        description=f"直接按日期区间回补资源 {_resource}。",
        strategy_type="backfill_by_date_range",
        executor_kind="sync_service",
        target_tables=(_service_target_table(_resource),),
        supported_params=(START_DATE_PARAM, END_DATE_PARAM, *_extra_params),
        supports_manual_run=True,
        supports_schedule=False,
        supports_retry=True,
    )

for _resource in ("dividend", "stk_holdernumber"):
    JOB_SPEC_REGISTRY[f"backfill_low_frequency.{_resource}"] = _backfill_job_spec(
        prefix="backfill_low_frequency",
        resource=_resource,
        display_name=f"低频事件回补 / {_resource}",
        description=f"从股票代码池读取证券列表，回补资源 {_resource}。",
        strategy_type="backfill_low_frequency",
        supported_params=(OFFSET_PARAM, LIMIT_PARAM),
    )

JOB_SPEC_REGISTRY["backfill_fund_series.fund_daily"] = _backfill_job_spec(
    prefix="backfill_fund_series",
    resource="fund_daily",
    display_name="按交易日回补 / fund_daily",
    description="按交易日历逐日回补 ETF 日线行情（支持分页拉取）。",
    strategy_type="backfill_by_security",
    supported_params=(START_DATE_PARAM, END_DATE_PARAM, OFFSET_PARAM, LIMIT_PARAM),
)
JOB_SPEC_REGISTRY["backfill_fund_series.fund_adj"] = _backfill_job_spec(
    prefix="backfill_fund_series",
    resource="fund_adj",
    display_name="按交易日回补 / fund_adj",
    description="按交易日历逐日回补基金复权因子（支持分页拉取）。",
    strategy_type="backfill_by_security",
    supported_params=(START_DATE_PARAM, END_DATE_PARAM, OFFSET_PARAM, LIMIT_PARAM),
)

JOB_SPEC_REGISTRY["backfill_by_month.broker_recommend"] = _backfill_job_spec(
    prefix="backfill_by_month",
    resource="broker_recommend",
    display_name="按月份回补 / broker_recommend",
    description="按月份区间逐月回补券商每月荐股。",
    strategy_type="backfill_by_month",
    supported_params=(START_MONTH_PARAM, END_MONTH_PARAM, OFFSET_PARAM, LIMIT_PARAM),
)

for _resource in ("index_daily", "index_weekly", "index_monthly", "index_daily_basic", "index_weight"):
    JOB_SPEC_REGISTRY[f"backfill_index_series.{_resource}"] = _backfill_job_spec(
        prefix="backfill_index_series",
        resource=_resource,
        display_name=f"指数纵向回补 / {_resource}",
        description=f"从指数代码池读取指数列表，纵向回补资源 {_resource}。",
        strategy_type="backfill_by_security",
        supported_params=(START_DATE_PARAM, END_DATE_PARAM, OFFSET_PARAM, LIMIT_PARAM),
    )

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
    target_tables=("core.index_weekly_serving", "core.index_monthly_serving"),
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
            WorkflowStepSpec("stock_basic", "sync_history.stock_basic", "股票主数据"),
            WorkflowStepSpec("trade_cal", "sync_history.trade_cal", "交易日历"),
            WorkflowStepSpec("etf_basic", "sync_history.etf_basic", "ETF 基本信息"),
            WorkflowStepSpec("etf_index", "sync_history.etf_index", "ETF 基准指数列表"),
            WorkflowStepSpec("index_basic", "sync_history.index_basic", "指数基本信息"),
            WorkflowStepSpec("hk_basic", "sync_history.hk_basic", "港股列表"),
            WorkflowStepSpec("us_basic", "sync_history.us_basic", "美股列表"),
        ),
        supports_schedule=True,
        supports_manual_run=True,
    ),
    "daily_market_close_sync": WorkflowSpec(
        key="daily_market_close_sync",
        display_name="每日收盘后同步",
        description="覆盖日线、日指标、资金流、榜单与基金/指数日线的每日同步工作流。",
        steps=(
            WorkflowStepSpec("daily", "sync_daily.daily", "股票日线"),
            WorkflowStepSpec("equity_price_restore_factor", "sync_daily.equity_price_restore_factor", "价格还原因子"),
            WorkflowStepSpec("adj_factor", "sync_daily.adj_factor", "复权因子"),
            WorkflowStepSpec("daily_basic", "sync_daily.daily_basic", "股票日指标"),
            WorkflowStepSpec("moneyflow", "sync_daily.moneyflow", "资金流"),
            WorkflowStepSpec("limit_list", "sync_daily.limit_list_d", "涨跌停榜"),
            WorkflowStepSpec("top_list", "sync_daily.top_list", "龙虎榜"),
            WorkflowStepSpec("block_trade", "sync_daily.block_trade", "大宗交易"),
            WorkflowStepSpec("fund_daily", "sync_daily.fund_daily", "基金日线"),
            WorkflowStepSpec("fund_adj", "sync_daily.fund_adj", "基金复权因子"),
            WorkflowStepSpec("index_daily", "sync_daily.index_daily", "指数日线"),
            WorkflowStepSpec("ths_daily", "sync_daily.ths_daily", "同花顺板块行情"),
            WorkflowStepSpec("dc_index", "sync_daily.dc_index", "东方财富概念板块"),
            WorkflowStepSpec("dc_member", "sync_daily.dc_member", "东方财富板块成分"),
            WorkflowStepSpec("dc_daily", "sync_daily.dc_daily", "东方财富板块行情"),
            WorkflowStepSpec("ths_hot", "sync_daily.ths_hot", "同花顺热榜"),
            WorkflowStepSpec("dc_hot", "sync_daily.dc_hot", "东方财富热榜"),
            WorkflowStepSpec("kpl_list", "sync_daily.kpl_list", "开盘啦榜单"),
            WorkflowStepSpec("limit_list_ths", "sync_daily.limit_list_ths", "同花顺涨跌停榜单"),
            WorkflowStepSpec("limit_step", "sync_daily.limit_step", "涨停天梯"),
            WorkflowStepSpec("limit_cpt_list", "sync_daily.limit_cpt_list", "最强板块统计"),
            WorkflowStepSpec("kpl_concept_cons", "sync_daily.kpl_concept_cons", "开盘啦题材成分"),
        ),
        default_schedule_policy="trading_day_close",
        supports_schedule=True,
        supports_manual_run=True,
    ),
    "board_reference_refresh": WorkflowSpec(
        key="board_reference_refresh",
        display_name="板块主数据刷新",
        description="刷新同花顺板块主数据与同花顺板块成分。",
        steps=(
            WorkflowStepSpec("ths_index", "sync_history.ths_index", "同花顺概念和行业指数"),
            WorkflowStepSpec("ths_member", "sync_history.ths_member", "同花顺板块成分"),
        ),
        supports_schedule=True,
        supports_manual_run=True,
    ),
    "index_extension_backfill": WorkflowSpec(
        key="index_extension_backfill",
        display_name="指数扩展数据补齐",
        description="批量回补指数日线、周线、月线、日指标和成分权重。",
        steps=(
            WorkflowStepSpec("index_daily", "backfill_index_series.index_daily", "指数日线"),
            WorkflowStepSpec("index_weekly", "backfill_index_series.index_weekly", "指数周线"),
            WorkflowStepSpec("index_monthly", "backfill_index_series.index_monthly", "指数月线"),
            WorkflowStepSpec("index_daily_basic", "backfill_index_series.index_daily_basic", "指数日指标"),
            WorkflowStepSpec("index_weight", "backfill_index_series.index_weight", "指数权重"),
        ),
        supports_manual_run=True,
    ),
    "index_kline_sync_pipeline": WorkflowSpec(
        key="index_kline_sync_pipeline",
        display_name="指数K线全链路同步",
        description="按日线→周线→月线→服务表补齐的顺序执行指数K线同步工作流。",
        supported_params=(START_DATE_PARAM, END_DATE_PARAM),
        steps=(
            WorkflowStepSpec("sync_index_daily", "backfill_index_series.index_daily", "同步指数日线"),
            WorkflowStepSpec("sync_index_weekly", "backfill_index_series.index_weekly", "同步指数周线"),
            WorkflowStepSpec("sync_index_monthly", "backfill_index_series.index_monthly", "同步指数月线"),
            WorkflowStepSpec("rebuild_index_serving", "maintenance.rebuild_index_kline_serving", "补齐指数服务表"),
        ),
        supports_manual_run=True,
        supports_schedule=False,
    ),
}


DATASET_FRESHNESS_METADATA: dict[str, tuple[str, str, str, str, str | None]] = {
    "stock_basic": ("股票主数据", "reference_data", "基础主数据", "reference", None),
    "hk_basic": ("港股列表", "reference_data", "基础主数据", "reference", None),
    "us_basic": ("美股列表", "reference_data", "基础主数据", "reference", None),
    "trade_cal": ("交易日历", "reference_data", "基础主数据", "reference", "trade_date"),
    "etf_basic": ("ETF 基本信息", "reference_data", "基础主数据", "reference", None),
    "etf_index": ("ETF 基准指数列表", "reference_data", "基础主数据", "reference", None),
    "broker_recommend": ("券商每月荐股", "reference_data", "基础主数据", "reference", None),
    "index_basic": ("指数主数据", "reference_data", "基础主数据", "reference", None),
    "daily": ("股票日线", "equity", "股票", "daily", "trade_date"),
    "equity_price_restore_factor": ("价格还原因子", "equity", "股票", "daily", "trade_date"),
    "adj_factor": ("复权因子", "equity", "股票", "daily", "trade_date"),
    "daily_basic": ("股票日指标", "equity", "股票", "daily", "trade_date"),
    "moneyflow": ("资金流", "equity", "股票", "daily", "trade_date"),
    "top_list": ("龙虎榜", "equity", "股票", "daily", "trade_date"),
    "block_trade": ("大宗交易", "equity", "股票", "daily", "trade_date"),
    "limit_list_d": ("涨跌停榜", "equity", "股票", "daily", "trade_date"),
    "stk_period_bar_week": ("股票周线", "equity", "股票", "weekly", "trade_date"),
    "stk_period_bar_month": ("股票月线", "equity", "股票", "monthly", "trade_date"),
    "stk_period_bar_adj_week": ("股票复权周线", "equity", "股票", "weekly", "trade_date"),
    "stk_period_bar_adj_month": ("股票复权月线", "equity", "股票", "monthly", "trade_date"),
    "fund_daily": ("基金日线", "fund", "ETF/Fund", "daily", "trade_date"),
    "fund_adj": ("基金复权因子", "fund", "ETF/Fund", "daily", "trade_date"),
    "index_daily": ("指数日线", "index", "指数", "daily", "trade_date"),
    "index_weekly": ("指数周线", "index", "指数", "weekly", "trade_date"),
    "index_monthly": ("指数月线", "index", "指数", "monthly", "trade_date"),
    "index_daily_basic": ("指数日指标", "index", "指数", "daily", "trade_date"),
    "index_weight": ("指数成分权重", "index", "指数", "monthly", "trade_date"),
    "ths_index": ("同花顺概念和行业指数", "board", "板块", "reference", None),
    "ths_member": ("同花顺板块成分", "board", "板块", "reference", None),
    "ths_daily": ("同花顺板块行情", "board", "板块", "daily", "trade_date"),
    "dc_index": ("东方财富概念板块", "board", "板块", "daily", "trade_date"),
    "dc_member": ("东方财富板块成分", "board", "板块", "daily", "trade_date"),
    "dc_daily": ("东方财富板块行情", "board", "板块", "daily", "trade_date"),
    "ths_hot": ("同花顺热榜", "ranking", "榜单", "daily", "trade_date"),
    "dc_hot": ("东方财富热榜", "ranking", "榜单", "daily", "trade_date"),
    "kpl_list": ("开盘啦榜单", "ranking", "榜单", "daily", "trade_date"),
    "limit_list_ths": ("同花顺涨跌停榜单", "ranking", "榜单", "daily", "trade_date"),
    "limit_step": ("涨停天梯", "ranking", "榜单", "daily", "trade_date"),
    "limit_cpt_list": ("最强板块统计", "ranking", "榜单", "daily", "trade_date"),
    "kpl_concept_cons": ("开盘啦题材成分", "board", "板块", "daily", "trade_date"),
    "dividend": ("分红送转", "event", "低频事件", "event", None),
    "stk_holdernumber": ("股东户数", "event", "低频事件", "event", None),
}


DATASET_FRESHNESS_SPEC_REGISTRY: dict[str, DatasetFreshnessSpec] = {}
DATASET_FRESHNESS_BY_JOB_NAME: dict[str, DatasetFreshnessSpec] = {}


def _primary_execution_spec_key_for_resource(resource: str) -> str | None:
    sync_daily_key = f"sync_daily.{resource}"
    if sync_daily_key in JOB_SPEC_REGISTRY:
        return sync_daily_key
    sync_history_key = f"sync_history.{resource}"
    if sync_history_key in JOB_SPEC_REGISTRY:
        return sync_history_key
    return None

for _resource, _service_cls in SYNC_SERVICE_REGISTRY.items():
    if _resource not in DATASET_FRESHNESS_METADATA:
        continue
    _display_name, _domain_key, _domain_display_name, _cadence, _observed_date_column = DATASET_FRESHNESS_METADATA[_resource]
    _spec = DatasetFreshnessSpec(
        dataset_key=_resource,
        resource_key=_resource,
        job_name=_service_cls.job_name,
        display_name=_display_name,
        domain_key=_domain_key,
        domain_display_name=_domain_display_name,
        target_table=_service_cls.target_table,
        cadence=_cadence,  # type: ignore[arg-type]
        observed_date_column=_observed_date_column,
        primary_execution_spec_key=_primary_execution_spec_key_for_resource(_resource),
    )
    DATASET_FRESHNESS_SPEC_REGISTRY[_resource] = _spec
    DATASET_FRESHNESS_BY_JOB_NAME[_spec.job_name] = _spec


def list_job_specs() -> list[JobSpec]:
    return [JOB_SPEC_REGISTRY[key] for key in sorted(JOB_SPEC_REGISTRY)]


def get_job_spec(key: str) -> JobSpec | None:
    return JOB_SPEC_REGISTRY.get(key)


def list_workflow_specs() -> list[WorkflowSpec]:
    return [WORKFLOW_SPEC_REGISTRY[key] for key in sorted(WORKFLOW_SPEC_REGISTRY)]


def get_workflow_spec(key: str) -> WorkflowSpec | None:
    return WORKFLOW_SPEC_REGISTRY.get(key)


def get_ops_spec(spec_type: str, spec_key: str) -> JobSpec | WorkflowSpec | None:
    if spec_type == "job":
        return get_job_spec(spec_key)
    if spec_type == "workflow":
        return get_workflow_spec(spec_key)
    return None


def get_ops_spec_display_name(spec_type: str, spec_key: str) -> str | None:
    spec = get_ops_spec(spec_type, spec_key)
    return spec.display_name if spec is not None else None


def ops_spec_supports_schedule(spec_type: str, spec_key: str) -> bool:
    spec = get_ops_spec(spec_type, spec_key)
    return bool(spec is not None and getattr(spec, "supports_schedule", False))


def list_dataset_freshness_specs() -> list[DatasetFreshnessSpec]:
    return [DATASET_FRESHNESS_SPEC_REGISTRY[key] for key in sorted(DATASET_FRESHNESS_SPEC_REGISTRY)]


def get_dataset_freshness_spec(resource_key: str) -> DatasetFreshnessSpec | None:
    return DATASET_FRESHNESS_SPEC_REGISTRY.get(resource_key)


def get_dataset_freshness_spec_by_job_name(job_name: str) -> DatasetFreshnessSpec | None:
    return DATASET_FRESHNESS_BY_JOB_NAME.get(job_name)
