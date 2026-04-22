from __future__ import annotations

from src.foundation.config.settings import get_settings
from src.foundation.services.sync.fields import (
    DC_INDEX_FIELDS,
    DC_MEMBER_FIELDS,
    KPL_CONCEPT_CONS_FIELDS,
    KPL_LIST_FIELDS,
    THS_INDEX_FIELDS,
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

CONTRACTS: dict[str, DatasetSyncContract] = {    "ths_index": DatasetSyncContract(
        dataset_key="ths_index",
        display_name="同花顺板块列表",
        job_name="sync_ths_index",
        run_profiles_supported=("point_incremental", "snapshot_refresh"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("ts_code", "string", required=False, description="板块代码"),
                InputField("exchange", "string", required=False, description="交易所"),
                InputField("type", "string", required=False, description="板块类型"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="none",
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
            date_anchor_policy="trade_date",
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
            date_anchor_policy="trade_date",
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
    "kpl_list": DatasetSyncContract(
        dataset_key="kpl_list",
        display_name="开盘啦榜单",
        job_name="sync_kpl_list",
        run_profiles_supported=("point_incremental", "range_rebuild"),
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
            date_anchor_policy="trade_date",
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
            date_anchor_policy="trade_date",
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
