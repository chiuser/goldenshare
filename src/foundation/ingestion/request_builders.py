from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.foundation.config.settings import get_settings
from src.foundation.ingestion.constants import (
    ALL_LIMIT_LIST_EXCHANGES,
    ALL_LIMIT_LIST_TYPES,
    ALL_MARGIN_EXCHANGE_IDS,
    ALL_MONEYFLOW_IND_DC_CONTENT_TYPES,
)


def _format_yyyymmdd(value: Any) -> str:
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    return str(value).strip().replace("-", "")


def _has_value(value: Any) -> bool:
    return value not in (None, "")

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
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _stk_mins_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    del request
    del anchor_date
    return {
        "ts_code": str(enum_values["ts_code"]).strip().upper(),
        "freq": str(enum_values["freq"]).strip(),
        "start_date": str(enum_values["window_start"]).strip(),
        "end_date": str(enum_values["window_end"]).strip(),
    }


def _daily_basic_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _daily_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _adj_factor_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _fund_daily_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _fund_adj_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    if request.run_profile == "point_incremental":
        if anchor_date is None:
            raise ValueError("单日维护缺少日期锚点")
        params["trade_date"] = anchor_date.strftime("%Y%m%d")
    elif request.run_profile == "range_rebuild":
        if anchor_date is None:
            raise ValueError("区间维护缺少日期锚点")
        params["trade_date"] = anchor_date.strftime("%Y%m%d")
    else:
        history_start = str(get_settings().history_start_date or "2000-01-01").replace("-", "")
        params["start_date"] = history_start
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _index_basic_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    for key in ("name", "publisher"):
        value = request.params.get(key)
        if value not in (None, ""):
            params[key] = str(value).strip()
    market = enum_values.get("market", request.params.get("market"))
    category = enum_values.get("category", request.params.get("category"))
    if _has_value(market):
        params["market"] = str(market).strip()
    if _has_value(category):
        params["category"] = str(category).strip()
    return params


def _etf_basic_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    list_status = enum_values.get("list_status", request.params.get("list_status"))
    if isinstance(list_status, (list, tuple, set)):
        normalized = [str(item).strip() for item in list_status if str(item).strip()]
        if normalized:
            params["list_status"] = ",".join(normalized)
    elif list_status not in (None, ""):
        params["list_status"] = str(list_status).strip()
    for key in ("ts_code", "index_code", "mgr"):
        value = request.params.get(key)
        if value not in (None, ""):
            params[key] = str(value).strip()
    exchange = enum_values.get("exchange", request.params.get("exchange"))
    if _has_value(exchange):
        params["exchange"] = str(exchange).strip()
    list_date = request.params.get("list_date")
    if list_date not in (None, ""):
        params["list_date"] = str(list_date).replace("-", "")
    return params


def _etf_index_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    for key in ("pub_date", "base_date"):
        value = request.params.get(key)
        if value not in (None, ""):
            params[key] = str(value).replace("-", "")
    return params


def _hk_basic_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    list_status = request.params.get("list_status")
    if isinstance(list_status, (list, tuple, set)):
        normalized = [str(item).strip() for item in list_status if str(item).strip()]
        if normalized:
            params["list_status"] = ",".join(normalized)
    elif list_status not in (None, ""):
        params["list_status"] = str(list_status).strip()
    return params


def _normalize_us_classify(value: Any) -> str:
    normalized = str(value).strip().upper()
    return "EQT" if normalized == "EQ" else normalized


def _us_basic_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    classify = request.params.get("classify")
    if isinstance(classify, (list, tuple, set)):
        normalized = [_normalize_us_classify(item) for item in classify if str(item).strip()]
        if normalized:
            params["classify"] = ",".join(normalized)
    elif classify not in (None, ""):
        params["classify"] = _normalize_us_classify(classify)
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _stock_basic_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    del anchor_date
    source_key = str(enum_values.get("source_key") or request.source_key or request.params.get("source_key") or "tushare").strip().lower()
    if source_key == "biying":
        return {}

    params: dict[str, Any] = {}
    list_status = enum_values.get("list_status", request.params.get("list_status"))
    if not _has_value(list_status):
        params["list_status"] = "L,D,P,G"
    else:
        params["list_status"] = str(list_status).strip()

    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    for key in ("name", "market", "exchange", "is_hs"):
        value = enum_values.get(key, request.params.get(key))
        if _has_value(value):
            params[key] = str(value).strip()
    return params


def _ths_index_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    exchange = request.params.get("exchange")
    if exchange not in (None, ""):
        params["exchange"] = str(exchange).strip()
    ths_type = request.params.get("type")
    if ths_type not in (None, ""):
        params["type"] = str(ths_type).strip()
    return params


def _kpl_list_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    tag = enum_values.get("tag")
    if _has_value(tag):
        params["tag"] = str(tag).strip()
    return params


def _kpl_concept_cons_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("开盘啦题材成分缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    con_code = request.params.get("con_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    if con_code not in (None, ""):
        params["con_code"] = str(con_code).strip().upper()
    return params


def _broker_recommend_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    month = str(request.params.get("month") or "").strip().replace("-", "")
    if month:
        if len(month) != 6 or not month.isdigit():
            raise ValueError("月份必须是 YYYYMM 或 YYYY-MM")
        return {"month": month}

    anchor = anchor_date or request.trade_date
    if anchor is not None:
        return {"month": anchor.strftime("%Y%m")}
    return {}


def _dividend_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    if anchor_date is not None:
        params["ann_date"] = anchor_date.strftime("%Y%m%d")

    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()

    for key in ("ann_date", "record_date", "ex_date", "imp_ann_date"):
        value = request.params.get(key)
        if value not in (None, ""):
            params[key] = _format_yyyymmdd(value)
    return params


def _stk_holdernumber_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    if anchor_date is not None:
        params["ann_date"] = anchor_date.strftime("%Y%m%d")

    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()

    ann_date = request.params.get("ann_date")
    if ann_date not in (None, ""):
        params["ann_date"] = _format_yyyymmdd(ann_date)

    enddate = request.params.get("enddate")
    if enddate not in (None, ""):
        params["enddate"] = _format_yyyymmdd(enddate)
    return params


def _dc_index_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    idx_type = enum_values.get("idx_type", request.params.get("idx_type"))
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    if idx_type not in (None, ""):
        params["idx_type"] = str(idx_type).strip()
    return params


def _index_daily_basic_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _index_daily_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    ts_code = enum_values.get("ts_code") or request.params.get("ts_code")
    if ts_code in (None, ""):
        raise ValueError("指数日线缺少指数代码")
    params: dict[str, Any] = {"ts_code": str(ts_code).strip().upper()}
    if request.run_profile == "point_incremental":
        if request.trade_date is None:
            raise ValueError("指数日线单日维护缺少交易日期")
        params["trade_date"] = request.trade_date.strftime("%Y%m%d")
        return params
    if request.run_profile == "range_rebuild":
        if request.start_date is None or request.end_date is None:
            raise ValueError("指数日线区间维护必须同时填写开始日期和结束日期")
        params["start_date"] = request.start_date.strftime("%Y%m%d")
        params["end_date"] = request.end_date.strftime("%Y%m%d")
        return params
    raise ValueError(f"指数日线不支持该运行模式：{request.run_profile}")


def _index_weight_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    index_code = enum_values.get("index_code") or request.params.get("index_code")
    if index_code in (None, ""):
        raise ValueError("指数权重缺少指数代码")

    params: dict[str, Any] = {"index_code": str(index_code).strip().upper()}
    if request.start_date is None or request.end_date is None:
        raise ValueError("指数权重区间维护必须同时填写开始日期和结束日期")
    params["start_date"] = request.start_date.strftime("%Y%m%d")
    params["end_date"] = request.end_date.strftime("%Y%m%d")
    return params


def _index_weekly_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    target_date = anchor_date or request.trade_date
    if target_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": target_date.strftime("%Y%m%d")}
    ts_code = enum_values.get("ts_code") or request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _index_monthly_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    target_date = anchor_date or request.trade_date
    if target_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": target_date.strftime("%Y%m%d")}
    ts_code = enum_values.get("ts_code") or request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _limit_list_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    limit_type = enum_values.get("limit_type", request.params.get("limit_type"))
    exchange = enum_values.get("exchange", request.params.get("exchange"))
    if _has_value(limit_type):
        params["limit_type"] = str(limit_type).strip().upper()
    if _has_value(exchange):
        params["exchange"] = str(exchange).strip().upper()
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _limit_list_ths_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    limit_type = enum_values.get("limit_type", request.params.get("limit_type"))
    market = enum_values.get("market", request.params.get("market"))
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    if limit_type not in (None, ""):
        params["limit_type"] = str(limit_type).strip()
    if market not in (None, ""):
        params["market"] = str(market).strip()
    return params


def _suspend_d_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    suspend_type = enum_values.get("suspend_type", request.params.get("suspend_type"))
    if suspend_type not in (None, ""):
        params["suspend_type"] = str(suspend_type).strip().upper()
    return params


def _cyq_perf_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _stk_factor_pro_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _margin_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    exchange_id = enum_values.get("exchange_id", request.params.get("exchange_id"))
    if _has_value(exchange_id):
        params["exchange_id"] = str(exchange_id).strip().upper()
    return params


def _limit_step_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
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
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _top_list_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _block_trade_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _stock_st_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _stk_nineturn_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d"), "freq": "daily"}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _dc_member_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = enum_values.get("ts_code") or request.params.get("ts_code")
    con_code = enum_values.get("con_code") or request.params.get("con_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    if con_code not in (None, ""):
        params["con_code"] = str(con_code).strip().upper()
    return params


def _ths_member_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    ts_code = enum_values.get("ts_code") or request.params.get("ts_code")
    con_code = enum_values.get("con_code") or request.params.get("con_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    if con_code not in (None, ""):
        params["con_code"] = str(con_code).strip().upper()
    return params


def _ths_daily_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    ts_code = enum_values.get("ts_code") or request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    if request.run_profile == "point_incremental":
        target_date = anchor_date or request.trade_date
        if target_date is None:
            raise ValueError("同花顺板块日线单日维护缺少交易日期")
        params["trade_date"] = target_date.strftime("%Y%m%d")
        return params
    if request.run_profile == "range_rebuild":
        if anchor_date is None:
            raise ValueError("同花顺板块日线区间维护缺少日期锚点")
        params["trade_date"] = anchor_date.strftime("%Y%m%d")
        return params
    raise ValueError(f"同花顺板块日线不支持该运行模式：{request.run_profile}")


def _dc_daily_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    ts_code = enum_values.get("ts_code") or request.params.get("ts_code")
    idx_type = enum_values.get("idx_type", request.params.get("idx_type"))
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    if idx_type not in (None, ""):
        params["idx_type"] = str(idx_type).strip()
    if request.run_profile == "point_incremental":
        target_date = anchor_date or request.trade_date
        if target_date is None:
            raise ValueError("东方财富板块日线单日维护缺少交易日期")
        params["trade_date"] = target_date.strftime("%Y%m%d")
        return params
    if request.run_profile == "range_rebuild":
        if anchor_date is None:
            raise ValueError("东方财富板块日线区间维护缺少日期锚点")
        params["trade_date"] = anchor_date.strftime("%Y%m%d")
        return params
    raise ValueError(f"东方财富板块日线不支持该运行模式：{request.run_profile}")


def _ths_hot_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    ts_code = request.params.get("ts_code")
    market = enum_values.get("market", request.params.get("market"))
    is_new = enum_values.get("is_new", request.params.get("is_new"))
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    if _has_value(market):
        params["market"] = str(market).strip()
    if _has_value(is_new):
        params["is_new"] = str(is_new).strip()
    if request.run_profile == "point_incremental":
        target_date = anchor_date or request.trade_date
        if target_date is None:
            raise ValueError("同花顺热榜单日维护缺少交易日期")
        params["trade_date"] = target_date.strftime("%Y%m%d")
        return params
    if request.run_profile == "range_rebuild":
        if anchor_date is None:
            raise ValueError("同花顺热榜区间维护缺少日期锚点")
        params["trade_date"] = anchor_date.strftime("%Y%m%d")
        return params
    raise ValueError(f"同花顺热榜不支持该运行模式：{request.run_profile}")


def _dc_hot_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {}
    ts_code = request.params.get("ts_code")
    market = enum_values.get("market", request.params.get("market"))
    hot_type = enum_values.get("hot_type", request.params.get("hot_type"))
    is_new = enum_values.get("is_new", request.params.get("is_new"))
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    if _has_value(market):
        params["market"] = str(market).strip()
    if _has_value(hot_type):
        params["hot_type"] = str(hot_type).strip()
    if _has_value(is_new):
        params["is_new"] = str(is_new).strip()
    if request.run_profile == "point_incremental":
        target_date = anchor_date or request.trade_date
        if target_date is None:
            raise ValueError("东方财富热榜单日维护缺少交易日期")
        params["trade_date"] = target_date.strftime("%Y%m%d")
        return params
    if request.run_profile == "range_rebuild":
        if anchor_date is None:
            raise ValueError("东方财富热榜区间维护缺少日期锚点")
        params["trade_date"] = anchor_date.strftime("%Y%m%d")
        return params
    raise ValueError(f"东方财富热榜不支持该运行模式：{request.run_profile}")


def _stk_period_bar_week_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {"freq": "week"}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    if request.run_profile == "point_incremental":
        target_date = anchor_date or request.trade_date
        if target_date is None:
            raise ValueError("股票周线单日维护缺少交易日期")
        params["trade_date"] = target_date.strftime("%Y%m%d")
        return params
    if request.run_profile == "range_rebuild":
        target_date = anchor_date
        if target_date is not None:
            params["trade_date"] = target_date.strftime("%Y%m%d")
        else:
            if request.start_date is None or request.end_date is None:
                raise ValueError("股票周线区间维护必须同时填写开始日期和结束日期")
            params["start_date"] = request.start_date.strftime("%Y%m%d")
            params["end_date"] = request.end_date.strftime("%Y%m%d")
        return params
    raise ValueError(f"股票周线不支持该运行模式：{request.run_profile}")


def _stk_period_bar_month_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    params = _stk_period_bar_week_params(request, anchor_date, enum_values)
    params["freq"] = "month"
    return params


def _stk_period_bar_adj_week_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return _stk_period_bar_week_params(request, anchor_date, enum_values)


def _stk_period_bar_adj_month_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return _stk_period_bar_month_params(request, anchor_date, enum_values)


def _moneyflow_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("个股资金流向缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _moneyflow_ind_dc_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("东方财富板块资金流缺少日期锚点")
    content_type = str(enum_values.get("content_type", request.params.get("content_type")) or "").strip()
    if not content_type:
        raise ValueError("东方财富板块资金流缺少类型展开参数")
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
        raise ValueError("同花顺个股资金流缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _moneyflow_dc_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("东方财富个股资金流缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _moneyflow_cnt_ths_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("同花顺概念资金流缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _moneyflow_ind_ths_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("同花顺行业资金流缺少日期锚点")
    params: dict[str, Any] = {"trade_date": anchor_date.strftime("%Y%m%d")}
    ts_code = request.params.get("ts_code")
    if ts_code not in (None, ""):
        params["ts_code"] = str(ts_code).strip().upper()
    return params


def _moneyflow_mkt_dc_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if anchor_date is None:
        raise ValueError("东方财富市场资金流缺少日期锚点")
    return {"trade_date": anchor_date.strftime("%Y%m%d")}


def _biying_equity_daily_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    dm = str(enum_values.get("dm") or request.params.get("dm") or "").strip().upper()
    if not dm:
        raise ValueError("Biying 股票日线缺少股票代码")
    adj_type = str(enum_values.get("adj_type") or request.params.get("adj_type") or "f").strip().lower()
    if adj_type not in {"n", "f", "b"}:
        raise ValueError("Biying 股票日线复权类型必须是 n、f 或 b")
    window_start = enum_values.get("window_start")
    window_end = enum_values.get("window_end")
    if isinstance(window_start, date) and isinstance(window_end, date):
        st = window_start
        et = window_end
    elif request.run_profile == "point_incremental":
        target_date = anchor_date or request.trade_date
        if target_date is None:
            raise ValueError("Biying 股票日线单日维护缺少交易日期")
        st = target_date
        et = target_date
    elif request.run_profile == "range_rebuild":
        if request.start_date is None or request.end_date is None:
            raise ValueError("Biying 股票日线区间维护必须同时填写开始日期和结束日期")
        st = request.start_date
        et = request.end_date
    else:
        raise ValueError(f"Biying 股票日线不支持该运行模式：{request.run_profile}")

    params: dict[str, Any] = {
        "dm": dm,
        "freq": "d",
        "adj_type": adj_type,
        "st": st.strftime("%Y%m%d"),
        "et": et.strftime("%Y%m%d"),
        "lt": "5000",
    }
    mc = enum_values.get("mc")
    if mc not in (None, ""):
        params["mc"] = str(mc).strip()
    return params


def _biying_moneyflow_params(request, anchor_date: date | None, enum_values: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    dm = str(enum_values.get("dm") or request.params.get("dm") or "").strip().upper()
    if not dm:
        raise ValueError("Biying 资金流缺少股票代码")
    window_start = enum_values.get("window_start")
    window_end = enum_values.get("window_end")
    if isinstance(window_start, date) and isinstance(window_end, date):
        st = window_start
        et = window_end
    elif request.run_profile == "point_incremental":
        target_date = anchor_date or request.trade_date
        if target_date is None:
            raise ValueError("Biying 资金流单日维护缺少交易日期")
        st = target_date
        et = target_date
    elif request.run_profile == "range_rebuild":
        if request.start_date is None or request.end_date is None:
            raise ValueError("Biying 资金流区间维护必须同时填写开始日期和结束日期")
        st = request.start_date
        et = request.end_date
    else:
        raise ValueError(f"Biying 资金流不支持该运行模式：{request.run_profile}")
    params: dict[str, Any] = {
        "dm": dm,
        "st": st.strftime("%Y%m%d"),
        "et": et.strftime("%Y%m%d"),
    }
    mc = enum_values.get("mc")
    if mc not in (None, ""):
        params["mc"] = str(mc).strip()
    return params

__all__ = [
    "ALL_LIMIT_LIST_EXCHANGES",
    "ALL_LIMIT_LIST_TYPES",
    "ALL_MARGIN_EXCHANGE_IDS",
    "ALL_MONEYFLOW_IND_DC_CONTENT_TYPES",
    "_trade_cal_params",
    "_stk_limit_params",
    "_stk_mins_params",
    "_daily_basic_params",
    "_daily_params",
    "_adj_factor_params",
    "_fund_daily_params",
    "_fund_adj_params",
    "_index_basic_params",
    "_etf_basic_params",
    "_etf_index_params",
    "_hk_basic_params",
    "_normalize_us_classify",
    "_us_basic_params",
    "_stock_basic_params",
    "_ths_index_params",
    "_kpl_list_params",
    "_kpl_concept_cons_params",
    "_broker_recommend_params",
    "_dividend_params",
    "_stk_holdernumber_params",
    "_dc_index_params",
    "_index_daily_basic_params",
    "_index_daily_params",
    "_index_weight_params",
    "_index_weekly_params",
    "_index_monthly_params",
    "_limit_list_params",
    "_limit_list_ths_params",
    "_suspend_d_params",
    "_cyq_perf_params",
    "_stk_factor_pro_params",
    "_margin_params",
    "_limit_step_params",
    "_limit_cpt_list_params",
    "_top_list_params",
    "_block_trade_params",
    "_stock_st_params",
    "_stk_nineturn_params",
    "_dc_member_params",
    "_ths_member_params",
    "_ths_daily_params",
    "_dc_daily_params",
    "_ths_hot_params",
    "_dc_hot_params",
    "_stk_period_bar_week_params",
    "_stk_period_bar_month_params",
    "_stk_period_bar_adj_week_params",
    "_stk_period_bar_adj_month_params",
    "_moneyflow_params",
    "_moneyflow_ind_dc_params",
    "_moneyflow_ths_params",
    "_moneyflow_dc_params",
    "_moneyflow_cnt_ths_params",
    "_moneyflow_ind_ths_params",
    "_moneyflow_mkt_dc_params",
    "_biying_equity_daily_params",
    "_biying_moneyflow_params",
]
