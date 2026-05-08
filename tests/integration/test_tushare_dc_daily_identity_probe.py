from __future__ import annotations

from collections import defaultdict
import csv
from datetime import date, timedelta
import json
import os
from pathlib import Path
import time
from typing import Any

import pytest
import tushare as ts

from src.foundation.config.settings import get_settings


_RUN_FLAG = "RUN_TUSHARE_DC_DAILY_IDENTITY_PROBE"
_START_DATE = os.getenv("DC_DAILY_PROBE_START_DATE", "20250619").strip()
_END_DATE = os.getenv("DC_DAILY_PROBE_END_DATE", _START_DATE).strip()
_REQUEST_MODE = os.getenv("DC_DAILY_PROBE_REQUEST_MODE", "all").strip().lower()
_IDX_TYPES = tuple(
    item.strip()
    for item in os.getenv("DC_DAILY_PROBE_IDX_TYPES", "行业板块,概念板块,地域板块").split(",")
    if item.strip()
)
_PAGE_LIMIT = int(os.getenv("DC_DAILY_PROBE_PAGE_LIMIT", "2000"))
_MAX_CALLS_PER_MINUTE = int(os.getenv("DC_DAILY_PROBE_MAX_CALLS_PER_MINUTE", "100"))
_REPORT_DIR = Path(
    os.getenv(
        "DC_DAILY_PROBE_REPORT_DIR",
        f"reports/dc_daily_identity_probe_{_START_DATE}_{_END_DATE}_{_REQUEST_MODE}",
    )
)

_FIELDS = (
    "ts_code",
    "trade_date",
    "close",
    "open",
    "high",
    "low",
    "change",
    "pct_change",
    "vol",
    "amount",
    "swing",
    "turnover_rate",
    "category",
)
_BUSINESS_FIELDS = (
    "close",
    "open",
    "high",
    "low",
    "change",
    "pct_change",
    "vol",
    "amount",
    "swing",
    "turnover_rate",
)
_REPORT_FIELDS = (
    "probe_scope",
    "request_idx_type",
    *_FIELDS,
)


class _MinuteRateLimiter:
    def __init__(self, max_calls_per_minute: int) -> None:
        self.max_calls = max(max_calls_per_minute, 0)
        self.window_seconds = 60.0
        self.calls: list[float] = []

    def acquire(self) -> None:
        if self.max_calls <= 0:
            return
        while True:
            now = time.monotonic()
            self.calls = [item for item in self.calls if now - item < self.window_seconds]
            if len(self.calls) < self.max_calls:
                self.calls.append(now)
                return
            sleep_seconds = self.window_seconds - (now - self.calls[0]) + 0.05
            time.sleep(max(sleep_seconds, 0.05))


def _parse_yyyymmdd(value: str) -> date:
    normalized = value.strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid yyyymmdd: {value}")
    return date.fromisoformat(f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:8]}")


def _iter_dates(start_date: date, end_date: date) -> list[date]:
    dates: list[date] = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def _request_idx_types() -> list[str]:
    if _REQUEST_MODE == "all":
        return [""]
    if _REQUEST_MODE == "explicit_types":
        return list(_IDX_TYPES)
    if _REQUEST_MODE == "both":
        return ["", *list(_IDX_TYPES)]
    raise ValueError("DC_DAILY_PROBE_REQUEST_MODE must be one of: all, explicit_types, both")


def _normalize_scalar(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _scope_for_idx_type(idx_type: str) -> str:
    return "all_request" if not idx_type else "explicit_idx_type"


def _fetch_date_rows(
    pro_api,
    limiter: _MinuteRateLimiter,
    *,
    trade_date_text: str,
    idx_type: str,
) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        limiter.acquire()
        params: dict[str, Any] = {
            "trade_date": trade_date_text,
            "limit": _PAGE_LIMIT,
            "offset": offset,
        }
        if idx_type:
            params["idx_type"] = idx_type
        frame = pro_api.dc_daily(
            **params,
            fields=",".join(_FIELDS),
        )
        page_rows = [] if frame is None else frame.to_dict(orient="records")
        for row in page_rows:
            item = dict(row)
            item["probe_scope"] = _scope_for_idx_type(idx_type)
            item["request_idx_type"] = idx_type
            rows.append(item)
        if len(page_rows) < _PAGE_LIMIT:
            return rows
        offset += _PAGE_LIMIT


def _diff_fields(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[str]:
    differing_fields: list[str] = []
    for field in fields:
        values = {_normalize_scalar(row.get(field)) for row in rows}
        if len(values) > 1:
            differing_fields.append(field)
    return differing_fields


def _group_key(row: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_normalize_scalar(row.get(field)).upper() for field in fields)


def _summarize_duplicate_groups(
    rows: list[dict[str, Any]],
    *,
    identity_fields: tuple[str, ...],
    scope: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    scoped_rows = [row for row in rows if row.get("probe_scope") == scope]
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in scoped_rows:
        groups[_group_key(row, identity_fields)].append(row)

    group_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    duplicate_groups = 0
    duplicate_rows_beyond_first = 0
    groups_with_category_conflict = 0
    groups_with_request_idx_type_conflict = 0
    groups_with_business_conflict = 0

    for group_index, (key, bucket) in enumerate(
        ((key, bucket) for key, bucket in sorted(groups.items()) if len(bucket) > 1),
        start=1,
    ):
        duplicate_groups += 1
        duplicate_rows_beyond_first += len(bucket) - 1
        category_values = sorted({_normalize_scalar(row.get("category")) for row in bucket if _normalize_scalar(row.get("category"))})
        request_idx_type_values = sorted(
            {_normalize_scalar(row.get("request_idx_type")) for row in bucket if _normalize_scalar(row.get("request_idx_type"))}
        )
        differing_business_fields = _diff_fields(bucket, _BUSINESS_FIELDS)
        if len(category_values) > 1:
            groups_with_category_conflict += 1
        if len(request_idx_type_values) > 1:
            groups_with_request_idx_type_conflict += 1
        if differing_business_fields:
            groups_with_business_conflict += 1

        group_id = f"{scope}-{group_index:06d}"
        group_row = {
            "group_id": group_id,
            "scope": scope,
            "identity_fields": ",".join(identity_fields),
            "identity_key": "|".join(key),
            "row_count": len(bucket),
            "category_values": " | ".join(category_values),
            "request_idx_type_values": " | ".join(request_idx_type_values),
            "differing_business_fields": ",".join(differing_business_fields),
        }
        for field_name, field_value in zip(identity_fields, key, strict=True):
            group_row[field_name] = field_value
        group_rows.append(group_row)

        for row_index, row in enumerate(bucket, start=1):
            detail_row = {"group_id": group_id, "row_index": row_index}
            for field in _REPORT_FIELDS:
                detail_row[field] = row.get(field)
            detail_rows.append(detail_row)

    summary = {
        "scope": scope,
        "identity_fields": list(identity_fields),
        "source_rows": len(scoped_rows),
        "unique_identity_count": len(groups),
        "duplicate_groups": duplicate_groups,
        "duplicate_rows_beyond_first": duplicate_rows_beyond_first,
        "groups_with_category_conflict": groups_with_category_conflict,
        "groups_with_request_idx_type_conflict": groups_with_request_idx_type_conflict,
        "groups_with_business_conflict": groups_with_business_conflict,
    }
    return summary, group_rows, detail_rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def _write_reports(rows: list[dict[str, Any]]) -> dict[str, Any]:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(_REPORT_DIR / "dc_daily_rows.csv", rows, list(_REPORT_FIELDS))

    duplicate_group_rows: list[dict[str, Any]] = []
    duplicate_detail_rows: list[dict[str, Any]] = []
    identity_summaries: list[dict[str, Any]] = []
    for scope in ("all_request", "explicit_idx_type"):
        for identity_fields in (("ts_code", "trade_date"), ("ts_code", "trade_date", "category")):
            summary, group_rows, detail_rows = _summarize_duplicate_groups(
                rows,
                identity_fields=identity_fields,
                scope=scope,
            )
            identity_summaries.append(summary)
            duplicate_group_rows.extend(group_rows)
            duplicate_detail_rows.extend(detail_rows)

    _write_csv(
        _REPORT_DIR / "duplicate_identity_groups.csv",
        duplicate_group_rows,
        [
            "group_id",
            "scope",
            "identity_fields",
            "identity_key",
            "ts_code",
            "trade_date",
            "category",
            "row_count",
            "category_values",
            "request_idx_type_values",
            "differing_business_fields",
        ],
    )
    _write_csv(
        _REPORT_DIR / "duplicate_identity_rows.csv",
        duplicate_detail_rows,
        ["group_id", "row_index", *list(_REPORT_FIELDS)],
    )
    summary = {
        "api_name": "dc_daily",
        "source_doc": "docs/sources/tushare/股票数据/打板专题数据/0382_东财概念板块行情.md",
        "start_date": _START_DATE,
        "end_date": _END_DATE,
        "request_mode": _REQUEST_MODE,
        "idx_types": list(_IDX_TYPES),
        "page_limit": _PAGE_LIMIT,
        "rate_limit_per_minute": _MAX_CALLS_PER_MINUTE,
        "fetched_rows": len(rows),
        "all_request_rows": sum(1 for row in rows if row.get("probe_scope") == "all_request"),
        "explicit_idx_type_rows": sum(1 for row in rows if row.get("probe_scope") == "explicit_idx_type"),
        "identity_summaries": identity_summaries,
        "report_dir": str(_REPORT_DIR),
    }
    (_REPORT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


@pytest.mark.skipif(
    os.getenv(_RUN_FLAG) != "1",
    reason=f"set {_RUN_FLAG}=1 to probe live Tushare dc_daily identity keys",
)
def test_tushare_dc_daily_identity_probe() -> None:
    settings = get_settings()
    if not settings.tushare_token:
        pytest.skip("TUSHARE_TOKEN is not configured")
    if _PAGE_LIMIT <= 0:
        raise ValueError("DC_DAILY_PROBE_PAGE_LIMIT must be positive")

    start_date = _parse_yyyymmdd(_START_DATE)
    end_date = _parse_yyyymmdd(_END_DATE)
    if end_date < start_date:
        raise ValueError(f"DC_DAILY_PROBE_END_DATE must be >= DC_DAILY_PROBE_START_DATE: {_START_DATE} {_END_DATE}")

    pro_api = ts.pro_api(settings.tushare_token)
    limiter = _MinuteRateLimiter(_MAX_CALLS_PER_MINUTE)
    request_idx_types = _request_idx_types()

    fetched_rows: list[dict[str, Any]] = []
    dates = _iter_dates(start_date, end_date)
    total_requests = len(dates) * len(request_idx_types)
    request_index = 0
    for current_date in dates:
        trade_date_text = current_date.strftime("%Y%m%d")
        for idx_type in request_idx_types:
            request_index += 1
            rows = _fetch_date_rows(
                pro_api,
                limiter,
                trade_date_text=trade_date_text,
                idx_type=idx_type,
            )
            fetched_rows.extend(rows)
            print(
                "dc_daily identity probe progress: "
                f"{request_index}/{total_requests} trade_date={trade_date_text} "
                f"idx_type={idx_type or '*'} rows={len(rows)} total={len(fetched_rows)}",
                flush=True,
            )

    if not fetched_rows:
        pytest.skip(f"dc_daily probe fetched no rows for start={_START_DATE} end={_END_DATE}")

    summary = _write_reports(fetched_rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    assert Path(summary["report_dir"]).exists()
    assert summary["fetched_rows"] == len(fetched_rows)
