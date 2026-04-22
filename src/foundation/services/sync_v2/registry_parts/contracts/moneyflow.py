from __future__ import annotations

from src.foundation.config.settings import get_settings
from src.foundation.services.sync.fields import (
    MONEYFLOW_CNT_THS_FIELDS,
    MONEYFLOW_DC_FIELDS,
    MONEYFLOW_FIELDS,
    MONEYFLOW_IND_DC_FIELDS,
    MONEYFLOW_IND_THS_FIELDS,
    MONEYFLOW_MKT_DC_FIELDS,
    MONEYFLOW_THS_FIELDS,
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

CONTRACTS: dict[str, DatasetSyncContract] = {    "moneyflow": DatasetSyncContract(
        dataset_key="moneyflow",
        display_name="个股资金流向",
        job_name="sync_moneyflow",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="moneyflow",
            fields=tuple(MONEYFLOW_FIELDS),
            unit_params_builder=_moneyflow_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "buy_sm_amount",
                "sell_sm_amount",
                "buy_md_amount",
                "sell_md_amount",
                "buy_lg_amount",
                "sell_lg_amount",
                "buy_elg_amount",
                "sell_elg_amount",
                "net_mf_amount",
            ),
            required_fields=("trade_date", "ts_code"),
            row_transform=_moneyflow_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_moneyflow",
            core_dao_name="moneyflow_std",
            target_table="core_serving.equity_moneyflow",
            write_path="raw_std_publish_moneyflow",
        ),
        observe_spec=ObserveSpec(progress_label="moneyflow"),
    ),
    "moneyflow_ths": DatasetSyncContract(
        dataset_key="moneyflow_ths",
        display_name="个股资金流向(THS)",
        job_name="sync_moneyflow_ths",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="moneyflow_ths",
            fields=tuple(MONEYFLOW_THS_FIELDS),
            unit_params_builder=_moneyflow_ths_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "pct_change",
                "latest",
                "net_amount",
                "net_d5_amount",
                "buy_lg_amount",
                "buy_lg_amount_rate",
                "buy_md_amount",
                "buy_md_amount_rate",
                "buy_sm_amount",
                "buy_sm_amount_rate",
            ),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_moneyflow_ths",
            core_dao_name="equity_moneyflow_ths",
            target_table="core_serving.equity_moneyflow_ths",
        ),
        observe_spec=ObserveSpec(progress_label="moneyflow_ths"),
        pagination_spec=PaginationSpec(page_limit=6000),
    ),
    "moneyflow_dc": DatasetSyncContract(
        dataset_key="moneyflow_dc",
        display_name="个股资金流向(DC)",
        job_name="sync_moneyflow_dc",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="moneyflow_dc",
            fields=tuple(MONEYFLOW_DC_FIELDS),
            unit_params_builder=_moneyflow_dc_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "pct_change",
                "close",
                "net_amount",
                "net_amount_rate",
                "buy_elg_amount",
                "buy_elg_amount_rate",
                "buy_lg_amount",
                "buy_lg_amount_rate",
                "buy_md_amount",
                "buy_md_amount_rate",
                "buy_sm_amount",
                "buy_sm_amount_rate",
            ),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_moneyflow_dc",
            core_dao_name="equity_moneyflow_dc",
            target_table="core_serving.equity_moneyflow_dc",
        ),
        observe_spec=ObserveSpec(progress_label="moneyflow_dc"),
        pagination_spec=PaginationSpec(page_limit=6000),
    ),
    "moneyflow_cnt_ths": DatasetSyncContract(
        dataset_key="moneyflow_cnt_ths",
        display_name="概念板块资金流向(THS)",
        job_name="sync_moneyflow_cnt_ths",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="概念板块代码"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="moneyflow_cnt_ths",
            fields=tuple(MONEYFLOW_CNT_THS_FIELDS),
            unit_params_builder=_moneyflow_cnt_ths_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "close_price",
                "pct_change",
                "industry_index",
                "pct_change_stock",
                "net_buy_amount",
                "net_sell_amount",
                "net_amount",
            ),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_moneyflow_cnt_ths",
            core_dao_name="concept_moneyflow_ths",
            target_table="core_serving.concept_moneyflow_ths",
        ),
        observe_spec=ObserveSpec(progress_label="moneyflow_cnt_ths"),
    ),
    "moneyflow_ind_ths": DatasetSyncContract(
        dataset_key="moneyflow_ind_ths",
        display_name="行业资金流向(THS)",
        job_name="sync_moneyflow_ind_ths",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="行业代码"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="moneyflow_ind_ths",
            fields=tuple(MONEYFLOW_IND_THS_FIELDS),
            unit_params_builder=_moneyflow_ind_ths_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "close",
                "pct_change",
                "pct_change_stock",
                "close_price",
                "net_buy_amount",
                "net_sell_amount",
                "net_amount",
            ),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_moneyflow_ind_ths",
            core_dao_name="industry_moneyflow_ths",
            target_table="core_serving.industry_moneyflow_ths",
        ),
        observe_spec=ObserveSpec(progress_label="moneyflow_ind_ths"),
        pagination_spec=PaginationSpec(page_limit=5000),
    ),
    "moneyflow_ind_dc": DatasetSyncContract(
        dataset_key="moneyflow_ind_dc",
        display_name="板块资金流向(DC)",
        job_name="sync_moneyflow_ind_dc",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("content_type", "list", required=False, description="板块类型"),
                InputField("ts_code", "string", required=False, description="板块代码"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            enum_fanout_fields=("content_type",),
            enum_fanout_defaults={"content_type": ALL_MONEYFLOW_IND_DC_CONTENT_TYPES},
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="moneyflow_ind_dc",
            fields=tuple(MONEYFLOW_IND_DC_FIELDS),
            unit_params_builder=_moneyflow_ind_dc_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "pct_change",
                "close",
                "net_amount",
                "net_amount_rate",
                "buy_elg_amount",
                "buy_elg_amount_rate",
                "buy_lg_amount",
                "buy_lg_amount_rate",
                "buy_md_amount",
                "buy_md_amount_rate",
                "buy_sm_amount",
                "buy_sm_amount_rate",
            ),
            required_fields=("trade_date", "content_type", "ts_code"),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_moneyflow_ind_dc",
            core_dao_name="board_moneyflow_dc",
            target_table="core_serving.board_moneyflow_dc",
        ),
        observe_spec=ObserveSpec(progress_label="moneyflow_ind_dc"),
        pagination_spec=PaginationSpec(page_limit=5000),
    ),
    "moneyflow_mkt_dc": DatasetSyncContract(
        dataset_key="moneyflow_mkt_dc",
        display_name="市场资金流向(DC)",
        job_name="sync_moneyflow_mkt_dc",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=build_input_schema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
            )
        ),
        planning_spec=build_planning_spec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="moneyflow_mkt_dc",
            fields=tuple(MONEYFLOW_MKT_DC_FIELDS),
            unit_params_builder=_moneyflow_mkt_dc_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("trade_date",),
            decimal_fields=(
                "close_sh",
                "pct_change_sh",
                "close_sz",
                "pct_change_sz",
                "net_amount",
                "net_amount_rate",
                "buy_elg_amount",
                "buy_elg_amount_rate",
                "buy_lg_amount",
                "buy_lg_amount_rate",
                "buy_md_amount",
                "buy_md_amount_rate",
                "buy_sm_amount",
                "buy_sm_amount_rate",
            ),
            required_fields=("trade_date",),
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_moneyflow_mkt_dc",
            core_dao_name="market_moneyflow_dc",
            target_table="core_serving.market_moneyflow_dc",
        ),
        observe_spec=ObserveSpec(progress_label="moneyflow_mkt_dc"),
        pagination_spec=PaginationSpec(page_limit=5000),
    ),
}
