from __future__ import annotations

from src.foundation.config.settings import get_settings
from src.foundation.services.sync_v2.fields import (
    FUND_ADJ_FIELDS,
    FUND_DAILY_FIELDS,
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

CONTRACTS: dict[str, DatasetSyncContract] = {    "fund_daily": DatasetSyncContract(
        dataset_key="fund_daily",
        display_name="基金日线行情",
        job_name="sync_fund_daily",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="基金代码"),
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
            api_name="fund_daily",
            fields=tuple(FUND_DAILY_FIELDS),
            unit_params_builder=_fund_daily_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"),
            required_fields=("trade_date", "ts_code"),
            row_transform=_fund_daily_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_fund_daily",
            core_dao_name="fund_daily_bar",
            target_table="core_serving.fund_daily_bar",
        ),
        observe_spec=ObserveSpec(progress_label="fund_daily"),
        pagination_spec=PaginationSpec(page_limit=5000),
    ),
    "fund_adj": DatasetSyncContract(
        dataset_key="fund_adj",
        display_name="基金复权因子",
        job_name="sync_fund_adj",
        run_profiles_supported=("point_incremental", "range_rebuild", "snapshot_refresh"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="基金代码"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="fund_adj",
            fields=tuple(FUND_ADJ_FIELDS),
            unit_params_builder=_fund_adj_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("adj_factor",),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_fund_adj",
            core_dao_name="fund_adj_factor",
            target_table="core.fund_adj_factor",
        ),
        observe_spec=ObserveSpec(progress_label="fund_adj"),
        pagination_spec=PaginationSpec(page_limit=2000),
    ),
}
