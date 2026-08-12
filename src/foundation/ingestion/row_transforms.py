from __future__ import annotations

from datetime import date
from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math
from typing import Any
from zoneinfo import ZoneInfo

from src.foundation.services.transform.suspend_hash import build_suspend_d_row_key_hash
from src.foundation.services.transform.top_list_reason import hash_top_list_reason
from src.foundation.services.transform.top_list_payload import build_top_list_payload_hash
from src.foundation.services.transform.dividend_hash import build_dividend_event_key_hash, build_dividend_row_key_hash
from src.foundation.services.transform.holdernumber_hash import build_holdernumber_event_key_hash, build_holdernumber_row_key_hash
from src.foundation.ingestion.constants import MONEYFLOW_VOLUME_FIELDS
from src.foundation.datasets.public_fund_contracts import (
    fund_basic_identity,
    fund_company_identity,
    fund_div_identity,
    fund_manager_identity,
    fund_share_identity,
    mkt_idx_bmk_identity,
)


class RowTransformReject(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


_TOP_LIST_PSEUDO_NULL_NUMBER_TEXTS = {"nan", "nat", "none", "null"}


def _strip_nul_text(value: Any) -> str:
    return str(value or "").replace("\x00", "")


def _normalize_top_list_optional_number(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return None if value.is_nan() else value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    text = str(value).strip()
    if not text or text.lower() in _TOP_LIST_PSEUDO_NULL_NUMBER_TEXTS:
        return None
    return value


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


def _fund_company_observed_snapshot_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    source_entity_key, identity_basis = fund_company_identity(transformed)
    transformed["source_entity_key"] = source_entity_key
    transformed["identity_basis"] = identity_basis
    return transformed


def _mkt_idx_bmk_observed_snapshot_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    source_entity_key, identity_basis = mkt_idx_bmk_identity(transformed)
    transformed["source_entity_key"] = source_entity_key
    transformed["identity_basis"] = identity_basis
    return transformed


def _fund_basic_observed_snapshot_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    source_entity_key, identity_basis = fund_basic_identity(transformed)
    transformed["source_entity_key"] = source_entity_key
    transformed["identity_basis"] = identity_basis
    return transformed


def _fund_manager_observed_snapshot_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    source_entity_key, identity_basis, manager_identity_key = fund_manager_identity(transformed)
    transformed["source_entity_key"] = source_entity_key
    transformed["identity_basis"] = identity_basis
    transformed["manager_identity_key"] = manager_identity_key
    return transformed


def _fund_share_observed_fact_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    source_entity_key, identity_basis = fund_share_identity(transformed)
    transformed["source_entity_key"] = source_entity_key
    transformed["identity_basis"] = identity_basis
    return transformed


_FUND_DIV_NUMERIC_FIELDS = ("div_cash", "base_unit", "ear_distr", "ear_amount")

_EXPRESS_IDENTITY_BASIS = "ts_code_ann_date_end_date"


def _fund_div_immutable_fact_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    for field_name in _FUND_DIV_NUMERIC_FIELDS:
        value = transformed.get(field_name)
        if value is None:
            continue
        if not _decimal_fits_numeric_30_10(value):
            raise RowTransformReject(
                f"normalize.numeric_precision_overflow:{field_name}",
                f"字段 {field_name} 无法由 NUMERIC(30,10) 精确保存",
            )
    source_entity_key, identity_basis = fund_div_identity(transformed)
    transformed["source_entity_key"] = source_entity_key
    transformed["identity_basis"] = identity_basis
    return transformed


def _express_immutable_fact_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    ts_code = str(transformed.get("ts_code") or "").strip().upper()
    ann_date = transformed.get("ann_date")
    end_date = transformed.get("end_date")
    if not ts_code:
        raise RowTransformReject("normalize.empty_not_allowed:ts_code", "字段 ts_code 不允许为空")
    if not isinstance(ann_date, date):
        raise RowTransformReject("normalize.empty_not_allowed:ann_date", "字段 ann_date 不允许为空")
    if not isinstance(end_date, date):
        raise RowTransformReject("normalize.empty_not_allowed:end_date", "字段 end_date 不允许为空")
    identity_payload = json.dumps(
        [ts_code, ann_date.isoformat(), end_date.isoformat()],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    transformed["source_entity_key"] = f"express:{hashlib.sha256(identity_payload.encode('utf-8')).hexdigest()}"
    transformed["identity_basis"] = _EXPRESS_IDENTITY_BASIS
    return transformed


def _fund_portfolio_staged_fact_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    ts_code = str(transformed.get("ts_code") or "").strip().upper()
    symbol = str(transformed.get("symbol") or "").strip()
    if ts_code:
        transformed["ts_code"] = ts_code
    if symbol:
        transformed["symbol"] = symbol
    return transformed


def _decimal_fits_numeric_30_10(value: Decimal) -> bool:
    if not value.is_finite():
        return False
    normalized = value.normalize()
    if normalized.is_zero():
        return True
    sign, digits, exponent = normalized.as_tuple()
    del sign
    integer_digits = max(len(digits) + exponent, 0)
    fractional_digits = max(-exponent, 0)
    return integer_digits <= 20 and fractional_digits <= 10


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


def _bse_mapping_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    for key in ("o_code", "n_code"):
        value = transformed.get(key)
        if value not in (None, ""):
            transformed[key] = str(value).strip().upper()
    return transformed


def _stock_company_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    ts_code = str(transformed.get("ts_code") or "").strip().upper()
    exchange = str(transformed.get("exchange") or "").strip().upper()
    if ts_code:
        transformed["ts_code"] = ts_code
    if exchange:
        transformed["exchange"] = exchange
    return transformed


def _bak_basic_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    ts_code = str(transformed.get("ts_code") or "").strip().upper()
    if ts_code:
        transformed["ts_code"] = ts_code
    for key in ("name", "industry", "area"):
        value = transformed.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        transformed[key] = normalized or None
    return transformed


def _namechange_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    ts_code = str(transformed.get("ts_code") or "").strip().upper()
    name = str(transformed.get("name") or "").strip()
    change_reason = str(transformed.get("change_reason") or "").strip() or None
    if ts_code:
        transformed["ts_code"] = ts_code
    if name:
        transformed["name"] = name
    transformed["change_reason"] = change_reason
    hash_input = "\x1f".join(
        (
            "namechange",
            transformed.get("ts_code") or "",
            transformed.get("name") or "",
            transformed["start_date"].isoformat() if transformed.get("start_date") is not None else "",
            transformed["end_date"].isoformat() if transformed.get("end_date") is not None else "",
            transformed["ann_date"].isoformat() if transformed.get("ann_date") is not None else "",
            change_reason or "",
        )
    )
    transformed["row_key_hash"] = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    return transformed


def _st_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    ts_code = str(transformed.get("ts_code") or "").strip().upper()
    name_value = transformed.get("name")
    name = None if name_value is None else str(name_value).strip() or None
    st_type = str(transformed.get("st_type") or "").strip()
    st_reason = str(transformed.get("st_reason") or "").strip() or None
    st_explain = str(transformed.get("st_explain") or "").strip() or None
    if ts_code:
        transformed["ts_code"] = ts_code
    transformed["name"] = name
    if st_type:
        transformed["st_type"] = st_type
    transformed["st_reason"] = st_reason
    transformed["st_explain"] = st_explain
    hash_input = "\x1f".join(
        (
            "st",
            transformed.get("ts_code") or "",
            transformed["pub_date"].isoformat() if transformed.get("pub_date") is not None else "",
            transformed["imp_date"].isoformat() if transformed.get("imp_date") is not None else "",
            transformed.get("st_type") or "",
            st_reason or "",
            st_explain or "",
            name or "",
        )
    )
    transformed["row_key_hash"] = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
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
    transformed["float_values"] = _normalize_top_list_optional_number(transformed.get("float_values"))
    transformed["reason_hash"] = hash_top_list_reason(transformed.get("reason"))
    transformed["payload_hash"] = build_top_list_payload_hash(transformed)
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


def _parse_news_datetime(value: Any, *, field_name: str = "pub_time", display_name: str = "新闻发布时间") -> datetime | None:
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
            raise RowTransformReject(f"normalize.invalid_date:{field_name}", f"{display_name}格式无效：{value}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed


def _normalize_news_datetime_input(value: Any) -> Any:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in _TOP_LIST_PSEUDO_NULL_NUMBER_TEXTS:
        return None
    return value


def _major_news_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    if "content" not in transformed:
        raise RowTransformReject("normalize.required_field_missing:content", "新闻通讯缺少 content 字段")
    src = str(transformed.get("src") or "").strip()
    title = str(transformed.get("title") or "").strip() or None
    content_value = transformed.get("content")
    content = None if content_value is None else str(content_value).strip() or None
    url = str(transformed.get("url") or "").strip() or None
    pub_time = _parse_news_datetime(transformed.get("pub_time"))
    if not src:
        raise RowTransformReject("normalize.required_field_missing:src", "新闻通讯来源为空")
    if pub_time is None:
        raise RowTransformReject("normalize.required_field_missing:pub_time", "新闻发布时间为空")
    if title is None and content is None:
        raise RowTransformReject("normalize.empty_not_allowed:title_content", "新闻通讯标题与正文不能同时为空")
    transformed["src"] = src
    transformed["title"] = title
    transformed["content"] = content
    transformed["url"] = url
    transformed["pub_time"] = pub_time
    content_text = content or ""
    title_text = title or ""
    url_text = url or ""
    pub_time_text = pub_time.isoformat() if pub_time is not None else ""
    hash_input = "\x1f".join(("major_news", src, pub_time_text, title_text, content_text, url_text))
    transformed["row_key_hash"] = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    return transformed


def _news_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    src = _strip_nul_text(transformed.get("src")).strip()
    title = _strip_nul_text(transformed.get("title")).strip() or None
    content_value = transformed.get("content")
    content = None if content_value is None else _strip_nul_text(content_value).strip() or None
    channels = _strip_nul_text(transformed.get("channels")).strip() or None
    score = _strip_nul_text(transformed.get("score")).strip() or None
    news_time = _parse_news_datetime(
        transformed.get("datetime"),
        field_name="news_time",
        display_name="新闻时间",
    )
    if not src:
        raise RowTransformReject("normalize.required_field_missing:src", "新闻快讯来源为空")
    if news_time is None:
        raise RowTransformReject("normalize.required_field_missing:news_time", "新闻时间为空")
    if title is None and content is None:
        raise RowTransformReject("normalize.empty_not_allowed:title_content", "新闻快讯标题与正文不能同时为空")
    transformed["src"] = src
    transformed["news_time"] = news_time
    transformed["title"] = title
    transformed["content"] = content
    transformed["channels"] = channels
    transformed["score"] = score
    hash_input = "\x1f".join(
        (
            "news",
            src,
            news_time.isoformat(),
            title or "",
            content or "",
            channels or "",
            score or "",
        )
    )
    transformed["row_key_hash"] = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    return transformed


def _anns_d_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    ann_date = transformed.get("ann_date")
    ts_code = _strip_nul_text(transformed.get("ts_code")).strip().upper()
    name = _strip_nul_text(transformed.get("name")).strip() or None
    title = _strip_nul_text(transformed.get("title")).strip()
    url = _strip_nul_text(transformed.get("url")).strip()
    rec_time = _parse_news_datetime(
        _normalize_news_datetime_input(transformed.get("rec_time")),
        field_name="rec_time",
        display_name="公告收录时间",
    )
    if ann_date is None:
        raise RowTransformReject("normalize.required_field_missing:ann_date", "上市公司公告缺少 ann_date")
    if not ts_code:
        raise RowTransformReject("normalize.required_field_missing:ts_code", "上市公司公告缺少 ts_code")
    if not title:
        raise RowTransformReject("normalize.required_field_missing:title", "上市公司公告缺少 title")
    if not url:
        raise RowTransformReject("normalize.required_field_missing:url", "上市公司公告缺少 url")
    if rec_time is None:
        raise RowTransformReject("normalize.required_field_missing:rec_time", "上市公司公告缺少 rec_time")
    ann_date_text = ann_date.isoformat() if isinstance(ann_date, date) else str(ann_date)
    transformed["ann_date"] = ann_date
    transformed["ts_code"] = ts_code
    transformed["name"] = name
    transformed["title"] = title
    transformed["url"] = url
    transformed["rec_time"] = rec_time
    hash_input = "\x1f".join(("anns_d", ann_date_text, ts_code, title, url, rec_time.isoformat()))
    transformed["row_key_hash"] = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    return transformed


def _irm_qa_sh_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    trade_date = transformed.get("trade_date")
    ts_code = _strip_nul_text(transformed.get("ts_code")).strip().upper()
    name = _strip_nul_text(transformed.get("name")).strip() or None
    question = _strip_nul_text(transformed.get("q")).strip()
    answer = _strip_nul_text(transformed.get("a")).strip()
    pub_time = _parse_news_datetime(
        _normalize_news_datetime_input(transformed.get("pub_time")),
        field_name="pub_time",
        display_name="互动问答发布时间",
    )
    if trade_date is None:
        raise RowTransformReject("normalize.required_field_missing:trade_date", "上证E互动问答缺少 trade_date")
    if not ts_code:
        raise RowTransformReject("normalize.required_field_missing:ts_code", "上证E互动问答缺少 ts_code")
    if not question:
        raise RowTransformReject("normalize.required_field_missing:q", "上证E互动问答缺少 q")
    if not answer:
        raise RowTransformReject("normalize.required_field_missing:a", "上证E互动问答缺少 a")
    trade_date_text = trade_date.isoformat() if isinstance(trade_date, date) else str(trade_date)
    transformed["trade_date"] = trade_date
    transformed["ts_code"] = ts_code
    transformed["name"] = name
    transformed["q"] = question
    transformed["a"] = answer
    transformed["pub_time"] = pub_time
    hash_input = "\x1f".join(
        (
            "irm_qa_sh",
            ts_code,
            trade_date_text,
            pub_time.isoformat() if pub_time is not None else "",
            question,
            answer,
        )
    )
    transformed["row_key_hash"] = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    return transformed


def _irm_qa_sz_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    trade_date = transformed.get("trade_date")
    ts_code = _strip_nul_text(transformed.get("ts_code")).strip().upper()
    name = _strip_nul_text(transformed.get("name")).strip() or None
    question = _strip_nul_text(transformed.get("q")).strip()
    answer = _strip_nul_text(transformed.get("a")).strip()
    pub_time = _parse_news_datetime(
        _normalize_news_datetime_input(transformed.get("pub_time")),
        field_name="pub_time",
        display_name="互动易问答发布时间",
    )
    industry = _strip_nul_text(transformed.get("industry")).strip() or None
    if trade_date is None:
        raise RowTransformReject("normalize.required_field_missing:trade_date", "深证互动易问答缺少 trade_date")
    if not ts_code:
        raise RowTransformReject("normalize.required_field_missing:ts_code", "深证互动易问答缺少 ts_code")
    if not question:
        raise RowTransformReject("normalize.required_field_missing:q", "深证互动易问答缺少 q")
    if not answer:
        raise RowTransformReject("normalize.required_field_missing:a", "深证互动易问答缺少 a")
    trade_date_text = trade_date.isoformat() if isinstance(trade_date, date) else str(trade_date)
    transformed["trade_date"] = trade_date
    transformed["ts_code"] = ts_code
    transformed["name"] = name
    transformed["q"] = question
    transformed["a"] = answer
    transformed["pub_time"] = pub_time
    transformed["industry"] = industry
    hash_input = "\x1f".join(
        (
            "irm_qa_sz",
            ts_code,
            trade_date_text,
            pub_time.isoformat() if pub_time is not None else "",
            question,
            answer,
        )
    )
    transformed["row_key_hash"] = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    return transformed


def _research_report_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    trade_date = transformed.get("trade_date")
    report_code = _strip_nul_text(transformed.get("report_code")).strip() or None
    title = _strip_nul_text(transformed.get("title")).strip() or None
    report_type = _strip_nul_text(transformed.get("report_type")).strip() or None
    inst_csname = _strip_nul_text(transformed.get("inst_csname")).strip() or None
    url = _strip_nul_text(transformed.get("url")).strip()
    ts_code = _strip_nul_text(transformed.get("ts_code")).strip().upper() or None
    author = _strip_nul_text(transformed.get("author")).strip() or None
    name = _strip_nul_text(transformed.get("name")).strip() or None
    ind_name = _strip_nul_text(transformed.get("ind_name")).strip() or None
    abstr = _strip_nul_text(transformed.get("abstr")).strip() or None

    if not url:
        raise RowTransformReject("normalize.required_field_missing:url", "券商研究报告缺少 url")

    trade_date_text = trade_date.isoformat() if isinstance(trade_date, date) else (str(trade_date) if trade_date is not None else "")
    if report_code:
        hash_parts = ("research_report", "report_code", report_code)
    else:
        hash_parts = (
            "research_report",
            "fallback",
            trade_date_text,
            title or "",
            report_type or "",
            inst_csname or "",
            author or "",
            ts_code or "",
            ind_name or "",
            url,
        )

    transformed["trade_date"] = trade_date
    transformed["report_code"] = report_code
    transformed["title"] = title
    transformed["report_type"] = report_type
    transformed["inst_csname"] = inst_csname
    transformed["url"] = url
    transformed["ts_code"] = ts_code
    transformed["author"] = author
    transformed["name"] = name
    transformed["ind_name"] = ind_name
    transformed["abstr"] = abstr
    transformed["row_key_hash"] = hashlib.sha256("\x1f".join(hash_parts).encode("utf-8")).hexdigest()
    return transformed


def _fund_daily_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    transformed["change_amount"] = transformed.get("change")
    return transformed


def _etf_sh_cons_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    for field in ("ts_code", "con_code", "exchange"):
        value = _strip_nul_text(transformed.get(field)).strip().upper()
        transformed[field] = value if field in ("ts_code", "con_code") else value or None
    for field in ("con_name", "sub_flag", "cpr", "rdr", "sca"):
        value = _strip_nul_text(transformed.get(field)).strip()
        transformed[field] = value or None
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


def _index_mins_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(row)
    trade_time = _parse_quote_time(transformed.get("trade_time"))
    current_time = trade_time.time()
    is_trading_session = time(9, 30) <= current_time <= time(11, 30) or time(13, 0) <= current_time <= time(15, 0)
    if not is_trading_session:
        raise ValueError(f"指数分钟时间不在交易时段内：{trade_time}")

    freq = str(transformed.get("freq") or "").strip()
    allowed_freqs = {"1min", "5min", "15min", "30min", "60min"}
    if freq not in allowed_freqs:
        raise ValueError(f"指数分钟频率无效：{freq}")

    exchange = transformed.get("exchange")
    return {
        "ts_code": str(transformed.get("ts_code") or "").strip().upper(),
        "trade_time": trade_time,
        "close": _optional_float(transformed.get("close")),
        "open": _optional_float(transformed.get("open")),
        "high": _optional_float(transformed.get("high")),
        "low": _optional_float(transformed.get("low")),
        "vol": _optional_float(transformed.get("vol")),
        "amount": _optional_float(transformed.get("amount")),
        "freq": freq,
        "exchange": str(exchange).strip().upper() if exchange not in (None, "") else None,
        "vwap": _optional_float(transformed.get("vwap")),
    }


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
    "_fund_company_observed_snapshot_row_transform",
    "_mkt_idx_bmk_observed_snapshot_row_transform",
    "_fund_basic_observed_snapshot_row_transform",
    "_fund_manager_observed_snapshot_row_transform",
    "_fund_share_observed_fact_row_transform",
    "_fund_div_immutable_fact_row_transform",
    "_express_immutable_fact_row_transform",
    "_fund_portfolio_staged_fact_row_transform",
    "_trade_cal_row_transform",
    "_stock_basic_row_transform",
    "_bse_mapping_row_transform",
    "_stock_company_row_transform",
    "_bak_basic_row_transform",
    "_namechange_row_transform",
    "_st_row_transform",
    "_hk_security_row_transform",
    "_us_security_row_transform",
    "_kpl_concept_cons_row_transform",
    "_suspend_d_row_transform",
    "_top_list_row_transform",
    "_daily_row_transform",
    "_cctv_news_row_transform",
    "_major_news_row_transform",
    "_news_row_transform",
    "_anns_d_row_transform",
    "_irm_qa_sh_row_transform",
    "_irm_qa_sz_row_transform",
    "_research_report_row_transform",
    "_fund_daily_row_transform",
    "_etf_sh_cons_row_transform",
    "_index_daily_row_transform",
    "_limit_list_row_transform",
    "_limit_list_ths_row_transform",
    "_ths_hot_row_transform",
    "_dc_hot_row_transform",
    "_stk_period_bar_row_transform",
    "_stk_period_bar_adj_row_transform",
    "_stk_mins_row_transform",
    "_index_mins_row_transform",
    "_dividend_row_transform",
    "_holdernumber_row_transform",
    "_biying_equity_daily_row_transform",
    "_biying_moneyflow_row_transform",
]
