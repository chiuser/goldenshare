from __future__ import annotations

from src.foundation.config.settings import get_settings
from src.foundation.services.sync_v2.fields import (
    ETF_BASIC_FIELDS,
    HK_BASIC_FIELDS,
    STOCK_BASIC_FIELDS,
    TRADE_CAL_FIELDS,
    US_BASIC_FIELDS,
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

CONTRACTS: dict[str, DatasetSyncContract] = {    "trade_cal": DatasetSyncContract(
        dataset_key="trade_cal",
        display_name="交易日历",
        job_name="sync_trade_calendar",
        run_profiles_supported=("point_incremental", "range_rebuild", "snapshot_refresh"),
        input_schema=build_input_schema(
            fields=(
                InputField("exchange", "string", required=False, default=get_settings().default_exchange, description="交易所"),
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="none",
            anchor_type="natural_date_range",
            window_policy="point_or_range",
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="trade_cal",
            fields=tuple(TRADE_CAL_FIELDS),
            unit_params_builder=_trade_cal_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("cal_date", "pretrade_date"),
            required_fields=("exchange", "cal_date", "is_open"),
            row_transform=_trade_cal_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_trade_cal",
            core_dao_name="trade_calendar",
            target_table="core_serving.trade_calendar",
        ),
        observe_spec=ObserveSpec(progress_label="trade_cal"),
    ),
    "stock_basic": DatasetSyncContract(
        dataset_key="stock_basic",
        display_name="股票基础信息",
        job_name="sync_stock_basic",
        run_profiles_supported=("snapshot_refresh",),
        input_schema=build_input_schema(
            fields=(
                InputField(
                    "source_key",
                    "enum",
                    required=False,
                    default="tushare",
                    enum_values=("tushare", "biying", "all"),
                    description="来源选择",
                ),
                InputField("ts_code", "string", required=False, description="证券代码"),
                InputField("name", "string", required=False, description="证券名称"),
                InputField("market", "list", required=False, description="市场类型"),
                InputField("exchange", "list", required=False, description="交易所"),
                InputField("list_status", "list", required=False, description="上市状态"),
                InputField("is_hs", "list", required=False, description="沪深港通标识"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="none",
            anchor_type="none",
            window_policy="none",
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="stock_basic",
            fields=tuple(STOCK_BASIC_FIELDS),
            unit_params_builder=_stock_basic_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("list_date", "delist_date"),
            row_transform=_stock_basic_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_stock_basic",
            core_dao_name="security_std",
            target_table="core_serving.security_serving",
            write_path="raw_std_publish_stock_basic",
        ),
        observe_spec=ObserveSpec(progress_label="stock_basic"),
    ),
    "hk_basic": DatasetSyncContract(
        dataset_key="hk_basic",
        display_name="港股基础信息",
        job_name="sync_hk_basic",
        run_profiles_supported=("point_incremental", "snapshot_refresh"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("list_status", "list", required=False, description="上市状态"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="none",
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="hk_basic",
            fields=tuple(HK_BASIC_FIELDS),
            unit_params_builder=_hk_basic_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("list_date", "delist_date"),
            required_fields=("ts_code",),
            row_transform=_hk_security_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_hk_basic",
            core_dao_name="hk_security",
            target_table="core_serving.hk_security",
        ),
        observe_spec=ObserveSpec(progress_label="hk_basic"),
    ),
    "us_basic": DatasetSyncContract(
        dataset_key="us_basic",
        display_name="美股基础信息",
        job_name="sync_us_basic",
        run_profiles_supported=("point_incremental", "snapshot_refresh"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("classify", "list", required=False, description="证券分类"),
                InputField("ts_code", "string", required=False, description="证券代码"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="none",
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="us_basic",
            fields=tuple(US_BASIC_FIELDS),
            unit_params_builder=_us_basic_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("list_date", "delist_date"),
            required_fields=("ts_code",),
            row_transform=_us_security_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_us_basic",
            core_dao_name="us_security",
            target_table="core_serving.us_security",
        ),
        observe_spec=ObserveSpec(progress_label="us_basic"),
    ),
    "etf_basic": DatasetSyncContract(
        dataset_key="etf_basic",
        display_name="ETF 基础信息",
        job_name="sync_etf_basic",
        run_profiles_supported=("point_incremental", "snapshot_refresh"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("ts_code", "string", required=False, description="ETF 代码"),
                InputField("index_code", "string", required=False, description="指数代码"),
                InputField("exchange", "string", required=False, description="交易所"),
                InputField("mgr", "string", required=False, description="管理人"),
                InputField("list_status", "list", required=False, description="上市状态"),
                InputField("list_date", "date", required=False, description="上市日期"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="none",
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="etf_basic",
            fields=tuple(ETF_BASIC_FIELDS),
            unit_params_builder=_etf_basic_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("setup_date", "list_date"),
            decimal_fields=("mgt_fee",),
            required_fields=("ts_code",),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_etf_basic",
            core_dao_name="etf_basic",
            target_table="core_serving.etf_basic",
        ),
        observe_spec=ObserveSpec(progress_label="etf_basic"),
    ),
}
