from __future__ import annotations

from src.foundation.config.settings import get_settings
from src.foundation.services.sync_v2.fields import (
    ADJ_FACTOR_FIELDS,
    BIYING_EQUITY_DAILY_FIELDS,
    BLOCK_TRADE_FIELDS,
    BROKER_RECOMMEND_FIELDS,
    CYQ_PERF_FIELDS,
    DAILY_BASIC_FIELDS,
    DAILY_FIELDS,
    LIMIT_CPT_LIST_FIELDS,
    LIMIT_LIST_FIELDS,
    LIMIT_LIST_THS_FIELDS,
    LIMIT_STEP_FIELDS,
    MARGIN_FIELDS,
    STK_LIMIT_FIELDS,
    STK_FACTOR_PRO_FIELDS,
    STK_MINS_FIELDS,
    STK_NINETURN_FIELDS,
    STK_PERIOD_BAR_ADJ_FIELDS,
    STK_PERIOD_BAR_FIELDS,
    STOCK_ST_FIELDS,
    SUSPEND_D_FIELDS,
    TOP_LIST_FIELDS,
)
from src.foundation.services.sync_v2.contracts import (
    DatasetSyncContract,
    InputField,
    ObserveSpec,
    PaginationSpec,
    SourceSpec,
    TransactionSpec,
)
from src.foundation.services.sync_v2.registry_parts.builders import (
    build_date_model,
    build_input_schema,
    build_normalization_spec,
    build_planning_spec,
    build_write_spec,
)
from src.foundation.services.sync_v2.registry_parts.common.constants import (
    ALL_LIMIT_LIST_THS_LIMIT_TYPES,
    ALL_LIMIT_LIST_THS_MARKETS,
)
from src.foundation.services.sync_v2.registry_parts.common.param_policies import *  # noqa: F403
from src.foundation.services.sync_v2.registry_parts.common.row_transforms import *  # noqa: F403

CONTRACTS: dict[str, DatasetSyncContract] = {
    "biying_equity_daily": DatasetSyncContract(
        dataset_key="biying_equity_daily",
        display_name="BIYING 股票日线",
        job_name="sync_biying_equity_daily",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("biying_equity_daily"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("adj_type", "string", required=False, description="复权类型 n/f/b"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            enum_fanout_fields=("limit_type", "market"),
            enum_fanout_defaults={
                "limit_type": ALL_LIMIT_LIST_THS_LIMIT_TYPES,
                "market": ALL_LIMIT_LIST_THS_MARKETS,
            },
            pagination_policy="none",
        ),
        source_adapter_key="biying",
        source_spec=SourceSpec(
            api_name="equity_daily_bar",
            fields=tuple(BIYING_EQUITY_DAILY_FIELDS),
            unit_params_builder=_biying_equity_daily_params,
            source_key_default="biying",
        ),
        normalization_spec=build_normalization_spec(
            decimal_fields=("o", "h", "l", "c", "pc", "v", "a"),
            required_fields=("dm", "trade_date", "adj_type"),
            row_transform=_biying_equity_daily_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_biying_equity_daily_bar",
            core_dao_name="raw_biying_equity_daily_bar",
            target_table="raw_biying.equity_daily_bar",
            write_path="raw_only_upsert",
        ),
        observe_spec=ObserveSpec(progress_label="biying_equity_daily"),
    ),
    "daily": DatasetSyncContract(
        dataset_key="daily",
        display_name="股票日线行情",
        job_name="sync_equity_daily",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("daily"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("exchange", "string", required=False, default=get_settings().default_exchange, description="交易所"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="daily",
            fields=tuple(DAILY_FIELDS),
            unit_params_builder=_daily_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"),
            required_fields=("trade_date", "ts_code"),
            row_transform=_daily_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_daily",
            core_dao_name="equity_daily_bar",
            target_table="core_serving.equity_daily_bar",
        ),
        observe_spec=ObserveSpec(progress_label="daily"),
    ),
    "adj_factor": DatasetSyncContract(
        dataset_key="adj_factor",
        display_name="复权因子",
        job_name="sync_adj_factor",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("adj_factor"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("exchange", "string", required=False, default=get_settings().default_exchange, description="交易所"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="adj_factor",
            fields=tuple(ADJ_FACTOR_FIELDS),
            unit_params_builder=_adj_factor_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("adj_factor",),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_adj_factor",
            core_dao_name="equity_adj_factor",
            target_table="core.equity_adj_factor",
        ),
        observe_spec=ObserveSpec(progress_label="adj_factor"),
    ),
    "daily_basic": DatasetSyncContract(
        dataset_key="daily_basic",
        display_name="每日指标",
        job_name="maintain_daily_basic",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("daily_basic"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="daily_basic",
            fields=tuple(DAILY_BASIC_FIELDS),
            unit_params_builder=_daily_basic_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "close",
                "turnover_rate",
                "turnover_rate_f",
                "volume_ratio",
                "pe",
                "pe_ttm",
                "pb",
                "ps",
                "ps_ttm",
                "dv_ratio",
                "dv_ttm",
                "total_share",
                "float_share",
                "free_share",
                "total_mv",
                "circ_mv",
            ),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_daily_basic",
            core_dao_name="equity_daily_basic",
            target_table="core_serving.equity_daily_basic",
        ),
        observe_spec=ObserveSpec(progress_label="daily_basic"),
    ),
    "stk_limit": DatasetSyncContract(
        dataset_key="stk_limit",
        display_name="每日涨跌停价格",
        job_name="sync_stk_limit",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("stk_limit"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="stk_limit",
            fields=tuple(STK_LIMIT_FIELDS),
            unit_params_builder=_stk_limit_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("pre_close", "up_limit", "down_limit"),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_stk_limit",
            core_dao_name="equity_stk_limit",
            target_table="core_serving.equity_stk_limit",
        ),
        observe_spec=ObserveSpec(progress_label="stk_limit"),
        pagination_spec=PaginationSpec(page_limit=5800),
    ),
    "stk_mins": DatasetSyncContract(
        dataset_key="stk_mins",
        display_name="股票历史分钟行情",
        job_name="sync_stk_mins",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("stk_mins"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始交易日"),
                InputField("end_date", "date", required=False, description="结束交易日"),
                InputField("ts_code", "string", required=False, description="股票代码；不传则按股票池扇出"),
                InputField(
                    "freq",
                    "list",
                    required=True,
                    enum_values=("1min", "5min", "15min", "30min", "60min"),
                    description="分钟频度，支持逗号分隔或多选",
                ),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="stk_mins",
            fields=tuple(STK_MINS_FIELDS),
            unit_params_builder=_stk_mins_params,
        ),
        normalization_spec=build_normalization_spec(
            decimal_fields=("open", "close", "high", "low", "vol", "amount"),
            required_fields=("ts_code", "freq", "trade_time", "trade_date", "session_tag"),
            row_transform=_stk_mins_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_stk_mins",
            core_dao_name="raw_stk_mins",
            target_table="raw_tushare.stk_mins",
            write_path="raw_only_upsert",
        ),
        observe_spec=ObserveSpec(progress_label="stk_mins"),
        transaction_spec=TransactionSpec(
            commit_policy="unit",
            idempotent_write_required=True,
            write_volume_assessment="单个事务限定为一个 planned unit；stk_mins unit 由股票代码、频率与时间窗口确定，write_path=raw_only_upsert 为幂等 upsert。",
        ),
        pagination_spec=PaginationSpec(page_limit=8000),
    ),
    "suspend_d": DatasetSyncContract(
        dataset_key="suspend_d",
        display_name="每日停复牌信息",
        job_name="sync_suspend_d",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("suspend_d"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("suspend_type", "string", required=False, description="停复牌类型"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="suspend_d",
            fields=tuple(SUSPEND_D_FIELDS),
            unit_params_builder=_suspend_d_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            required_fields=("trade_date", "ts_code", "row_key_hash"),
            row_transform=_suspend_d_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_suspend_d",
            core_dao_name="equity_suspend_d",
            target_table="core_serving.equity_suspend_d",
            conflict_columns=("row_key_hash",),
        ),
        observe_spec=ObserveSpec(progress_label="suspend_d"),
        pagination_spec=PaginationSpec(page_limit=5000),
    ),
    "cyq_perf": DatasetSyncContract(
        dataset_key="cyq_perf",
        display_name="每日筹码及胜率",
        job_name="sync_cyq_perf",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("cyq_perf"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("exchange", "string", required=False, default=get_settings().default_exchange, description="交易所"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="cyq_perf",
            fields=tuple(CYQ_PERF_FIELDS),
            unit_params_builder=_cyq_perf_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "his_low",
                "his_high",
                "cost_5pct",
                "cost_15pct",
                "cost_50pct",
                "cost_85pct",
                "cost_95pct",
                "weight_avg",
                "winner_rate",
            ),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_cyq_perf",
            core_dao_name="equity_cyq_perf",
            target_table="core_serving.equity_cyq_perf",
        ),
        observe_spec=ObserveSpec(progress_label="cyq_perf"),
        pagination_spec=PaginationSpec(page_limit=5000),
    ),
    "stk_factor_pro": DatasetSyncContract(
        dataset_key="stk_factor_pro",
        display_name="股票技术面因子(专业版)",
        job_name="sync_stk_factor_pro",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("stk_factor_pro"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="stk_factor_pro",
            fields=tuple(STK_FACTOR_PRO_FIELDS),
            unit_params_builder=_stk_factor_pro_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_stk_factor_pro",
            core_dao_name="equity_factor_pro",
            target_table="core_serving.equity_factor_pro",
        ),
        observe_spec=ObserveSpec(progress_label="stk_factor_pro"),
        transaction_spec=TransactionSpec(
            commit_policy="unit",
            idempotent_write_required=True,
            write_volume_assessment="单个事务限定为一个 planned unit；stk_factor_pro unit 由交易日与筛选参数确定，write_path=raw_core_upsert 为幂等 upsert。",
        ),
        pagination_spec=PaginationSpec(page_limit=10000),
    ),
    "margin": DatasetSyncContract(
        dataset_key="margin",
        display_name="融资融券汇总",
        job_name="sync_margin",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("margin"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("exchange_id", "list", required=False, description="交易所列表"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            enum_fanout_fields=("exchange_id",),
            enum_fanout_defaults={"exchange_id": ALL_MARGIN_EXCHANGE_IDS},
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="margin",
            fields=tuple(MARGIN_FIELDS),
            unit_params_builder=_margin_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("rzye", "rzmre", "rzche", "rqye", "rqmcl", "rzrqye", "rqyl"),
            required_fields=("trade_date", "exchange_id"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_margin",
            core_dao_name="equity_margin",
            target_table="core_serving.equity_margin",
        ),
        observe_spec=ObserveSpec(progress_label="margin"),
    ),
    "limit_list_d": DatasetSyncContract(
        dataset_key="limit_list_d",
        display_name="每日涨跌停名单",
        job_name="sync_limit_list",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("limit_list_d"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("limit_type", "list", required=False, description="涨跌停类型"),
                InputField("exchange", "list", required=False, description="交易所"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            enum_fanout_fields=("limit_type", "exchange"),
            enum_fanout_defaults={"limit_type": ALL_LIMIT_LIST_TYPES, "exchange": ALL_LIMIT_LIST_EXCHANGES},
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="limit_list_d",
            fields=tuple(LIMIT_LIST_FIELDS),
            unit_params_builder=_limit_list_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("close", "pct_chg", "amount", "limit_amount", "float_mv", "total_mv", "turnover_ratio", "fd_amount"),
            required_fields=("trade_date", "ts_code", "limit_type"),
            row_transform=_limit_list_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_limit_list",
            core_dao_name="equity_limit_list",
            target_table="core_serving.equity_limit_list",
        ),
        observe_spec=ObserveSpec(progress_label="limit_list_d"),
    ),
    "limit_list_ths": DatasetSyncContract(
        dataset_key="limit_list_ths",
        display_name="同花顺涨停名单",
        job_name="sync_limit_list_ths",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("limit_list_ths"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("limit_type", "list", required=False, description="同花顺涨跌停类型"),
                InputField("market", "list", required=False, description="市场"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="limit_list_ths",
            fields=tuple(LIMIT_LIST_THS_FIELDS),
            unit_params_builder=_limit_list_ths_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "price",
                "pct_chg",
                "limit_order",
                "limit_amount",
                "turnover_rate",
                "free_float",
                "lu_limit_order",
                "limit_up_suc_rate",
                "turnover",
                "rise_rate",
                "sum_float",
            ),
            required_fields=("trade_date", "ts_code", "query_limit_type", "query_market"),
            row_transform=_limit_list_ths_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_limit_list_ths",
            core_dao_name="limit_list_ths",
            target_table="core_serving.limit_list_ths",
        ),
        observe_spec=ObserveSpec(progress_label="limit_list_ths"),
    ),
    "limit_step": DatasetSyncContract(
        dataset_key="limit_step",
        display_name="连板梯队",
        job_name="sync_limit_step",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("limit_step"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("nums", "string", required=False, description="几连板"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="limit_step",
            fields=tuple(LIMIT_STEP_FIELDS),
            unit_params_builder=_limit_step_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            required_fields=("trade_date", "ts_code", "nums"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_limit_step",
            core_dao_name="limit_step",
            target_table="core_serving.limit_step",
        ),
        observe_spec=ObserveSpec(progress_label="limit_step"),
    ),
    "limit_cpt_list": DatasetSyncContract(
        dataset_key="limit_cpt_list",
        display_name="涨停概念列表",
        job_name="sync_limit_cpt_list",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("limit_cpt_list"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="limit_cpt_list",
            fields=tuple(LIMIT_CPT_LIST_FIELDS),
            unit_params_builder=_limit_cpt_list_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("pct_chg",),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_limit_cpt_list",
            core_dao_name="limit_cpt_list",
            target_table="core_serving.limit_cpt_list",
        ),
        observe_spec=ObserveSpec(progress_label="limit_cpt_list"),
    ),
    "top_list": DatasetSyncContract(
        dataset_key="top_list",
        display_name="龙虎榜",
        job_name="sync_top_list",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("top_list"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="top_list",
            fields=tuple(TOP_LIST_FIELDS),
            unit_params_builder=_top_list_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "close",
                "pct_change",
                "turnover_rate",
                "amount",
                "l_sell",
                "l_buy",
                "l_amount",
                "net_amount",
                "net_rate",
                "amount_rate",
                "float_values",
            ),
            required_fields=("trade_date", "ts_code", "reason", "reason_hash"),
            row_transform=_top_list_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_top_list",
            core_dao_name="equity_top_list",
            target_table="core_serving.equity_top_list",
        ),
        observe_spec=ObserveSpec(progress_label="top_list"),
        pagination_spec=PaginationSpec(page_limit=10000),
    ),
    "block_trade": DatasetSyncContract(
        dataset_key="block_trade",
        display_name="大宗交易",
        job_name="sync_block_trade",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("block_trade"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="block_trade",
            fields=tuple(BLOCK_TRADE_FIELDS),
            unit_params_builder=_block_trade_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("price", "vol", "amount"),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_block_trade",
            core_dao_name="equity_block_trade",
            target_table="core_serving.equity_block_trade",
            write_path="raw_core_snapshot_insert_by_trade_date",
        ),
        observe_spec=ObserveSpec(progress_label="block_trade"),
        pagination_spec=PaginationSpec(page_limit=1000),
    ),
    "stock_st": DatasetSyncContract(
        dataset_key="stock_st",
        display_name="ST股票列表",
        job_name="sync_stock_st",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("stock_st"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="stock_st",
            fields=tuple(STOCK_ST_FIELDS),
            unit_params_builder=_stock_st_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            required_fields=("trade_date", "ts_code", "type"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_stock_st",
            core_dao_name="equity_stock_st",
            target_table="core_serving.equity_stock_st",
        ),
        observe_spec=ObserveSpec(progress_label="stock_st"),
        pagination_spec=PaginationSpec(page_limit=1000),
    ),
    "stk_nineturn": DatasetSyncContract(
        dataset_key="stk_nineturn",
        display_name="神奇九转指标",
        job_name="sync_stk_nineturn",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("stk_nineturn"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="stk_nineturn",
            fields=tuple(STK_NINETURN_FIELDS),
            unit_params_builder=_stk_nineturn_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("open", "high", "low", "close", "vol", "amount", "up_count", "down_count"),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_stk_nineturn",
            core_dao_name="equity_nineturn",
            target_table="core_serving.equity_nineturn",
        ),
        observe_spec=ObserveSpec(progress_label="stk_nineturn"),
        pagination_spec=PaginationSpec(page_limit=10000),
    ),
    "stk_period_bar_week": DatasetSyncContract(
        dataset_key="stk_period_bar_week",
        display_name="股票周线行情",
        job_name="sync_stk_period_bar_week",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("stk_period_bar_week"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="stk_weekly_monthly",
            fields=tuple(STK_PERIOD_BAR_FIELDS),
            unit_params_builder=_stk_period_bar_week_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date", "end_date"),
            decimal_fields=("open", "high", "low", "close", "pre_close", "vol", "amount", "change", "pct_chg"),
            required_fields=("trade_date", "ts_code", "freq"),
            row_transform=_stk_period_bar_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_stk_period_bar",
            core_dao_name="stk_period_bar",
            target_table="core_serving.stk_period_bar",
        ),
        observe_spec=ObserveSpec(progress_label="stk_period_bar_week"),
    ),
    "stk_period_bar_month": DatasetSyncContract(
        dataset_key="stk_period_bar_month",
        display_name="股票月线行情",
        job_name="sync_stk_period_bar_month",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("stk_period_bar_month"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="stk_weekly_monthly",
            fields=tuple(STK_PERIOD_BAR_FIELDS),
            unit_params_builder=_stk_period_bar_month_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date", "end_date"),
            decimal_fields=("open", "high", "low", "close", "pre_close", "vol", "amount", "change", "pct_chg"),
            required_fields=("trade_date", "ts_code", "freq"),
            row_transform=_stk_period_bar_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_stk_period_bar",
            core_dao_name="stk_period_bar",
            target_table="core_serving.stk_period_bar",
        ),
        observe_spec=ObserveSpec(progress_label="stk_period_bar_month"),
    ),
    "stk_period_bar_adj_week": DatasetSyncContract(
        dataset_key="stk_period_bar_adj_week",
        display_name="股票周线行情（复权）",
        job_name="sync_stk_period_bar_adj_week",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("stk_period_bar_adj_week"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="stk_week_month_adj",
            fields=tuple(STK_PERIOD_BAR_ADJ_FIELDS),
            unit_params_builder=_stk_period_bar_adj_week_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date", "end_date"),
            decimal_fields=(
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "open_qfq",
                "high_qfq",
                "low_qfq",
                "close_qfq",
                "open_hfq",
                "high_hfq",
                "low_hfq",
                "close_hfq",
                "vol",
                "amount",
                "change",
                "pct_chg",
            ),
            required_fields=("trade_date", "ts_code", "freq"),
            row_transform=_stk_period_bar_adj_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_stk_period_bar_adj",
            core_dao_name="stk_period_bar_adj",
            target_table="core_serving.stk_period_bar_adj",
        ),
        observe_spec=ObserveSpec(progress_label="stk_period_bar_adj_week"),
    ),
    "stk_period_bar_adj_month": DatasetSyncContract(
        dataset_key="stk_period_bar_adj_month",
        display_name="股票月线行情（复权）",
        job_name="sync_stk_period_bar_adj_month",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("stk_period_bar_adj_month"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="stk_week_month_adj",
            fields=tuple(STK_PERIOD_BAR_ADJ_FIELDS),
            unit_params_builder=_stk_period_bar_adj_month_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date", "end_date"),
            decimal_fields=(
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "open_qfq",
                "high_qfq",
                "low_qfq",
                "close_qfq",
                "open_hfq",
                "high_hfq",
                "low_hfq",
                "close_hfq",
                "vol",
                "amount",
                "change",
                "pct_chg",
            ),
            required_fields=("trade_date", "ts_code", "freq"),
            row_transform=_stk_period_bar_adj_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_stk_period_bar_adj",
            core_dao_name="stk_period_bar_adj",
            target_table="core_serving.stk_period_bar_adj",
        ),
        observe_spec=ObserveSpec(progress_label="stk_period_bar_adj_month"),
    ),
    "broker_recommend": DatasetSyncContract(
        dataset_key="broker_recommend",
        display_name="券商月度金股推荐",
        job_name="sync_broker_recommend",
        run_profiles_supported=("point_incremental", "range_rebuild", "snapshot_refresh"),
        date_model=build_date_model("broker_recommend"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("month", "string", required=False, description="月份，YYYYMM"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="broker_recommend",
            fields=tuple(BROKER_RECOMMEND_FIELDS),
            unit_params_builder=_broker_recommend_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("close", "pct_change", "target_price"),
            required_fields=("month", "ts_code", "broker"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_broker_recommend",
            core_dao_name="broker_recommend",
            target_table="core_serving.broker_recommend",
        ),
        observe_spec=ObserveSpec(progress_label="broker_recommend"),
        pagination_spec=PaginationSpec(page_limit=1000),
    ),
}
