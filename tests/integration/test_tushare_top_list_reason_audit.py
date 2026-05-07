from __future__ import annotations

from collections import defaultdict
import csv
from datetime import date, timedelta
import json
import os
from pathlib import Path
from typing import Any

import pytest
import tushare as ts

from src.foundation.config.settings import get_settings
from src.foundation.services.transform.top_list_reason import hash_top_list_reason, normalize_top_list_reason


_RUN_FLAG = "RUN_TUSHARE_TOP_LIST_REASON_AUDIT"
_START_DATE = os.getenv("TOP_LIST_AUDIT_START_DATE", "20170110").strip()
_END_DATE = os.getenv("TOP_LIST_AUDIT_END_DATE", _START_DATE).strip()
_TS_CODE = os.getenv("TOP_LIST_AUDIT_TS_CODE", "").strip().upper()
_PAGE_LIMIT = int(os.getenv("TOP_LIST_AUDIT_PAGE_LIMIT", "8000"))
_REPORT_DIR = Path(
    os.getenv(
        "TOP_LIST_AUDIT_REPORT_DIR",
        f"reports/top_list_reason_audit_{_START_DATE}_{_END_DATE}",
    )
)
_FIELDS = (
    "trade_date",
    "ts_code",
    "name",
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
    "reason",
)
_DISPLAY_FIELDS = ("reason", "name")
_BUSINESS_FIELDS = (
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
)
_COMPARE_FIELDS = _DISPLAY_FIELDS + _BUSINESS_FIELDS


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


def _normalize_scalar(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _fetch_trade_date_rows(pro_api, *, trade_date_text: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        params: dict[str, Any] = {
            "trade_date": trade_date_text,
            "limit": _PAGE_LIMIT,
            "offset": offset,
        }
        if _TS_CODE:
            params["ts_code"] = _TS_CODE
        frame = pro_api.top_list(
            **params,
            fields=",".join(_FIELDS),
        )
        page_rows = [] if frame is None else frame.to_dict(orient="records")
        if not page_rows:
            return rows
        rows.extend(page_rows)
        if len(page_rows) < _PAGE_LIMIT:
            return rows
        offset += _PAGE_LIMIT


def _augment_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    augmented: list[dict[str, Any]] = []
    for row in rows:
        normalized_reason = normalize_top_list_reason(row.get("reason"))
        reason_hash = hash_top_list_reason(row.get("reason"))
        item = dict(row)
        item["normalized_reason"] = normalized_reason
        item["reason_hash"] = reason_hash
        augmented.append(item)
    return augmented


def _diff_fields(rows: list[dict[str, Any]]) -> list[str]:
    differing_fields: list[str] = []
    for field in _COMPARE_FIELDS:
        values = {_normalize_scalar(row.get(field)) for row in rows}
        if len(values) > 1:
            differing_fields.append(field)
    return differing_fields


def _classify_group(rows: list[dict[str, Any]]) -> str:
    differing_fields = _diff_fields(rows)
    business_diffs = [field for field in differing_fields if field in _BUSINESS_FIELDS]
    display_diffs = [field for field in differing_fields if field in _DISPLAY_FIELDS]
    if business_diffs:
        return "conflicting_payload"
    if display_diffs:
        return "display_variant_only"
    return "identical_payload_duplicate"


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def _write_reports(*, rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            _normalize_scalar(row.get("ts_code")).upper(),
            _normalize_scalar(row.get("trade_date")),
            _normalize_scalar(row.get("reason_hash")),
        )
        groups[key].append(row)

    duplicate_group_rows: list[dict[str, Any]] = []
    duplicate_detail_rows: list[dict[str, Any]] = []
    summary = {
        "start_date": _START_DATE,
        "end_date": _END_DATE,
        "ts_code_filter": _TS_CODE or None,
        "page_limit": _PAGE_LIMIT,
        "fetched_rows": len(rows),
        "duplicate_identity_groups": 0,
        "duplicate_rows_beyond_first": 0,
        "group_type_counts": {
            "display_variant_only": 0,
            "conflicting_payload": 0,
            "identical_payload_duplicate": 0,
        },
    }

    group_index = 0
    for (ts_code, trade_date_text, reason_hash), bucket in sorted(groups.items()):
        if len(bucket) <= 1:
            continue
        group_index += 1
        group_type = _classify_group(bucket)
        differing_fields = _diff_fields(bucket)
        summary["duplicate_identity_groups"] += 1
        summary["duplicate_rows_beyond_first"] += len(bucket) - 1
        summary["group_type_counts"][group_type] += 1
        group_id = f"G{group_index:06d}"
        duplicate_group_rows.append(
            {
                "group_id": group_id,
                "ts_code": ts_code,
                "trade_date": trade_date_text,
                "reason_hash": reason_hash,
                "row_count": len(bucket),
                "group_type": group_type,
                "differing_fields": ",".join(differing_fields),
                "reasons": " | ".join(sorted({_normalize_scalar(row.get("reason")) for row in bucket})),
                "names": " | ".join(sorted({_normalize_scalar(row.get("name")) for row in bucket})),
            }
        )
        for row_index, row in enumerate(bucket, start=1):
            detail_row = {"group_id": group_id, "row_index": row_index, "group_type": group_type}
            for field in _FIELDS:
                detail_row[field] = row.get(field)
            detail_row["normalized_reason"] = row.get("normalized_reason")
            detail_row["reason_hash"] = row.get("reason_hash")
            duplicate_detail_rows.append(detail_row)

    report_dir = _REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        report_dir / "top_list_rows.csv",
        rows,
        list(_FIELDS) + ["normalized_reason", "reason_hash"],
    )
    _write_csv(
        report_dir / "duplicate_groups.csv",
        duplicate_group_rows,
        [
            "group_id",
            "ts_code",
            "trade_date",
            "reason_hash",
            "row_count",
            "group_type",
            "differing_fields",
            "reasons",
            "names",
        ],
    )
    _write_csv(
        report_dir / "duplicate_group_rows.csv",
        duplicate_detail_rows,
        ["group_id", "row_index", "group_type", *_FIELDS, "normalized_reason", "reason_hash"],
    )
    summary["report_dir"] = str(report_dir)
    with (report_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    return summary


@pytest.mark.skipif(
    os.getenv(_RUN_FLAG) != "1",
    reason=f"set {_RUN_FLAG}=1 to run live Tushare top_list reason audit",
)
def test_tushare_top_list_reason_identity_audit() -> None:
    settings = get_settings()
    if not settings.tushare_token:
        pytest.skip("TUSHARE_TOKEN is not configured")

    start_date = _parse_yyyymmdd(_START_DATE)
    end_date = _parse_yyyymmdd(_END_DATE)
    if end_date < start_date:
        raise ValueError(f"TOP_LIST_AUDIT_END_DATE must be >= TOP_LIST_AUDIT_START_DATE: {_START_DATE} {_END_DATE}")

    pro_api = ts.pro_api(settings.tushare_token)
    fetched_rows: list[dict[str, Any]] = []
    for current_date in _iter_dates(start_date, end_date):
        trade_date_text = current_date.strftime("%Y%m%d")
        fetched_rows.extend(_fetch_trade_date_rows(pro_api, trade_date_text=trade_date_text))

    if not fetched_rows:
        pytest.skip(
            "top_list audit fetched no rows "
            f"for start={_START_DATE} end={_END_DATE} ts_code={_TS_CODE or '*'}"
        )

    summary = _write_reports(rows=_augment_rows(fetched_rows))
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    assert Path(summary["report_dir"]).exists()
    assert summary["fetched_rows"] == len(fetched_rows)
