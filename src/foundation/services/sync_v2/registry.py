from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from src.foundation.config.settings import get_settings
from src.foundation.services.sync.fields import (
    ADJ_FACTOR_FIELDS,
    BLOCK_TRADE_FIELDS,
    CYQ_PERF_FIELDS,
    DAILY_FIELDS,
    DAILY_BASIC_FIELDS,
    DC_MEMBER_FIELDS,
    DC_INDEX_FIELDS,
    FUND_DAILY_FIELDS,
    INDEX_DAILY_BASIC_FIELDS,
    INDEX_DAILY_FIELDS,
    LIMIT_CPT_LIST_FIELDS,
    LIMIT_LIST_FIELDS,
    LIMIT_LIST_THS_FIELDS,
    LIMIT_STEP_FIELDS,
    MARGIN_FIELDS,
    MONEYFLOW_FIELDS,
    MONEYFLOW_CNT_THS_FIELDS,
    MONEYFLOW_DC_FIELDS,
    MONEYFLOW_IND_DC_FIELDS,
    MONEYFLOW_IND_THS_FIELDS,
    MONEYFLOW_MKT_DC_FIELDS,
    MONEYFLOW_THS_FIELDS,
    STOCK_ST_FIELDS,
    STK_LIMIT_FIELDS,
    STK_NINETURN_FIELDS,
    SUSPEND_D_FIELDS,
    TOP_LIST_FIELDS,
    TRADE_CAL_FIELDS,
)
from src.foundation.services.transform.top_list_reason import hash_top_list_reason
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
ALL_LIMIT_LIST_EXCHANGES = ("SH", "SZ", "BJ")
ALL_LIMIT_LIST_TYPES = ("U", "D", "Z")
ALL_MONEYFLOW_IND_DC_CONTENT_TYPES = ("行业", "概念", "地域")
MONEYFLOW_VOLUME_FIELDS = (
    "buy_sm_vol",
    "sell_sm_vol",
    "buy_md_vol",
    "sell_md_vol",
    "buy_lg_vol",
    "sell_lg_vol",
    "buy_elg_vol",
    "sell_elg_vol",
    "net_mf_vol",
)


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


def _daily_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("daily requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _adj_factor_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("adj_factor requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _fund_daily_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("fund_daily requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _dc_index_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("dc_index requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    idx_type = request.params.get("idx_type")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    if idx_type not in (None, ""):
        params["idx_type"] = str(idx_type).strip()
    return params


def _index_daily_basic_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("index_daily_basic requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _index_daily_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("index_daily requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _limit_list_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("limit_list_d requires trade_date anchor")
    limit_type = str(enum_values.get("limit_type") or "").strip().upper()
    exchange = str(enum_values.get("exchange") or "").strip().upper()
    if not limit_type:
        raise ValueError("limit_list_d requires limit_type fanout")
    if not exchange:
        raise ValueError("limit_list_d requires exchange fanout")
    params: dict[str, Any] = {
        "trade_date": anchor_date.strftime("%Y%m%d"),
        "limit_type": limit_type,
        "exchange": exchange,
    }
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _limit_list_ths_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("limit_list_ths requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    limit_type = request.params.get("limit_type")
    market = request.params.get("market")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    if limit_type not in (None, ""):
        params["limit_type"] = str(limit_type).strip()
    if market not in (None, ""):
        params["market"] = str(market).strip()
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


def _limit_step_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("limit_step requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    nums = request.params.get("nums")
    if nums not in (None, ""):
        params["nums"] = str(nums).strip()
    return params


def _limit_cpt_list_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("limit_cpt_list requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _top_list_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("top_list requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _block_trade_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("block_trade requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _stock_st_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("stock_st requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _stk_nineturn_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("stk_nineturn requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d"), "freq": "daily"}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _dc_member_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("dc_member requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = enum_values.get("ts_code") or request.params.get("ts_code")
    con_code = enum_values.get("con_code") or request.params.get("con_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    if con_code not in (None, ""):
        params["con_code"] = str(con_code).strip().upper()
    return params


def _moneyflow_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("moneyflow requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


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


def _moneyflow_ths_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("moneyflow_ths requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _moneyflow_dc_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("moneyflow_dc requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _moneyflow_cnt_ths_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("moneyflow_cnt_ths requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _moneyflow_ind_ths_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("moneyflow_ind_ths requires trade_date anchor")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _moneyflow_mkt_dc_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("moneyflow_mkt_dc requires trade_date anchor")
    return {"trade_date": anchor_date.strftime("%Y%m%d")}


def _moneyflow_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    for field in MONEYFLOW_VOLUME_FIELDS:
        if field not in transformed:
            continue
        value = transformed.get(field)
        if value in (None, ""):
            transformed[field] = None
            continue
        decimal_value = Decimal(str(value))
        if decimal_value != decimal_value.to_integral_value():
            raise ValueError(f"moneyflow field `{field}` must be integer-like, got: {value}")
        transformed[field] = int(decimal_value)
    return transformed


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


def _top_list_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["pct_chg"] = transformed.get("pct_change")
    transformed["reason_hash"] = hash_top_list_reason(transformed.get("reason"))
    return transformed


def _daily_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["change_amount"] = transformed.get("change")
    transformed["source"] = "tushare"
    return transformed


def _fund_daily_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["change_amount"] = transformed.get("change")
    return transformed


def _index_daily_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["change_amount"] = transformed.get("change")
    return transformed


def _limit_list_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["limit_type"] = transformed.get("limit")
    return transformed


def _limit_list_ths_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["query_limit_type"] = str(transformed.get("limit_type") or "__ALL__")
    transformed["query_market"] = str(transformed.get("market_type") or "__ALL__")
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
    "daily": DatasetSyncContract(
        dataset_key="daily",
        display_name="股票日线行情",
        job_name="sync_equity_daily",
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
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="daily",
            fields=tuple(DAILY_FIELDS),
            unit_params_builder=_daily_params,
        ),
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            decimal_fields=("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"),
            required_fields=("trade_date", "ts_code"),
            row_transform=_daily_row_transform,
        ),
        write_spec=WriteSpec(
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
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="adj_factor",
            fields=tuple(ADJ_FACTOR_FIELDS),
            unit_params_builder=_adj_factor_params,
        ),
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            decimal_fields=("adj_factor",),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=WriteSpec(
            raw_dao_name="raw_adj_factor",
            core_dao_name="equity_adj_factor",
            target_table="core.equity_adj_factor",
        ),
        observe_spec=ObserveSpec(progress_label="adj_factor"),
    ),
    "fund_daily": DatasetSyncContract(
        dataset_key="fund_daily",
        display_name="基金日线行情",
        job_name="sync_fund_daily",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="基金代码"),
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
            api_name="fund_daily",
            fields=tuple(FUND_DAILY_FIELDS),
            unit_params_builder=_fund_daily_params,
        ),
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            decimal_fields=("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"),
            required_fields=("trade_date", "ts_code"),
            row_transform=_fund_daily_row_transform,
        ),
        write_spec=WriteSpec(
            raw_dao_name="raw_fund_daily",
            core_dao_name="fund_daily_bar",
            target_table="core_serving.fund_daily_bar",
        ),
        observe_spec=ObserveSpec(progress_label="fund_daily"),
        pagination_spec=PaginationSpec(page_limit=5000),
    ),
    "dc_index": DatasetSyncContract(
        dataset_key="dc_index",
        display_name="东方财富板块列表",
        job_name="sync_dc_index",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="板块代码"),
                InputField("idx_type", "string", required=False, description="板块类型"),
            )
        ),
        planning_spec=PlanningSpec(
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
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            decimal_fields=("pct_change", "leading_pct", "total_mv", "turnover_rate"),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=WriteSpec(
            raw_dao_name="raw_dc_index",
            core_dao_name="dc_index",
            target_table="core_serving.dc_index",
        ),
        observe_spec=ObserveSpec(progress_label="dc_index"),
    ),
    "index_daily_basic": DatasetSyncContract(
        dataset_key="index_daily_basic",
        display_name="指数每日指标",
        job_name="sync_index_daily_basic",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="指数代码"),
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
            api_name="index_dailybasic",
            fields=tuple(INDEX_DAILY_BASIC_FIELDS),
            unit_params_builder=_index_daily_basic_params,
        ),
        normalization_spec=NormalizationSpec(
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
        write_spec=WriteSpec(
            raw_dao_name="raw_index_daily_basic",
            core_dao_name="index_daily_basic",
            target_table="core_serving.index_daily_basic",
        ),
        observe_spec=ObserveSpec(progress_label="index_daily_basic"),
        pagination_spec=PaginationSpec(page_limit=1000),
    ),
    "index_daily": DatasetSyncContract(
        dataset_key="index_daily",
        display_name="指数日线行情",
        job_name="sync_index_daily",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="指数代码"),
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
            api_name="index_daily",
            fields=tuple(INDEX_DAILY_FIELDS),
            unit_params_builder=_index_daily_params,
        ),
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            decimal_fields=("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"),
            required_fields=("trade_date", "ts_code"),
            row_transform=_index_daily_row_transform,
        ),
        write_spec=WriteSpec(
            raw_dao_name="raw_index_daily",
            core_dao_name="index_daily_serving",
            target_table="core_serving.index_daily_serving",
        ),
        observe_spec=ObserveSpec(progress_label="index_daily"),
        pagination_spec=PaginationSpec(page_limit=2000),
    ),
    "limit_list_d": DatasetSyncContract(
        dataset_key="limit_list_d",
        display_name="每日涨跌停名单",
        job_name="sync_limit_list",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("limit_type", "list", required=False, description="涨跌停类型"),
                InputField("exchange", "list", required=False, description="交易所"),
            )
        ),
        planning_spec=PlanningSpec(
            date_anchor_policy="trade_date",
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
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            decimal_fields=("close", "pct_chg", "amount", "limit_amount", "float_mv", "total_mv", "turnover_ratio", "fd_amount"),
            required_fields=("trade_date", "ts_code", "limit_type"),
            row_transform=_limit_list_row_transform,
        ),
        write_spec=WriteSpec(
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
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("limit_type", "string", required=False, description="同花顺涨跌停类型"),
                InputField("market", "string", required=False, description="市场"),
            )
        ),
        planning_spec=PlanningSpec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="limit_list_ths",
            fields=tuple(LIMIT_LIST_THS_FIELDS),
            unit_params_builder=_limit_list_ths_params,
        ),
        normalization_spec=NormalizationSpec(
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
        write_spec=WriteSpec(
            raw_dao_name="raw_limit_list_ths",
            core_dao_name="limit_list_ths",
            target_table="core_serving.limit_list_ths",
        ),
        observe_spec=ObserveSpec(progress_label="limit_list_ths"),
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
    "limit_step": DatasetSyncContract(
        dataset_key="limit_step",
        display_name="连板梯队",
        job_name="sync_limit_step",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="股票代码"),
                InputField("nums", "string", required=False, description="几连板"),
            )
        ),
        planning_spec=PlanningSpec(
            date_anchor_policy="trade_date",
            universe_policy="none",
            pagination_policy="none",
        ),
        source_adapter_key="tushare",
        source_spec=SourceSpec(
            api_name="limit_step",
            fields=tuple(LIMIT_STEP_FIELDS),
            unit_params_builder=_limit_step_params,
        ),
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            required_fields=("trade_date", "ts_code", "nums"),
        ),
        write_spec=WriteSpec(
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
            api_name="limit_cpt_list",
            fields=tuple(LIMIT_CPT_LIST_FIELDS),
            unit_params_builder=_limit_cpt_list_params,
        ),
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            decimal_fields=("pct_chg",),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=WriteSpec(
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
            api_name="top_list",
            fields=tuple(TOP_LIST_FIELDS),
            unit_params_builder=_top_list_params,
        ),
        normalization_spec=NormalizationSpec(
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
        write_spec=WriteSpec(
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
            api_name="block_trade",
            fields=tuple(BLOCK_TRADE_FIELDS),
            unit_params_builder=_block_trade_params,
        ),
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            decimal_fields=("price", "vol", "amount"),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=WriteSpec(
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
            api_name="stock_st",
            fields=tuple(STOCK_ST_FIELDS),
            unit_params_builder=_stock_st_params,
        ),
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            required_fields=("trade_date", "ts_code", "type"),
        ),
        write_spec=WriteSpec(
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
            api_name="stk_nineturn",
            fields=tuple(STK_NINETURN_FIELDS),
            unit_params_builder=_stk_nineturn_params,
        ),
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            decimal_fields=("open", "high", "low", "close", "vol", "amount", "up_count", "down_count"),
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=WriteSpec(
            raw_dao_name="raw_stk_nineturn",
            core_dao_name="equity_nineturn",
            target_table="core_serving.equity_nineturn",
        ),
        observe_spec=ObserveSpec(progress_label="stk_nineturn"),
        pagination_spec=PaginationSpec(page_limit=10000),
    ),
    "dc_member": DatasetSyncContract(
        dataset_key="dc_member",
        display_name="东方财富板块成分",
        job_name="sync_dc_member",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="板块代码"),
                InputField("con_code", "string", required=False, description="成分股票代码"),
                InputField("idx_type", "string", required=False, description="东财板块类型"),
            )
        ),
        planning_spec=PlanningSpec(
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
        normalization_spec=NormalizationSpec(
            date_fields=("trade_date",),
            required_fields=("trade_date", "ts_code", "con_code"),
        ),
        write_spec=WriteSpec(
            raw_dao_name="raw_dc_member",
            core_dao_name="dc_member",
            target_table="core_serving.dc_member",
        ),
        observe_spec=ObserveSpec(progress_label="dc_member"),
    ),
    "moneyflow": DatasetSyncContract(
        dataset_key="moneyflow",
        display_name="个股资金流向",
        job_name="sync_moneyflow",
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
            api_name="moneyflow",
            fields=tuple(MONEYFLOW_FIELDS),
            unit_params_builder=_moneyflow_params,
        ),
        normalization_spec=NormalizationSpec(
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
        write_spec=WriteSpec(
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
            api_name="moneyflow_ths",
            fields=tuple(MONEYFLOW_THS_FIELDS),
            unit_params_builder=_moneyflow_ths_params,
        ),
        normalization_spec=NormalizationSpec(
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
        write_spec=WriteSpec(
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
            api_name="moneyflow_dc",
            fields=tuple(MONEYFLOW_DC_FIELDS),
            unit_params_builder=_moneyflow_dc_params,
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
            required_fields=("trade_date", "ts_code"),
        ),
        write_spec=WriteSpec(
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
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="概念板块代码"),
            )
        ),
        planning_spec=PlanningSpec(
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
        normalization_spec=NormalizationSpec(
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
        write_spec=WriteSpec(
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
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
                InputField("ts_code", "string", required=False, description="行业代码"),
            )
        ),
        planning_spec=PlanningSpec(
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
        normalization_spec=NormalizationSpec(
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
        write_spec=WriteSpec(
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
    "moneyflow_mkt_dc": DatasetSyncContract(
        dataset_key="moneyflow_mkt_dc",
        display_name="市场资金流向(DC)",
        job_name="sync_moneyflow_mkt_dc",
        run_profiles_supported=("point_incremental", "range_rebuild"),
        input_schema=InputSchema(
            fields=(
                InputField("trade_date", "date", required=False, description="交易日"),
                InputField("start_date", "date", required=False, description="起始日期"),
                InputField("end_date", "date", required=False, description="结束日期"),
            )
        ),
        planning_spec=PlanningSpec(
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
        normalization_spec=NormalizationSpec(
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
        write_spec=WriteSpec(
            raw_dao_name="raw_moneyflow_mkt_dc",
            core_dao_name="market_moneyflow_dc",
            target_table="core_serving.market_moneyflow_dc",
        ),
        observe_spec=ObserveSpec(progress_label="moneyflow_mkt_dc"),
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
