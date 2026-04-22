from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from src.foundation.services.transform.suspend_hash import build_suspend_d_row_key_hash
from src.foundation.services.transform.top_list_reason import hash_top_list_reason
from src.foundation.services.sync_v2.registry_parts.common.constants import MONEYFLOW_VOLUME_FIELDS
from src.utils import coerce_row

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


def _ths_hot_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["query_market"] = str(transformed.get("query_market") or "__ALL__")
    transformed["query_is_new"] = str(transformed.get("query_is_new") or "__ALL__")
    return transformed


def _dc_hot_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["query_market"] = str(transformed.get("query_market") or "__ALL__")
    transformed["query_hot_type"] = str(transformed.get("query_hot_type") or "__ALL__")
    transformed["query_is_new"] = str(transformed.get("query_is_new") or "__ALL__")
    return transformed


def _stk_period_bar_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["change_amount"] = transformed.get("change")
    return transformed


def _stk_period_bar_adj_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["change_amount"] = transformed.get("change")
    return transformed

__all__ = [
    "MONEYFLOW_VOLUME_FIELDS",
    "_moneyflow_row_transform",
    "_trade_cal_row_transform",
    "_suspend_d_row_transform",
    "_top_list_row_transform",
    "_daily_row_transform",
    "_fund_daily_row_transform",
    "_index_daily_row_transform",
    "_limit_list_row_transform",
    "_limit_list_ths_row_transform",
    "_ths_hot_row_transform",
    "_dc_hot_row_transform",
    "_stk_period_bar_row_transform",
    "_stk_period_bar_adj_row_transform",
]
