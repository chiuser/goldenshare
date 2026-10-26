"""The six original announcement fields, without stock-pool filtering."""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
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


@dataclass(frozen=True)
class AnnouncementFileSettings:
    """Only the saved settings needed to verify an announcement file."""

    page_size: int
    duckdb_memory: str
    duckdb_threads: int
    spill_limit: str
    min_free_reserve: int


@dataclass(frozen=True)
class AnnouncementHistorySettings(AnnouncementFileSettings):
    """Frozen bounded source settings, without daily source execution controls."""

    prod_fetch_rows: int
    max_month_rows: int
    month_deadline: float
    sql_timeout_ms: int


def _announcement_saved_policy(record, reason):
    if not isinstance(record, Mapping) or not isinstance(record.get("policy"), Mapping):
        raise AnnouncementError(reason)
    return record["policy"]


def _announcement_saved_positive_int(policy, field, reason):
    value = policy.get(field)
    if type(value) is not int or value <= 0:
        raise AnnouncementError(reason)
    return value


def _announcement_saved_capacity(policy, field, reason):
    value = policy.get(field)
    # DuckDB owns the unit grammar; preserve legal saved values such as a 0B spill.
    if not isinstance(value, str) or not value.strip():
        raise AnnouncementError(reason)
    return value


def _announcement_saved_file_values(policy, reason):
    page_size = _announcement_saved_positive_int(policy, "page_size", reason)
    if page_size != 2000:
        raise AnnouncementError(reason)
    return {
        "page_size": page_size,
        "duckdb_memory": _announcement_saved_capacity(policy, "duckdb_memory", reason),
        "duckdb_threads": _announcement_saved_positive_int(
            policy, "duckdb_threads", reason
        ),
        "spill_limit": _announcement_saved_capacity(policy, "spill_limit", reason),
        "min_free_reserve": _announcement_saved_positive_int(
            policy, "min_free_reserve", reason
        ),
    }


def announcement_file_settings_from_evidence(identity):
    """Read the fields used by file checks; preserve the complete original identity."""
    reason = "announcement_evidence_policy"
    policy = _announcement_saved_policy(identity, reason)
    return AnnouncementFileSettings(**_announcement_saved_file_values(policy, reason))


def announcement_history_settings_from_plan(plan):
    """Read actual history controls, not unrelated saved daily execution metadata."""
    reason = "announcement_plan_policy"
    policy = _announcement_saved_policy(plan, reason)
    seconds = policy.get("month_deadline")
    try:
        valid_seconds = (
            type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0
        )
    except OverflowError:
        valid_seconds = False
    if not valid_seconds:
        raise AnnouncementError(reason)
    return AnnouncementHistorySettings(
        **_announcement_saved_file_values(policy, reason),
        prod_fetch_rows=_announcement_saved_positive_int(
            policy, "prod_fetch_rows", reason
        ),
        max_month_rows=_announcement_saved_positive_int(
            policy, "max_month_rows", reason
        ),
        month_deadline=seconds,
        sql_timeout_ms=_announcement_saved_positive_int(
            policy, "sql_timeout_ms", reason
        ),
    )


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


def announcement_date_range(start, end):
    """Enumerate a validated closed range; the calling intent sets its time boundary."""
    first, last = announcement_date(start), announcement_date(end)
    if first > last:
        raise AnnouncementError("announcement_range_not_closed")
    return tuple(
        (first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)
    )


def announcement_dates(start, end, *, today=None):
    """Historical/manual intent continues to require ended natural days."""
    today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if announcement_date(end) >= today:
        raise AnnouncementError("announcement_range_not_closed")
    return announcement_date_range(start, end)


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
