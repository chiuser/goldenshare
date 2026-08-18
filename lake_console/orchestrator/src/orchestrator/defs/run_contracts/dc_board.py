"""Stable contracts for the Eastmoney board datasets."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import time
from numbers import Real

DC_INDEX_HISTORY_START_DATE = "2024-12-20"
DC_MEMBER_HISTORY_START_DATE = "2024-12-20"
DC_DAILY_HISTORY_START_DATE = "2024-01-02"

DC_INDEX_TYPES = ("行业板块", "概念板块", "地域板块")
DC_DAILY_CATEGORIES = DC_INDEX_TYPES

DC_INDEX_FIELDS = (
    "ts_code",
    "trade_date",
    "name",
    "leading",
    "leading_code",
    "pct_change",
    "leading_pct",
    "total_mv",
    "turnover_rate",
    "up_num",
    "down_num",
    "idx_type",
    "level",
)
DC_MEMBER_FIELDS = ("trade_date", "ts_code", "con_code", "name")
DC_DAILY_FIELDS = (
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

DC_INDEX_PAGE_LIMIT = 5_000
DC_MEMBER_PAGE_LIMIT = 5_000
DC_DAILY_PAGE_LIMIT = 2_000
DC_BOARD_SENSOR_WINDOW_LIMIT = 10
DC_BOARD_CURRENT_DAY_REFERENCE_NOT_BEFORE = time(21, 15)
DC_BOARD_REFERENCE_STABILITY_SECONDS = 300

# These are the M1C-approved per-partition guardrails for the future dc_member
# writer. The writer must pass requests through the bounded policy helper; these
# values are contract data, not an invitation to call Tushare directly.
DC_MEMBER_MIN_REQUEST_INTERVAL_SECONDS = 0.13
DC_MEMBER_MAX_RETRIES = 3
DC_MEMBER_BACKOFF_BASE_SECONDS = 1.0
DC_MEMBER_BACKOFF_MAX_SECONDS = 8.0
DC_BOARD_MAX_REQUESTS_PER_PARTITION = 1_200
# This is DC-member-specific.  The shared request-policy default remains 300s.
DC_BOARD_MAX_ELAPSED_MS = 600_000

DC_MEMBER_BOOTSTRAP_SOURCE_METHOD = "prod_db_readonly_export"
DC_MEMBER_DAILY_SOURCE_METHOD = "tushare_api_by_ts_code"
DC_INDEX_REQUEST_POLICY_NAME = "tushare_partition_paged_bounded"
DC_DAILY_REQUEST_POLICY_NAME = "tushare_partition_paged_bounded"
DC_MEMBER_REQUEST_POLICY_NAME = "tushare_code_loop_bounded_policy"

RAW_DC_INDEX_CHECKS = ("raw_tushare_dc_index_core_check",)
RAW_DC_MEMBER_CHECKS = ("raw_tushare_dc_member_core_check",)
RAW_DC_DAILY_CHECKS = ("raw_tushare_dc_daily_core_check",)
SILVER_DC_INDEX_CHECKS = ("silver_dc_index_core_check",)
SILVER_DC_MEMBER_CHECKS = ("silver_dc_member_core_check",)
SILVER_DC_DAILY_CHECKS = ("silver_dc_daily_core_check",)

# Raw mirrors the explicitly requested Tushare fields. Silver keeps the same
# business fields and changes only the storage type/normalization of dates and
# codes; no business field is silently dropped.
RAW_DC_INDEX_COLUMNS = DC_INDEX_FIELDS
RAW_DC_MEMBER_COLUMNS = DC_MEMBER_FIELDS
RAW_DC_DAILY_COLUMNS = DC_DAILY_FIELDS
SILVER_DC_INDEX_COLUMNS = DC_INDEX_FIELDS
SILVER_DC_MEMBER_COLUMNS = DC_MEMBER_FIELDS
SILVER_DC_DAILY_COLUMNS = DC_DAILY_FIELDS


@dataclass(frozen=True, slots=True)
class DcBoardProdCompletionSnapshot:
    """In-memory prod completion evidence; never serialize its code sets."""

    trade_date: str
    index_identity: tuple[tuple[str, str], ...]
    daily_identity: tuple[tuple[str, str], ...]
    member_codes: tuple[str, ...]
    member_row_count: int
    completion_fingerprint: str

    @property
    def index_row_count(self) -> int:
        return len(self.index_identity)

    @property
    def daily_row_count(self) -> int:
        return len(self.daily_identity)

    @property
    def member_code_count(self) -> int:
        return len(self.member_codes)

    def compact_summary(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "completion_fingerprint": self.completion_fingerprint,
            "index_row_count": self.index_row_count,
            "daily_row_count": self.daily_row_count,
            "member_row_count": self.member_row_count,
            "member_code_count": self.member_code_count,
        }


def build_dc_board_prod_completion_snapshot(
    *,
    trade_date: str,
    index_identity: Sequence[tuple[str, str]],
    daily_identity: Sequence[tuple[str, str]],
    member_codes: Sequence[str],
    member_row_count: int,
) -> DcBoardProdCompletionSnapshot:
    """Build the stable hash proving that prod completion stopped changing."""

    normalized_index_identity = tuple(sorted(index_identity))
    normalized_daily_identity = tuple(sorted(daily_identity))
    normalized_member_codes = tuple(sorted(member_codes))
    fingerprint_payload = {
        "trade_date": trade_date,
        "index_identity": normalized_index_identity,
        "daily_identity": normalized_daily_identity,
        "member_codes": normalized_member_codes,
        "member_row_count": member_row_count,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return DcBoardProdCompletionSnapshot(
        trade_date=trade_date,
        index_identity=normalized_index_identity,
        daily_identity=normalized_daily_identity,
        member_codes=normalized_member_codes,
        member_row_count=member_row_count,
        completion_fingerprint=fingerprint,
    )


@dataclass(frozen=True, slots=True)
class DcBoardTushareSourceSnapshot:
    """Validated Tushare index/daily source identity and business-row hash."""

    trade_date: str
    index_identity: tuple[tuple[str, str], ...]
    daily_identity: tuple[tuple[str, str], ...]
    index_row_count: int
    daily_row_count: int
    source_fingerprint: str

    def compact_summary(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "source_fingerprint": self.source_fingerprint,
            "index_row_count": self.index_row_count,
            "daily_row_count": self.daily_row_count,
        }


def _canonical_source_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Real):
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        return format(numeric, ".15g")
    return str(value)


def _canonical_source_rows(
    rows: Sequence[Mapping[str, object]],
    fields: Sequence[str],
) -> tuple[tuple[object, ...], ...]:
    normalized = [
        tuple(_canonical_source_value(row.get(field)) for field in fields)
        for row in rows
    ]
    return tuple(
        sorted(
            normalized,
            key=lambda row: json.dumps(
                row,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
    )


def build_dc_board_tushare_source_snapshot(
    *,
    trade_date: str,
    index_rows: Sequence[Mapping[str, object]],
    daily_rows: Sequence[Mapping[str, object]],
) -> DcBoardTushareSourceSnapshot:
    """Hash complete normalized Tushare business rows, not only identities."""

    index_identity = tuple(
        sorted(
            (
                str(row.get("idx_type") or "").strip(),
                str(row.get("ts_code") or "").strip().upper(),
            )
            for row in index_rows
        )
    )
    daily_identity = tuple(
        sorted(
            (
                str(row.get("category") or "").strip(),
                str(row.get("ts_code") or "").strip().upper(),
            )
            for row in daily_rows
        )
    )
    payload = {
        "trade_date": trade_date,
        "index_rows": _canonical_source_rows(index_rows, DC_INDEX_FIELDS),
        "daily_rows": _canonical_source_rows(daily_rows, DC_DAILY_FIELDS),
    }
    source_fingerprint = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return DcBoardTushareSourceSnapshot(
        trade_date=trade_date,
        index_identity=index_identity,
        daily_identity=daily_identity,
        index_row_count=len(index_rows),
        daily_row_count=len(daily_rows),
        source_fingerprint=source_fingerprint,
    )
