from __future__ import annotations

from src.foundation.services.sync_v2.fields import DIVIDEND_FIELDS, HOLDERNUMBER_FIELDS
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
    "dividend": DatasetSyncContract(
        dataset_key="dividend",
        display_name="分红送股",
        job_name="sync_dividend",
        run_profiles_supported=("range_rebuild", "snapshot_refresh"),
        date_model=build_date_model("dividend"),
        input_schema=build_input_schema(
            fields=(
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("ann_date", "date", required=False, description="公告日期"),
                InputField("record_date", "date", required=False, description="股权登记日"),
                InputField("ex_date", "date", required=False, description="除权除息日"),
                InputField("imp_ann_date", "date", required=False, description="实施公告日"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="dividend",
            fields=tuple(DIVIDEND_FIELDS),
            unit_params_builder=_dividend_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("end_date", "ann_date", "record_date", "ex_date", "pay_date", "div_listdate", "imp_ann_date", "base_date"),
            decimal_fields=("base_share", "stk_div", "stk_bo_rate", "stk_co_rate", "cash_div", "cash_div_tax"),
            required_fields=("ts_code", "end_date", "ann_date", "div_proc", "row_key_hash", "event_key_hash"),
            row_transform=_dividend_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_dividend",
            core_dao_name="equity_dividend",
            target_table="core_serving.equity_dividend",
            conflict_columns=("row_key_hash",),
        ),
        observe_spec=ObserveSpec(progress_label="dividend"),
        pagination_spec=PaginationSpec(page_limit=6000),
    ),
    "stk_holdernumber": DatasetSyncContract(
        dataset_key="stk_holdernumber",
        display_name="股东户数",
        job_name="sync_holder_number",
        run_profiles_supported=("range_rebuild", "snapshot_refresh"),
        date_model=build_date_model("stk_holdernumber"),
        input_schema=build_input_schema(
            fields=(
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("ann_date", "date", required=False, description="公告日期"),
                InputField("enddate", "date", required=False, description="截止日期"),
            )
        ),
        planning_spec=build_planning_spec(
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="stk_holdernumber",
            fields=tuple(HOLDERNUMBER_FIELDS),
            unit_params_builder=_stk_holdernumber_params,
        ),
        normalization_spec=build_normalization_spec(
            date_fields=("ann_date", "end_date"),
            required_fields=("ts_code", "end_date", "row_key_hash", "event_key_hash"),
            row_transform=_holdernumber_row_transform,
        ),
        write_spec=build_write_spec(
            raw_dao_name="raw_holder_number",
            core_dao_name="equity_holder_number",
            target_table="core_serving.equity_holder_number",
            conflict_columns=("row_key_hash",),
        ),
        observe_spec=ObserveSpec(progress_label="stk_holdernumber"),
        pagination_spec=PaginationSpec(page_limit=3000),
    ),
}
