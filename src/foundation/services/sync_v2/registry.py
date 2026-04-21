from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.foundation.config.settings import get_settings
from src.foundation.services.sync.fields import (
    CYQ_PERF_FIELDS,
    DAILY_BASIC_FIELDS,
    MARGIN_FIELDS,
    MONEYFLOW_IND_DC_FIELDS,
    STK_LIMIT_FIELDS,
    SUSPEND_D_FIELDS,
    TRADE_CAL_FIELDS,
)
from src.foundation.services.transform.suspend_hash import build_suspend_d_row_key_hash
from src.foundation.services.sync_v2.contracts import (
    DatasetSyncContract,
    InputField,
    InputSchema,
    NormalizationSpec,
    ObserveSpec,
    PaginationSpec,
    PlanningSpec,
    SourceSpec,
    WriteSpec,
)

ALL_MARGIN_EXCHANGE_IDS = ("SSE", "SZSE", "BSE")
ALL_MONEYFLOW_IND_DC_CONTENT_TYPES = ("行业", "概念", "地域")


def _trade_cal_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    exchange = str(request.params.get("exchange") or get_settings().default_exchange)
    if request.run_profile == "point_incremental" and anchor_date is not None:
        text = anchor_date.strftime("%Y%m%d")
        return {"exchange": exchange, "start_date": text, "end_date": text}
    if request.run_profile == "range_rebuild":
        assert request.start_date is not None and request.end_date is not None
        return {
            "exchange": exchange,
            "start_date": request.start_date.strftime("%Y%m%d"),
            "end_date": request.end_date.strftime("%Y%m%d"),
        }
    end = date.today()
    start = end - timedelta(days=30)
    return {
        "exchange": exchange,
        "start_date": start.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
    }


def _stk_limit_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("stk_limit requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _daily_basic_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("daily_basic requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _suspend_d_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("suspend_d requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    suspend_type = request.params.get("suspend_type")
    if suspend_type not in (None, ""):
        params["suspend_type"] = str(suspend_type).strip().upper()
    return params


def _cyq_perf_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("cyq_perf requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _margin_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("margin requires trade_date anchor")
    exchange_id = str(enum_values.get("exchange_id") or "").strip().upper()
    if not exchange_id:
        raise ValueError("margin requires exchange_id fanout")
    return {
        "trade_date": anchor_date.strftime("%Y%m%d"),
        "exchange_id": exchange_id,
    }


def _moneyflow_ind_dc_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("moneyflow_ind_dc requires trade_date anchor")
    content_type = str(enum_values.get("content_type") or "").strip()
    if not content_type:
        raise ValueError("moneyflow_ind_dc requires content_type fanout")
    params: dict[str, Any] = {
        "trade_date": anchor_date.strftime("%Y%m%d"),
        "content_type": content_type,
    }
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _trade_cal_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    value = transformed.get("is_open")
    if isinstance(value, str):
        transformed["is_open"] = bool(int(value))
    elif value is not None:
        transformed["is_open"] = bool(value)
    transformed["trade_date"] = transformed.get("cal_date")
    return transformed


def _suspend_d_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["row_key_hash"] = build_suspend_d_row_key_hash(transformed)
    return transformed


SYNC_V2_CONTRACTS: dict[str, DatasetSyncContract] = {
    "trade_cal": DatasetSyncContract(
        dataset_key="trade_cal",
        display_name="交易日历",
        job_name="sync_trade_calendar",
        run_profiles_supported=("point_incremental", "range_rebuild", "snapshot_refresh"),
        input_schema=InputSchema(
            fields=(
                InputField("exchange", "string", required=False, default=get_settings().default_exchange, description="交易所"),
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
            )
        ),
        planning_spec=PlanningSpec(
            date_anchor_policy="none",
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="trade_cal",
            fields=tuple(TRADE_CAL_FIELDS),
            unit_params_builder=_trade_cal_params,
        ),
        normalization_spec=NormalizationSpec(
            date_fields=("cal_date", "pretrade_date"),
            required_fields=("exchange", "cal_date", "is_open"),
            row_transform=_trade_cal_row_transform,
        ),
        write_spec=WriteSpec(
            raw_dao_name="raw_trade_cal",
            core_dao_name="trade_calendar",
            target_table="core_serving.trade_calendar",
        ),
        observe_spec=ObserveSpec(progress_label="trade_cal"),
    ),
    "stk_limit": DatasetSyncContract(
        dataset_key="stk_limit",
        display_name="每日涨跌停价格",
        job_name="sync_stk_limit",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=PlanningSpec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="stk_limit",
            fields=tuple(STK_LIMIT_FIELDS),
            unit_params_builder=_stk_limit_params,
        ),
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            decimal_fields=("pre_close", "up_limit", "down_limit"),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=WriteSpec(
            raw_dao_name="raw_stk_limit",
            core_dao_name="equity_stk_limit",
            target_table="core_serving.equity_stk_limit",
        ),
        observe_spec=ObserveSpec(progress_label="stk_limit"),
        pagination_spec=PaginationSpec(page_limit=5800),
    ),
    "daily_basic": DatasetSyncContract(
        dataset_key="daily_basic",
        display_name="每日指标",
        job_name="sync_daily_basic",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
            )
        ),
        planning_spec=PlanningSpec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="daily_basic",
            fields=tuple(DAILY_BASIC_FIELDS),
            unit_params_builder=_daily_basic_params,
        ),
        normalization_spec=NormalizationSpec(
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
        write_spec=WriteSpec(
            raw_dao_name="raw_daily_basic",
            core_dao_name="equity_daily_basic",
            target_table="core_serving.equity_daily_basic",
        ),
        observe_spec=ObserveSpec(progress_label="daily_basic"),
    ),
    "suspend_d": DatasetSyncContract(
        dataset_key="suspend_d",
        display_name="每日停复牌信息",
        job_name="sync_suspend_d",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("suspend_type", "string", required=False, description="停复牌类型"),
            )
        ),
        planning_spec=PlanningSpec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="suspend_d",
            fields=tuple(SUSPEND_D_FIELDS),
            unit_params_builder=_suspend_d_params,
        ),
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            required_fields=("trade_date", "ts_code", "row_key_hash"),
            row_transform=_suspend_d_row_transform,
        ),
        write_spec=WriteSpec(
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
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("exchange", "string", required=False, default=get_settings().default_exchange, description="交易所"),
            )
        ),
        planning_spec=PlanningSpec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="offset_limit",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="cyq_perf",
            fields=tuple(CYQ_PERF_FIELDS),
            unit_params_builder=_cyq_perf_params,
        ),
        normalization_spec=NormalizationSpec(
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
        write_spec=WriteSpec(
            raw_dao_name="raw_cyq_perf",
            core_dao_name="equity_cyq_perf",
            target_table="core_serving.equity_cyq_perf",
        ),
        observe_spec=ObserveSpec(progress_label="cyq_perf"),
        pagination_spec=PaginationSpec(page_limit=5000),
    ),
    "margin": DatasetSyncContract(
        dataset_key="margin",
        display_name="融资融券汇总",
        job_name="sync_margin",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("exchange_id", "list", required=False, description="交易所列表"),
            )
        ),
        planning_spec=PlanningSpec(
            date_anchor_policy="trade_date",
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
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            decimal_fields=("rzye", "rzmre", "rzche", "rqye", "rqmcl", "rzrqye", "rqyl"),
            required_fields=("trade_date", "exchange_id"),
        ),
        write_spec=WriteSpec(
            raw_dao_name="raw_margin",
            core_dao_name="equity_margin",
            target_table="core_serving.equity_margin",
        ),
        observe_spec=ObserveSpec(progress_label="margin"),
    ),
    "moneyflow_ind_dc": DatasetSyncContract(
        dataset_key="moneyflow_ind_dc",
        display_name="板块资金流向(DC)",
        job_name="sync_moneyflow_ind_dc",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("content_type", "list", required=False, description="板块类型"),
                InputField("ts_code", "string", required=False, description="板块代码"),
            )
        ),
        planning_spec=PlanningSpec(
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
        normalization_spec=NormalizationSpec(
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
        write_spec=WriteSpec(
            raw_dao_name="raw_moneyflow_ind_dc",
            core_dao_name="board_moneyflow_dc",
            target_table="core_serving.board_moneyflow_dc",
        ),
        observe_spec=ObserveSpec(progress_label="moneyflow_ind_dc"),
        pagination_spec=PaginationSpec(page_limit=5000),
    ),
}


def list_sync_v2_contracts() -> tuple[DatasetSyncContract, ...]:
    return tuple(SYNC_V2_CONTRACTS[key] for key in sorted(SYNC_V2_CONTRACTS.keys()))


def has_sync_v2_contract(dataset_key: str) -> bool:
    return dataset_key in SYNC_V2_CONTRACTS


def get_sync_v2_contract(dataset_key: str) -> DatasetSyncContract:
    contract = SYNC_V2_CONTRACTS.get(dataset_key)
    if contract is None:
        raise KeyError(f"sync_v2 contract not found for dataset={dataset_key}")
    return contract
