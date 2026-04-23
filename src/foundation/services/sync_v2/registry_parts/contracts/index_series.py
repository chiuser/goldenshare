from __future__ import annotations

from src.foundation.config.settings import get_settings
from src.foundation.services.sync.fields import (
    ETF_INDEX_FIELDS,
    INDEX_BASIC_FIELDS,
    INDEX_DAILY_BASIC_FIELDS,
    INDEX_DAILY_FIELDS,
    INDEX_MONTHLY_FIELDS,
    INDEX_WEEKLY_FIELDS,
    INDEX_WEIGHT_FIELDS,
)
from src.foundation.services.sync_v2.contracts import (
    DatasetSyncContract,
    InputField,
    ObserveSpec,
    PaginationSpec,
    SourceSpec,
)
from src.foundation.services.sync_v2.registry_parts.builders import (
    build_input_schema,
    build_normalization_spec,
    build_planning_spec,
    build_write_spec,
)
from src.foundation.services.sync_v2.registry_parts.common.param_policies import *  # noqa: F403
from src.foundation.services.sync_v2.registry_parts.common.row_transforms import *  # noqa: F403

CONTRACTS: dict[str, DatasetSyncContract] = {
    "index_daily": DatasetSyncContract(
        dataset_key="index_daily",
        display_name="指数日线行情",
        job_name="sync_index_daily",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="指数代码"),
                InputField("exchange", "string", required=False, default=get_settings().default_exchange, description="交易所"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="none",
            anchor_type="natural_date_range",
            window_policy="point_or_range",
            universe_policy="index_active_codes",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="index_daily",
            fields=tuple(INDEX_DAILY_FIELDS),
            unit_params_builder=_index_daily_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"),
            required_fields=("trade_date", "ts_code"),
            row_transform=_index_daily_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_index_daily",
            core_dao_name="index_daily_serving",
            target_table="core_serving.index_daily_serving",
        ),
        observe_spec=ObserveSpec(progress_label="index_daily"),
        pagination_spec=PaginationSpec(page_limit=2000),
    ),
    "index_weekly": DatasetSyncContract(
        dataset_key="index_weekly",
        display_name="指数周线行情",
        job_name="sync_index_weekly",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="指数代码"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="week_end_trade_date",
            anchor_type="week_end_trade_date",
            window_policy="point_or_range",
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="index_weekly",
            fields=tuple(INDEX_WEEKLY_FIELDS),
            unit_params_builder=_index_weekly_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"),
            required_fields=("trade_date", "ts_code"),
            row_transform=_index_daily_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_index_weekly_bar",
            core_dao_name="index_weekly_serving",
            target_table="core_serving.index_weekly_serving",
            write_path="raw_index_period_serving_upsert",
        ),
        observe_spec=ObserveSpec(progress_label="index_weekly"),
        pagination_spec=PaginationSpec(page_limit=1000),
    ),
    "index_monthly": DatasetSyncContract(
        dataset_key="index_monthly",
        display_name="指数月线行情",
        job_name="sync_index_monthly",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="指数代码"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="month_end_trade_date",
            anchor_type="month_end_trade_date",
            window_policy="point_or_range",
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="index_monthly",
            fields=tuple(INDEX_MONTHLY_FIELDS),
            unit_params_builder=_index_monthly_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"),
            required_fields=("trade_date", "ts_code"),
            row_transform=_index_daily_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_index_monthly_bar",
            core_dao_name="index_monthly_serving",
            target_table="core_serving.index_monthly_serving",
            write_path="raw_index_period_serving_upsert",
        ),
        observe_spec=ObserveSpec(progress_label="index_monthly"),
        pagination_spec=PaginationSpec(page_limit=1000),
    ),
    "index_daily_basic": DatasetSyncContract(
        dataset_key="index_daily_basic",
        display_name="指数每日指标",
        job_name="sync_index_daily_basic",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="指数代码"),
                InputField("exchange", "string", required=False, default=get_settings().default_exchange, description="交易所"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="index_dailybasic",
            fields=tuple(INDEX_DAILY_BASIC_FIELDS),
            unit_params_builder=_index_daily_basic_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "total_mv",
                "float_mv",
                "total_share",
                "float_share",
                "free_share",
                "turnover_rate",
                "turnover_rate_f",
                "pe",
                "pe_ttm",
                "pb",
            ),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_index_daily_basic",
            core_dao_name="index_daily_basic",
            target_table="core_serving.index_daily_basic",
        ),
        observe_spec=ObserveSpec(progress_label="index_daily_basic"),
        pagination_spec=PaginationSpec(page_limit=1000),
    ),
    "index_basic": DatasetSyncContract(
        dataset_key="index_basic",
        display_name="指数基础信息",
        job_name="sync_index_basic",
        run_profiles_supported=("point_incremental", "snapshot_refresh"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("ts_code", "string", required=False, description="指数代码"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="none",
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="index_basic",
            fields=tuple(INDEX_BASIC_FIELDS),
            unit_params_builder=_index_basic_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("base_date", "list_date", "exp_date"),
            decimal_fields=("base_point",),
            required_fields=("ts_code",),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_index_basic",
            core_dao_name="index_basic",
            target_table="core_serving.index_basic",
        ),
        observe_spec=ObserveSpec(progress_label="index_basic"),
    ),
    "etf_index": DatasetSyncContract(
        dataset_key="etf_index",
        display_name="ETF 跟踪指数",
        job_name="sync_etf_index",
        run_profiles_supported=("point_incremental", "snapshot_refresh"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("ts_code", "string", required=False, description="ETF 代码"),
                InputField("pub_date", "date", required=False, description="发布日期"),
                InputField("base_date", "date", required=False, description="基期日期"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="none",
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="etf_index",
            fields=tuple(ETF_INDEX_FIELDS),
            unit_params_builder=_etf_index_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("pub_date", "base_date"),
            decimal_fields=("bp",),
            required_fields=("ts_code",),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_etf_index",
            core_dao_name="etf_index",
            target_table="core_serving.etf_index",
        ),
        observe_spec=ObserveSpec(progress_label="etf_index"),
    ),
    "index_weight": DatasetSyncContract(
        dataset_key="index_weight",
        display_name="指数成分权重",
        job_name="sync_index_weight",
        run_profiles_supported=("range_rebuild",),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("index_code", "string", required=False, description="指数代码"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="none",
            anchor_type="month_range_natural",
            window_policy="range",
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="index_weight",
            fields=tuple(INDEX_WEIGHT_FIELDS),
            unit_params_builder=_index_weight_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("weight",),
            required_fields=("index_code", "trade_date", "con_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_index_weight",
            core_dao_name="index_weight",
            target_table="core_serving.index_weight",
        ),
        observe_spec=ObserveSpec(progress_label="index_weight"),
        pagination_spec=PaginationSpec(page_limit=6000),
    ),
}
