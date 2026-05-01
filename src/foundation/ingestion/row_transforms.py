from __future__ import annotations

from datetime import date
from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from typing import Any
from zoneinfo import ZoneInfo

from src.foundation.services.transform.suspend_hash import build_suspend_d_row_key_hash
from src.foundation.services.transform.top_list_reason import hash_top_list_reason
from src.foundation.services.transform.dividend_hash import build_dividend_event_key_hash, build_dividend_row_key_hash
from src.foundation.services.transform.holdernumber_hash import build_holdernumber_event_key_hash, build_holdernumber_row_key_hash
from src.foundation.ingestion.constants import MONEYFLOW_VOLUME_FIELDS
from src.utils import coerce_row


class RowTransformReject(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


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
            raise ValueError(f"资金流字段 `{field}` 必须是整数格式，实际值：{value}")
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


def _stock_basic_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    ts_code = str(transformed.get("ts_code") or "").strip().upper()
    dm = str(transformed.get("dm") or "").strip().upper()
    if ts_code:
        transformed["ts_code"] = ts_code
    if dm:
        transformed["dm"] = dm
    return transformed


def _hk_security_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["source"] = "tushare"
    return transformed


def _us_security_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["source"] = "tushare"
    return transformed


def _kpl_concept_cons_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    if transformed.get("con_name") in (None, "") and transformed.get("ts_name"):
        transformed["con_name"] = transformed["ts_name"]
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


def _cctv_news_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    title = str(transformed.get("title") or "").strip()
    content = str(transformed.get("content") or "").strip()
    transformed["title"] = title
    transformed["content"] = content
    date_value = transformed.get("date")
    date_text = date_value.isoformat() if isinstance(date_value, date) else str(date_value or "").strip()
    hash_input = "\x1f".join((date_text, title, content))
    transformed["row_key_hash"] = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    return transformed


def _parse_news_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("/", "-"))
        except ValueError as exc:
            raise RowTransformReject("invalid_pub_time", f"新闻发布时间格式无效：{value}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed


def _major_news_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    if "content" not in transformed:
        raise RowTransformReject("missing_content_field", "新闻通讯缺少 content 字段")
    src = str(transformed.get("src") or "").strip()
    title = str(transformed.get("title") or "").strip()
    content_value = transformed.get("content")
    content = None if content_value is None else str(content_value).strip()
    url = str(transformed.get("url") or "").strip() or None
    pub_time = _parse_news_datetime(transformed.get("pub_time"))
    if not src:
        raise RowTransformReject("missing_src", "新闻通讯来源为空")
    if pub_time is None:
        raise RowTransformReject("invalid_pub_time", "新闻发布时间为空")
    if not title:
        raise RowTransformReject("missing_title", "新闻通讯标题为空")
    transformed["src"] = src
    transformed["title"] = title
    transformed["content"] = content
    transformed["url"] = url
    transformed["pub_time"] = pub_time
    content_text = content or ""
    pub_time_text = pub_time.isoformat() if pub_time is not None else ""
    hash_input = "\x1f".join((src, pub_time_text, title, content_text))
    transformed["row_key_hash"] = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
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
    if transformed.get("query_limit_type") not in (None, ""):
        transformed["query_limit_type"] = str(transformed.get("query_limit_type"))
    if transformed.get("query_market") not in (None, ""):
        transformed["query_market"] = str(transformed.get("query_market"))
    return transformed


def _ths_hot_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    if transformed.get("query_market") not in (None, ""):
        transformed["query_market"] = str(transformed.get("query_market"))
    if transformed.get("query_is_new") not in (None, ""):
        transformed["query_is_new"] = str(transformed.get("query_is_new"))
    return transformed


def _dc_hot_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    if transformed.get("query_market") not in (None, ""):
        transformed["query_market"] = str(transformed.get("query_market"))
    if transformed.get("query_hot_type") not in (None, ""):
        transformed["query_hot_type"] = str(transformed.get("query_hot_type"))
    if transformed.get("query_is_new") not in (None, ""):
        transformed["query_is_new"] = str(transformed.get("query_is_new"))
    return transformed


def _stk_period_bar_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["change_amount"] = transformed.get("change")
    return transformed


def _stk_period_bar_adj_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["change_amount"] = transformed.get("change")
    return transformed


def _stk_mins_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    trade_time = _parse_quote_time(transformed.get("trade_time"))
    current_time = trade_time.time()
    is_trading_session = time(9, 30) <= current_time <= time(11, 30) or time(13, 0) <= current_time <= time(15, 0)
    if not is_trading_session:
        raise ValueError(f"股票分钟时间不在交易时段内：{trade_time}")

    freq = str(transformed.get("freq") or "").strip()
    freq_map = {"1min": 1, "5min": 5, "15min": 15, "30min": 30, "60min": 60}
    if freq not in freq_map:
        raise ValueError(f"股票分钟频率无效：{freq}")

    transformed["ts_code"] = str(transformed.get("ts_code") or "").strip().upper()
    transformed["freq"] = freq_map[freq]
    transformed["trade_time"] = trade_time
    transformed["open"] = _optional_float(transformed.get("open"), ndigits=2)
    transformed["close"] = _optional_float(transformed.get("close"), ndigits=2)
    transformed["high"] = _optional_float(transformed.get("high"), ndigits=2)
    transformed["low"] = _optional_float(transformed.get("low"), ndigits=2)
    transformed["vol"] = _optional_int(transformed.get("vol"))
    transformed["amount"] = _optional_float(transformed.get("amount"))
    transformed.pop("trade_date", None)
    transformed.pop("session_tag", None)
    transformed.pop("api_name", None)
    transformed.pop("fetched_at", None)
    transformed.pop("raw_payload", None)
    return transformed


def _optional_float(value: Any, *, ndigits: int | None = None) -> float | None:
    if value in (None, ""):
        return None
    if ndigits is None:
        return float(value)
    quantize_unit = Decimal("1").scaleb(-ndigits)
    return float(Decimal(str(value)).quantize(quantize_unit, rounding=ROUND_HALF_UP))


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    decimal_value = Decimal(str(value))
    if decimal_value != decimal_value.to_integral_value():
        raise ValueError(f"股票分钟成交量必须是整数格式，实际值：{value}")
    return int(decimal_value)


def _dividend_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    if transformed.get("div_proc") == "实施" and transformed.get("ex_date") is None:
        stk_div = transformed.get("stk_div")
        cash_div = transformed.get("cash_div")
        record_date = transformed.get("record_date")
        pay_date = transformed.get("pay_date")
        if stk_div is not None and stk_div > 0 and record_date is not None:
            transformed["ex_date"] = record_date
        elif stk_div is not None and stk_div == 0 and cash_div is not None and cash_div > 0 and pay_date is not None:
            transformed["ex_date"] = pay_date
    transformed["row_key_hash"] = build_dividend_row_key_hash(transformed)
    transformed["event_key_hash"] = build_dividend_event_key_hash(transformed)
    return transformed


def _holdernumber_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["row_key_hash"] = build_holdernumber_row_key_hash(transformed)
    transformed["event_key_hash"] = build_holdernumber_event_key_hash(transformed)
    return transformed


_BIYING_MONEYFLOW_INT_FIELDS = (
    "zmbzds",
    "zmszds",
    "zmbzdszl",
    "zmszdszl",
    "cjbszl",
    "zmbtdcjl",
    "zmbddcjl",
    "zmbzdcjl",
    "zmbxdcjl",
    "zmstdcjl",
    "zmsddcjl",
    "zmszdcjl",
    "zmsxdcjl",
    "bdmbtdcjl",
    "bdmbddcjl",
    "bdmbzdcjl",
    "bdmbxdcjl",
    "bdmstdcjl",
    "bdmsddcjl",
    "bdmszdcjl",
    "bdmsxdcjl",
    "zmbtdcjzlv",
    "zmbddcjzlv",
    "zmbzdcjzlv",
    "zmbxdcjzlv",
    "zmstdcjzlv",
    "zmsddcjzlv",
    "zmszdcjzlv",
    "zmsxdcjzlv",
    "bdmbtdcjzlv",
    "bdmbddcjzlv",
    "bdmbzdcjzlv",
    "bdmbxdcjzlv",
    "bdmstdcjzlv",
    "bdmsddcjzlv",
    "bdmszdcjzlv",
    "bdmsxdcjzlv",
)

_BIYING_MONEYFLOW_DECIMAL_FIELDS = (
    "dddx",
    "zddy",
    "ddcf",
    "zmbtdcje",
    "zmbddcje",
    "zmbzdcje",
    "zmbxdcje",
    "zmstdcje",
    "zmsddcje",
    "zmszdcje",
    "zmsxdcje",
    "bdmbtdcje",
    "bdmbddcje",
    "bdmbzdcje",
    "bdmbxdcje",
    "bdmstdcje",
    "bdmsddcje",
    "bdmszdcje",
    "bdmsxdcje",
    "zmbtdcjzl",
    "zmbddcjzl",
    "zmbzdcjzl",
    "zmbxdcjzl",
    "zmstdcjzl",
    "zmsddcjzl",
    "zmszdcjzl",
    "zmsxdcjzl",
    "bdmbtdcjzl",
    "bdmbddcjzl",
    "bdmbzdcjzl",
    "bdmbxdcjzl",
    "bdmstdcjzl",
    "bdmsddcjzl",
    "bdmszdcjzl",
    "bdmsxdcjzl",
)


def _parse_quote_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _to_int_like(value: Any) -> int | None:
    if value in (None, ""):
        return None
    decimal_value = Decimal(str(value))
    if decimal_value != decimal_value.to_integral_value():
        raise ValueError(f"值必须是整数格式，实际值：{value}")
    return int(decimal_value)


def _biying_equity_daily_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    quote_time = _parse_quote_time(transformed.get("t"))
    return {
        "dm": str(transformed.get("dm") or "").strip().upper(),
        "trade_date": quote_time.date(),
        "adj_type": str(transformed.get("adj_type") or "").strip().lower(),
        "mc": transformed.get("mc"),
        "quote_time": quote_time,
        "open": transformed.get("o"),
        "high": transformed.get("h"),
        "low": transformed.get("l"),
        "close": transformed.get("c"),
        "pre_close": transformed.get("pc"),
        "vol": transformed.get("v"),
        "amount": transformed.get("a"),
        "suspend_flag": _to_int_like(transformed.get("sf")),
        "raw_payload": json.dumps(transformed, ensure_ascii=False, default=str),
    }


def _biying_moneyflow_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    quote_time = _parse_quote_time(transformed.get("t"))
    normalized: dict[str, Any] = {
        "dm": str(transformed.get("dm") or "").strip().upper(),
        "trade_date": quote_time.date(),
        "mc": transformed.get("mc"),
        "quote_time": quote_time,
        "raw_payload": json.dumps(transformed, ensure_ascii=False, default=str),
    }
    for field_name in _BIYING_MONEYFLOW_INT_FIELDS:
        normalized[field_name] = _to_int_like(transformed.get(field_name))
    for field_name in _BIYING_MONEYFLOW_DECIMAL_FIELDS:
        normalized[field_name] = transformed.get(field_name)
    return normalized

__all__ = [
    "MONEYFLOW_VOLUME_FIELDS",
    "RowTransformReject",
    "_moneyflow_row_transform",
    "_trade_cal_row_transform",
    "_stock_basic_row_transform",
    "_hk_security_row_transform",
    "_us_security_row_transform",
    "_kpl_concept_cons_row_transform",
    "_suspend_d_row_transform",
    "_top_list_row_transform",
    "_daily_row_transform",
    "_cctv_news_row_transform",
    "_major_news_row_transform",
    "_fund_daily_row_transform",
    "_index_daily_row_transform",
    "_limit_list_row_transform",
    "_limit_list_ths_row_transform",
    "_ths_hot_row_transform",
    "_dc_hot_row_transform",
    "_stk_period_bar_row_transform",
    "_stk_period_bar_adj_row_transform",
    "_stk_mins_row_transform",
    "_dividend_row_transform",
    "_holdernumber_row_transform",
    "_biying_equity_daily_row_transform",
    "_biying_moneyflow_row_transform",
]
