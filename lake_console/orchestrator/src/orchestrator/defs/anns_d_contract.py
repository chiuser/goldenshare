"""The six original announcement fields, without stock-pool filtering."""

import hashlib
import json
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ANNOUNCEMENT_FIELDS = ("ann_date", "ts_code", "name", "title", "url", "rec_time")
ANNOUNCEMENT_VERSION = 1
ANNOUNCEMENT_COLUMNS_SQL = ", ".join(ANNOUNCEMENT_FIELDS)


class AnnouncementError(RuntimeError):
    """Safe reason codes; optional source sample is stored only in staging."""

    def __init__(self, reason, *, source_sample=None):
        super().__init__(reason)
        self.source_sample = source_sample


class AnnouncementCancelled(AnnouncementError):
    pass


def announcement_date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise AnnouncementError("invalid_announcement_date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise AnnouncementError("invalid_announcement_date") from None
    if parsed.isoformat() != value or parsed < date(2020, 1, 1):
        raise AnnouncementError("invalid_announcement_date")
    return parsed


def announcement_dates(start, end, *, today=None):
    first, last = announcement_date(start), announcement_date(end)
    today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if first > last or last >= today:
        raise AnnouncementError("announcement_range_not_closed")
    return tuple(
        (first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)
    )


def normalize_announcement_rows(
    rows, columns=ANNOUNCEMENT_FIELDS, *, day=None, sdk=False
):
    if tuple(columns) != ANNOUNCEMENT_FIELDS:
        raise AnnouncementError("announcement_response_schema")
    if sdk:
        from pandas import NA, NaT
    normalized = []
    for row in rows:
        if set(row) != set(ANNOUNCEMENT_FIELDS):
            raise AnnouncementError("announcement_source_keys")
        projected = {}
        for field in ANNOUNCEMENT_FIELDS:
            value = row[field]
            if sdk and (
                value is NA
                or value is NaT
                or (isinstance(value, float) and math.isnan(value))
            ):
                value = None
            if value is not None and not isinstance(value, str):
                raise AnnouncementError("announcement_source_type")
            projected[field] = value
        raw_date = projected["ann_date"]
        try:
            parsed = (
                date.fromisoformat(raw_date)
                if isinstance(raw_date, str) and len(raw_date) == 8
                else None
            )
        except ValueError:
            parsed = None
        if parsed is None or parsed.strftime("%Y%m%d") != raw_date:
            raise AnnouncementError("announcement_source_date")
        if day is not None and parsed != announcement_date(day):
            raise AnnouncementError("announcement_partition_mismatch")
        normalized.append(projected)
    return normalized


def announcement_rows_digest(rows):
    # Used only for detecting repeated source pages, never for deduplicating Raw.
    encoded = json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


ANNOUNCEMENT_ASSET = "raw_tushare_anns_d"
ANNOUNCEMENT_JOB = "raw_anns_d_update_job"
ANNOUNCEMENT_CHECKS = (
    "raw_tushare_anns_d_file_contract_check",
    "raw_tushare_anns_d_delivery_reconciliation_check",
)
ANNOUNCEMENT_SOURCE_DOC = "docs/sources/tushare/大模型语料/0176_上市公司全量公告.md"
