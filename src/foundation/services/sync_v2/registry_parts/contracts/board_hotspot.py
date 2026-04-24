from __future__ import annotations

from src.foundation.services.sync_v2.fields import (
    DC_DAILY_FIELDS,
    DC_HOT_FIELDS,
    DC_INDEX_FIELDS,
    DC_MEMBER_FIELDS,
    KPL_CONCEPT_CONS_FIELDS,
    KPL_LIST_FIELDS,
    THS_DAILY_FIELDS,
    THS_HOT_FIELDS,
    THS_INDEX_FIELDS,
    THS_MEMBER_FIELDS,
)
from src.foundation.services.sync_v2.contracts import (
    DatasetSyncContract,
    InputField,
    ObserveSpec,
    PaginationSpec,
    SourceSpec,
)
from src.foundation.services.sync_v2.registry_parts.builders import (
    build_date_model,
    build_input_schema,
    build_normalization_spec,
    build_planning_spec,
    build_write_spec,
)
from src.foundation.services.sync_v2.registry_parts.common.param_policies import *  # noqa: F403
from src.foundation.services.sync_v2.registry_parts.common.row_transforms import *  # noqa: F403


CONTRACTS: dict[str, DatasetSyncContract] = {
    "ths_index": DatasetSyncContract(
        dataset_key="ths_index",
        display_name="同花顺板块列表",
        job_name="sync_ths_index",
        run_profiles_supported=("point_incremental", "snapshot_refresh"),
        date_model=build_date_model("ths_index"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("ts_code", "string", required=False, description="板块代码"),
                InputField("exchange", "string", required=False, description="交易所"),
                InputField("type", "string", required=False, description="板块类型"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="ths_index",
            fields=tuple(THS_INDEX_FIELDS),
            unit_params_builder=_ths_index_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("list_date",),
            required_fields=("ts_code",),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_ths_index",
            core_dao_name="ths_index",
            target_table="core_serving.ths_index",
        ),
        observe_spec=ObserveSpec(progress_label="ths_index"),
    ),
    "dc_index": DatasetSyncContract(
        dataset_key="dc_index",
        display_name="东方财富板块列表",
        job_name="sync_dc_index",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("dc_index"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="板块代码"),
                InputField("idx_type", "string", required=False, description="板块类型"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="dc_index",
            fields=tuple(DC_INDEX_FIELDS),
            unit_params_builder=_dc_index_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("pct_change", "leading_pct", "total_mv", "turnover_rate"),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_dc_index",
            core_dao_name="dc_index",
            target_table="core_serving.dc_index",
        ),
        observe_spec=ObserveSpec(progress_label="dc_index"),
    ),
    "dc_member": DatasetSyncContract(
        dataset_key="dc_member",
        display_name="东方财富板块成分",
        job_name="sync_dc_member",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("dc_member"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="板块代码"),
                InputField("con_code", "string", required=False, description="成分股票代码"),
                InputField("idx_type", "string", required=False, description="东财板块类型"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="dc_index_board_codes",
            pagination_policy="none",
            max_units_per_execution=5000,
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="dc_member",
            fields=tuple(DC_MEMBER_FIELDS),
            unit_params_builder=_dc_member_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            required_fields=("trade_date", "ts_code", "con_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_dc_member",
            core_dao_name="dc_member",
            target_table="core_serving.dc_member",
        ),
        observe_spec=ObserveSpec(progress_label="dc_member"),
    ),
    "ths_member": DatasetSyncContract(
        dataset_key="ths_member",
        display_name="同花顺板块成分",
        job_name="sync_ths_member",
        run_profiles_supported=("point_incremental", "range_rebuild", "snapshot_refresh"),
        date_model=build_date_model("ths_member"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="板块代码"),
                InputField("con_code", "string", required=False, description="成分股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="ths_index_board_codes",
            pagination_policy="none",
            max_units_per_execution=5000,
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="ths_member",
            fields=tuple(THS_MEMBER_FIELDS),
            unit_params_builder=_ths_member_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("in_date", "out_date"),
            decimal_fields=("weight",),
            required_fields=("ts_code", "con_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_ths_member",
            core_dao_name="ths_member",
            target_table="core_serving.ths_member",
        ),
        observe_spec=ObserveSpec(progress_label="ths_member"),
    ),
    "ths_daily": DatasetSyncContract(
        dataset_key="ths_daily",
        display_name="同花顺板块日线行情",
        job_name="sync_ths_daily",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("ths_daily"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="板块代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
            max_units_per_execution=5000,
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="ths_daily",
            fields=tuple(THS_DAILY_FIELDS),
            unit_params_builder=_ths_daily_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "close",
                "open",
                "high",
                "low",
                "pre_close",
                "avg_price",
                "change",
                "pct_change",
                "vol",
                "turnover_rate",
                "total_mv",
                "float_mv",
            ),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_ths_daily",
            core_dao_name="ths_daily",
            target_table="core_serving.ths_daily",
        ),
        observe_spec=ObserveSpec(progress_label="ths_daily"),
    ),
    "dc_daily": DatasetSyncContract(
        dataset_key="dc_daily",
        display_name="东方财富板块日线行情",
        job_name="sync_dc_daily",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("dc_daily"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="板块代码"),
                InputField("idx_type", "string", required=False, description="板块类型"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
            max_units_per_execution=5000,
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="dc_daily",
            fields=tuple(DC_DAILY_FIELDS),
            unit_params_builder=_dc_daily_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("close", "open", "high", "low", "change", "pct_change", "vol", "amount", "swing", "turnover_rate"),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_dc_daily",
            core_dao_name="dc_daily",
            target_table="core_serving.dc_daily",
        ),
        observe_spec=ObserveSpec(progress_label="dc_daily"),
    ),
    "ths_hot": DatasetSyncContract(
        dataset_key="ths_hot",
        display_name="同花顺热榜",
        job_name="sync_ths_hot",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("ths_hot"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="证券代码"),
                InputField("market", "string", required=False, description="市场筛选"),
                InputField("is_new", "string", required=False, description="是否最新"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            enum_fanout_fields=("market", "is_new"),
            enum_fanout_defaults={"market": ("__ALL__",), "is_new": ("__ALL__",)},
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="ths_hot",
            fields=tuple(THS_HOT_FIELDS),
            unit_params_builder=_ths_hot_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("pct_change", "current_price", "hot"),
            required_fields=("trade_date", "data_type", "ts_code", "rank_time", "query_market", "query_is_new"),
            row_transform=_ths_hot_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_ths_hot",
            core_dao_name="ths_hot",
            target_table="core_serving.ths_hot",
        ),
        observe_spec=ObserveSpec(progress_label="ths_hot"),
    ),
    "dc_hot": DatasetSyncContract(
        dataset_key="dc_hot",
        display_name="东方财富热榜",
        job_name="sync_dc_hot",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("dc_hot"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="证券代码"),
                InputField("market", "string", required=False, description="市场筛选"),
                InputField("hot_type", "string", required=False, description="热榜类型"),
                InputField("is_new", "string", required=False, description="是否最新"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            enum_fanout_fields=("market", "hot_type", "is_new"),
            enum_fanout_defaults={"market": ("__ALL__",), "hot_type": ("__ALL__",), "is_new": ("__ALL__",)},
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="dc_hot",
            fields=tuple(DC_HOT_FIELDS),
            unit_params_builder=_dc_hot_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=("pct_change", "current_price", "hot"),
            required_fields=("trade_date", "data_type", "ts_code", "rank_time", "query_market", "query_hot_type", "query_is_new"),
            row_transform=_dc_hot_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_dc_hot",
            core_dao_name="dc_hot",
            target_table="core_serving.dc_hot",
        ),
        observe_spec=ObserveSpec(progress_label="dc_hot"),
    ),
    "kpl_list": DatasetSyncContract(
        dataset_key="kpl_list",
        display_name="开盘啦榜单",
        job_name="sync_kpl_list",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("kpl_list"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("tag", "list", required=False, description="榜单标签"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            enum_fanout_fields=("tag",),
            enum_fanout_defaults={"tag": ("__ALL__",)},
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="kpl_list",
            fields=tuple(KPL_LIST_FIELDS),
            unit_params_builder=_kpl_list_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "net_change",
                "bid_amount",
                "bid_change",
                "bid_turnover",
                "lu_bid_vol",
                "pct_chg",
                "bid_pct_chg",
                "rt_pct_chg",
                "limit_order",
                "amount",
                "turnover_rate",
                "free_float",
                "lu_limit_order",
            ),
            required_fields=("ts_code", "trade_date", "tag"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_kpl_list",
            core_dao_name="kpl_list",
            target_table="core_serving.kpl_list",
        ),
        observe_spec=ObserveSpec(progress_label="kpl_list"),
    ),
    "kpl_concept_cons": DatasetSyncContract(
        dataset_key="kpl_concept_cons",
        display_name="开盘啦板块成分",
        job_name="sync_kpl_concept_cons",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        date_model=build_date_model("kpl_concept_cons"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("con_code", "string", required=False, description="板块代码"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="kpl_concept_cons",
            fields=tuple(KPL_CONCEPT_CONS_FIELDS),
            unit_params_builder=_kpl_concept_cons_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            required_fields=("trade_date", "ts_code", "con_code"),
            row_transform=_kpl_concept_cons_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_kpl_concept_cons",
            core_dao_name="kpl_concept_cons",
            target_table="core_serving.kpl_concept_cons",
        ),
        observe_spec=ObserveSpec(progress_label="kpl_concept_cons"),
    ),
}
