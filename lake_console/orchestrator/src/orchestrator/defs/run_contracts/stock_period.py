"""Direct-source weekly/monthly Raw intent and wire contract; no runtime IO."""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from orchestrator.defs.run_contracts.stock_weekly import ADJUSTED_WEEKLY_FIELDS

FIELDS = ADJUSTED_WEEKLY_FIELDS
VERSION = "stock-period-source-v2"
FREQUENCIES = ("week", "month")
COMPLETION_VERSION = "stock-period-completion@1"
COMPLETION_METADATA_KEY = "goldenshare/period_completion"


def completion_reference(run_id, receipt_hash, freq):
    """An existing immutable Raw receipt, never an arbitrary path or event id."""
    from orchestrator.defs.run_contracts.run_keys import build_batch_id

    frequency(freq)
    if any(
        not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None
        for v in (run_id, receipt_hash)
    ):
        raise ValueError("period_completion_identity_invalid")
    return {
        "raw_execution_id": run_id,
        "file_receipt_hash": receipt_hash,
        "upstream_batch_id": build_batch_id(
            producer="stock_period_raw",
            scope=freq,
            payload={"producer_run_id": run_id, "file_receipt_hash": receipt_hash},
        ),
    }


def validate_completion_reference(value, freq):
    if not isinstance(value, dict) or set(value) != {
        "raw_execution_id",
        "file_receipt_hash",
        "upstream_batch_id",
    }:
        raise ValueError("period_completion_reference_invalid")
    expected = completion_reference(
        value["raw_execution_id"], value["file_receipt_hash"], freq
    )
    if value != expected:
        raise ValueError("period_completion_reference_invalid")
    return expected


def completion_notice(reference, freq, file_count):
    reference = validate_completion_reference(reference, freq)
    if type(file_count) is not int or file_count <= 0:
        raise ValueError("period_completion_count_invalid")
    return {
        "version": COMPLETION_VERSION,
        "freq": freq,
        "file_count": file_count,
        **reference,
    }


def validate_completion_notice(value, freq):
    if not isinstance(value, dict) or set(value) != {
        "version",
        "freq",
        "file_count",
        "raw_execution_id",
        "file_receipt_hash",
        "upstream_batch_id",
    }:
        raise ValueError("period_completion_notice_invalid")
    reference = {
        k: value[k]
        for k in ("raw_execution_id", "file_receipt_hash", "upstream_batch_id")
    }
    if value != completion_notice(reference, freq, value["file_count"]):
        raise ValueError("period_completion_notice_invalid")
    return reference


@dataclass(frozen=True)
class StockPeriodPolicy:
    page_limit: int = 6000
    response_bytes: int = 16 * 1024**2
    unit_bytes: int = 128 * 1024**2
    timeout_seconds: float = 30
    retries: int = 2
    duckdb_memory: str = "3GiB"
    duckdb_threads: int = 2
    spill_bytes: int = 16 * 1024**3
    workspace_bytes: int = 32 * 1024**3
    rss_bytes: int = 4 * 1024**3
    progress_seconds: float = 5

    def __post_init__(self):
        if not 1 <= self.page_limit <= 6000 or self.timeout_seconds <= 0:
            raise ValueError("period_policy_invalid")
        if (
            min(
                self.response_bytes,
                self.unit_bytes,
                self.spill_bytes,
                self.workspace_bytes,
                self.rss_bytes,
                self.duckdb_threads,
                self.progress_seconds,
            )
            <= 0
            or self.retries < 0
        ):
            raise ValueError("period_policy_invalid")
        if self.unit_bytes < self.response_bytes:
            raise ValueError("period_policy_invalid")

    def payload(self):
        return asdict(self)


DEFAULT_POLICY = StockPeriodPolicy()


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def intent_id(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("period_intent_id_required")
    return value


def execution_id(value):
    """One logical intent survives process retries and the passage of midnight."""
    return digest({"version": VERSION, "intent_id": intent_id(value)})


def verify_execution(saved, run_id):
    identity = saved["identity"]
    if (
        identity["intent"].get("version") != VERSION
        or execution_id(identity["intent"].get("request_id")) != run_id
        or saved.get("identity_hash") != digest(identity)
    ):
        raise ValueError("period_manifest_changed")
    if "devices" not in saved:
        raise ValueError("period_execution_protection_missing")
    return identity


def frequency(freq):
    if freq not in FREQUENCIES:
        raise ValueError("period_frequency_invalid")
    return freq


def period_for(day: date, freq: str):
    frequency(freq)
    return (
        (day + timedelta(days=4 - day.weekday())).isoformat()
        if freq == "week"
        else day.strftime("%Y-%m")
    )


def period_date(period, freq):
    frequency(freq)
    if freq == "week":
        day = date.fromisoformat(period)
        if day.isoformat() != period or day.weekday() != 4:
            raise ValueError("period_week_invalid")
        return day.strftime("%Y%m%d")
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        raise ValueError("period_month_invalid")
    year, month = map(int, period.split("-"))
    return f"{year:04d}{month:02d}{calendar.monthrange(year, month)[1]:02d}"


def next_period(period, freq):
    coordinate = date.fromisoformat(period if freq == "week" else period + "-01")
    return (
        (coordinate + timedelta(days=7)).isoformat()
        if freq == "week"
        else (coordinate.replace(day=28) + timedelta(days=4)).strftime("%Y-%m")
    )


def source_period(trade_date, freq):
    if not isinstance(trade_date, str) or not re.fullmatch(r"\d{8}", trade_date):
        raise ValueError("period_source_date_invalid")
    day = date(int(trade_date[:4]), int(trade_date[4:6]), int(trade_date[6:]))
    return period_for(day, freq)


def admitted_code(code, listed, aliases):
    if (
        not isinstance(code, str)
        or not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code)
        or code not in listed
        or aliases.get(code, code) != code
    ):
        raise ValueError("period_code_not_admitted")
    # BSE new-code admission is proven by the confirmed identity mapping, not prefix guessing.
    if code.endswith(".BJ") and code not in set(aliases.values()):
        raise ValueError("period_bse_identity_unconfirmed")
    return code


def request_params(
    *,
    freq,
    offset=0,
    policy=DEFAULT_POLICY,
    code=None,
    period=None,
    listed=(),
    aliases=None,
):
    frequency(freq)
    if type(offset) is not int or offset < 0 or (code is None) == (period is None):
        raise ValueError("period_request_scope_invalid")
    params = {"freq": freq, "limit": policy.page_limit, "offset": offset}
    if code is not None:
        params["ts_code"] = admitted_code(code, listed, aliases or {})
    else:
        # A month can contain several source trade_date keys (e.g. 20200228 and 29).
        anchor = period_date(period, freq)
        if freq == "month":
            params.update(start_date=anchor[:6] + "01", end_date=anchor)
        else:
            params["trade_date"] = anchor
    return params


def validate_rows(fields, items, *, freq, code=None, period=None):
    if (
        not isinstance(fields, (list, tuple))
        or tuple(fields) != FIELDS
        or len(set(fields)) != len(fields)
    ):
        raise ValueError("period_source_fields_invalid")
    seen = set()
    for values in items:
        if not isinstance(values, (list, tuple)) or len(values) != len(FIELDS):
            raise ValueError("period_source_width_invalid")
        row = dict(zip(FIELDS, values, strict=True))
        if row["freq"] != freq or not re.fullmatch(
            r"\d{6}\.(SH|SZ|BJ)", str(row["ts_code"])
        ):
            raise ValueError("period_source_identity_invalid")
        if code is not None and row["ts_code"] != code:
            raise ValueError("period_source_identity_invalid")
        for field in ("trade_date", "end_date"):
            value = row[field]
            if field == "end_date" and value is None:
                continue
            if not isinstance(value, str) or not re.fullmatch(r"\d{8}", value):
                raise ValueError("period_source_date_invalid")
            source_period(value, freq)
        if period is not None and source_period(row["trade_date"], freq) != period:
            raise ValueError("period_source_range_invalid")
        key = (row["ts_code"], row["trade_date"], row["freq"])
        if key in seen:
            raise ValueError("period_source_duplicate_key")
        seen.add(key)
        for field in FIELDS[4:]:
            value = row[field]
            if value is None:
                continue
            try:
                number = Decimal(str(value))
                precision = (
                    20
                    if field in ("vol", "amount")
                    else 10
                    if field == "pct_chg"
                    else 18
                )
                if (
                    not number.is_finite()
                    or number != number.quantize(Decimal(".0001"))
                    or abs(number) >= Decimal(10) ** (precision - 4)
                ):
                    raise ValueError("period_source_decimal_invalid")
            except InvalidOperation:
                raise ValueError("period_source_decimal_invalid") from None
    return seen
