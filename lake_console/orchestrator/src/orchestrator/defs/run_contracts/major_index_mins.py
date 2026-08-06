"""Stable source contract for major-index minute bars."""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

MAJOR_INDEX_MINS_SOURCE_FREQS = (
    "1min",
    "5min",
    "15min",
    "30min",
    "60min",
)
MAJOR_INDEX_MINS_SILVER_FREQS = MAJOR_INDEX_MINS_SOURCE_FREQS + (
    "90min",
    "120min",
)
MAJOR_INDEX_MINS_SOURCE_COLUMNS = (
    "ts_code",
    "freq",
    "trade_time",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
    "exchange",
    "vwap",
)
MAJOR_INDEX_MINS_RAW_COLUMN_TYPES = {
    "ts_code": "VARCHAR",
    "freq": "VARCHAR",
    "trade_time": "TIMESTAMP",
    "open": "DOUBLE",
    "close": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "vol": "DOUBLE",
    "amount": "DOUBLE",
    "exchange": "VARCHAR",
    "vwap": "DOUBLE",
}
MAJOR_INDEX_MINS_PAGE_LIMIT = 8_000
MAJOR_INDEX_MINS_HISTORY_START_DATE = "2009-01-05"
MAJOR_INDEX_MINS_SCOPE_REVISION = "major_index_mins_scope_v1"
MAJOR_INDEX_MINS_BOOTSTRAP_MAX_REQUESTS = 5_000
MAJOR_INDEX_MINS_BOOTSTRAP_WINDOW_TRADING_DAYS = {
    "1min": 20,
    "5min": 60,
    "15min": 120,
    "30min": 180,
    "60min": 240,
}
MAJOR_INDEX_MINS_BOOTSTRAP_REQUEST_CHUNK_SIZE = 20
MAJOR_INDEX_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER = 2.0
MAJOR_INDEX_MINS_DAILY_PROBE_WINDOW_LIMIT = 10
MAJOR_INDEX_MINS_RAW_ASSET_KEYS = tuple(
    f"raw_major_index_mins_{frequency.removesuffix('min')}m"
    for frequency in MAJOR_INDEX_MINS_SOURCE_FREQS
)
MAJOR_INDEX_MINS_SILVER_ASSET_KEYS = tuple(
    f"silver_major_index_mins_{frequency.removesuffix('min')}m"
    for frequency in MAJOR_INDEX_MINS_SILVER_FREQS
)
MAJOR_INDEX_MINS_RAW_CHECKS = tuple(
    f"{asset_key}_core_check" for asset_key in MAJOR_INDEX_MINS_RAW_ASSET_KEYS
)
MAJOR_INDEX_MINS_SILVER_CHECKS = tuple(
    f"{asset_key}_core_check" for asset_key in MAJOR_INDEX_MINS_SILVER_ASSET_KEYS
)
MAJOR_INDEX_MINS_RAW_JOB_NAME = "raw_major_index_mins_update_job"
MAJOR_INDEX_MINS_SILVER_JOB_NAME = "silver_major_index_mins_update_job"

_TS_CODE_PATTERN = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")


class MajorIndexMinsContractError(ValueError):
    """Raised when source scope or request identity violates the contract."""


def normalize_major_index_mins_source_freq(value: object) -> str:
    normalized = str(value).strip().lower()
    if normalized not in MAJOR_INDEX_MINS_SOURCE_FREQS:
        allowed = ", ".join(MAJOR_INDEX_MINS_SOURCE_FREQS)
        raise MajorIndexMinsContractError(
            f"major-index minute source frequency must be one of {allowed}; "
            f"got {value!r}."
        )
    return normalized


def normalize_major_index_mins_silver_freq(value: object) -> str:
    normalized = str(value).strip().lower()
    if normalized not in MAJOR_INDEX_MINS_SILVER_FREQS:
        allowed = ", ".join(MAJOR_INDEX_MINS_SILVER_FREQS)
        raise MajorIndexMinsContractError(
            f"major-index minute Silver frequency must be one of {allowed}; "
            f"got {value!r}."
        )
    return normalized


def major_index_mins_exchange_for_code(ts_code: str) -> str:
    normalized_code = major_index_mins_source_scope(ts_code).ts_code
    if normalized_code.endswith(".SH"):
        return "XSHG"
    if normalized_code.endswith(".SZ"):
        return "XSHE"
    return "BSE"


def _clock_text(total_minutes: int) -> str:
    hour, minute = divmod(total_minutes, 60)
    return f"{hour:02d}:{minute:02d}:00"


def major_index_mins_session_times(
    *,
    exchange: str,
    source_freq: str,
) -> tuple[str, ...]:
    normalized_exchange = str(exchange).strip().upper()
    if normalized_exchange not in {"XSHG", "XSHE", "BSE"}:
        raise MajorIndexMinsContractError(
            f"unsupported major-index minute exchange: {exchange!r}"
        )
    normalized_freq = normalize_major_index_mins_silver_freq(source_freq)
    frequency = int(normalized_freq.removesuffix("min"))
    if frequency in {90, 120}:
        return tuple(
            dict.fromkeys(
                window.target_time
                for window in major_index_mins_derived_windows(
                    silver_freq=normalized_freq,
                    exchange=normalized_exchange,
                )
            )
        )
    market_close = 15 * 60 + (30 if normalized_exchange == "BSE" else 0)
    times = ["09:30:00"]
    times.extend(
        _clock_text(value)
        for value in range(9 * 60 + 30 + frequency, 11 * 60 + 31, frequency)
    )
    afternoon = list(range(13 * 60 + frequency, market_close + 1, frequency))
    if not afternoon or afternoon[-1] != market_close:
        afternoon.append(market_close)
    times.extend(_clock_text(value) for value in afternoon)
    return tuple(times)


@dataclass(frozen=True, slots=True)
class MajorIndexMinsDerivedWindow:
    source_time: str
    window_id: int
    target_time: str
    expected_source_count: int


_MAJOR_INDEX_MINS_DERIVED_WINDOWS = {
    ("90min", "CN"): (
        MajorIndexMinsDerivedWindow("10:00:00", 1, "11:00:00", 3),
        MajorIndexMinsDerivedWindow("10:30:00", 1, "11:00:00", 3),
        MajorIndexMinsDerivedWindow("11:00:00", 1, "11:00:00", 3),
        MajorIndexMinsDerivedWindow("11:30:00", 2, "14:00:00", 3),
        MajorIndexMinsDerivedWindow("13:30:00", 2, "14:00:00", 3),
        MajorIndexMinsDerivedWindow("14:00:00", 2, "14:00:00", 3),
        MajorIndexMinsDerivedWindow("14:30:00", 3, "15:00:00", 2),
        MajorIndexMinsDerivedWindow("15:00:00", 3, "15:00:00", 2),
    ),
    ("90min", "BSE"): (
        MajorIndexMinsDerivedWindow("10:00:00", 1, "11:00:00", 3),
        MajorIndexMinsDerivedWindow("10:30:00", 1, "11:00:00", 3),
        MajorIndexMinsDerivedWindow("11:00:00", 1, "11:00:00", 3),
        MajorIndexMinsDerivedWindow("11:30:00", 2, "14:00:00", 3),
        MajorIndexMinsDerivedWindow("13:30:00", 2, "14:00:00", 3),
        MajorIndexMinsDerivedWindow("14:00:00", 2, "14:00:00", 3),
        MajorIndexMinsDerivedWindow("14:30:00", 3, "15:30:00", 3),
        MajorIndexMinsDerivedWindow("15:00:00", 3, "15:30:00", 3),
        MajorIndexMinsDerivedWindow("15:30:00", 3, "15:30:00", 3),
    ),
    ("120min", "CN"): (
        MajorIndexMinsDerivedWindow("09:30:00", 1, "10:30:00", 2),
        MajorIndexMinsDerivedWindow("10:30:00", 1, "10:30:00", 2),
        MajorIndexMinsDerivedWindow("11:30:00", 2, "14:00:00", 2),
        MajorIndexMinsDerivedWindow("14:00:00", 2, "14:00:00", 2),
    ),
    ("120min", "BSE"): (
        MajorIndexMinsDerivedWindow("09:30:00", 1, "10:30:00", 2),
        MajorIndexMinsDerivedWindow("10:30:00", 1, "10:30:00", 2),
        MajorIndexMinsDerivedWindow("11:30:00", 2, "14:00:00", 2),
        MajorIndexMinsDerivedWindow("14:00:00", 2, "14:00:00", 2),
    ),
}


def major_index_mins_derived_windows(
    *,
    silver_freq: str,
    exchange: str,
) -> tuple[MajorIndexMinsDerivedWindow, ...]:
    normalized_freq = normalize_major_index_mins_silver_freq(silver_freq)
    if normalized_freq not in {"90min", "120min"}:
        raise MajorIndexMinsContractError(
            f"major-index minute frequency is not derived: {silver_freq!r}"
        )
    normalized_exchange = str(exchange).strip().upper()
    market = "BSE" if normalized_exchange == "BSE" else "CN"
    if normalized_exchange not in {"XSHG", "XSHE", "BSE"}:
        raise MajorIndexMinsContractError(
            f"unsupported major-index minute exchange: {exchange!r}"
        )
    return _MAJOR_INDEX_MINS_DERIVED_WINDOWS[(normalized_freq, market)]


def source_freq_for_major_index_mins_derived_freq(value: object) -> str:
    normalized = normalize_major_index_mins_silver_freq(value)
    if normalized == "90min":
        return "30min"
    if normalized == "120min":
        return "60min"
    raise MajorIndexMinsContractError(
        f"major-index minute frequency is not derived: {value!r}"
    )


def normalize_major_index_mins_trade_date(value: str | date) -> str:
    if isinstance(value, datetime):
        raise MajorIndexMinsContractError(
            "trade date must not include a time component."
        )
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise MajorIndexMinsContractError(
            f"major-index minute trade date must be an ISO trade date: {value!r}"
        ) from exc
    if text != parsed.isoformat():
        raise MajorIndexMinsContractError(
            f"major-index minute trade date must be an ISO trade date: {value!r}"
        )
    return text


@dataclass(frozen=True, slots=True)
class MajorIndexMinsSourceScope:
    ts_code: str
    source_start_date: str
    source_end_date: str | None = None

    def __post_init__(self) -> None:
        normalized_code = str(self.ts_code).strip().upper()
        if not _TS_CODE_PATTERN.fullmatch(normalized_code):
            raise MajorIndexMinsContractError(
                f"unsupported major-index minute code: {self.ts_code!r}"
            )
        start_date = normalize_major_index_mins_trade_date(self.source_start_date)
        end_date = (
            normalize_major_index_mins_trade_date(self.source_end_date)
            if self.source_end_date is not None
            else None
        )
        if end_date is not None and end_date < start_date:
            raise MajorIndexMinsContractError(
                f"source scope end precedes start for {normalized_code}."
            )
        object.__setattr__(self, "ts_code", normalized_code)
        object.__setattr__(self, "source_start_date", start_date)
        object.__setattr__(self, "source_end_date", end_date)

    def eligible_on(self, trade_date: str | date) -> bool:
        normalized_date = normalize_major_index_mins_trade_date(trade_date)
        return self.source_start_date <= normalized_date and (
            self.source_end_date is None or normalized_date <= self.source_end_date
        )


MAJOR_INDEX_MINS_SOURCE_SCOPES = (
    MajorIndexMinsSourceScope("000001.SH", "2009-01-05"),
    MajorIndexMinsSourceScope("399001.SZ", "2009-01-05"),
    MajorIndexMinsSourceScope("399006.SZ", "2010-06-01"),
    MajorIndexMinsSourceScope("000688.SH", "2020-07-23"),
    MajorIndexMinsSourceScope("000300.SH", "2009-01-05"),
    MajorIndexMinsSourceScope("000905.SH", "2009-01-05"),
    MajorIndexMinsSourceScope("000852.SH", "2014-10-17"),
    MajorIndexMinsSourceScope("899050.BJ", "2022-11-21", "2025-10-30"),
    MajorIndexMinsSourceScope("000510.SH", "2024-10-22"),
    MajorIndexMinsSourceScope("000016.SH", "2009-01-05"),
    MajorIndexMinsSourceScope("000680.SH", "2025-01-20"),
)
MAJOR_INDEX_MINS_CODES = tuple(
    scope.ts_code for scope in MAJOR_INDEX_MINS_SOURCE_SCOPES
)
MAJOR_INDEX_MINS_DAILY_CODES = tuple(
    scope.ts_code
    for scope in MAJOR_INDEX_MINS_SOURCE_SCOPES
    if scope.source_end_date is None
)


def _validated_scope_map(
    scopes: Sequence[MajorIndexMinsSourceScope],
) -> dict[str, MajorIndexMinsSourceScope]:
    scope_map: dict[str, MajorIndexMinsSourceScope] = {}
    for scope in scopes:
        if scope.ts_code in scope_map:
            raise MajorIndexMinsContractError(
                f"duplicate source scope for {scope.ts_code}."
            )
        scope_map[scope.ts_code] = scope
    return scope_map


def major_index_mins_source_scope(
    ts_code: str,
    *,
    scopes: Sequence[MajorIndexMinsSourceScope] = MAJOR_INDEX_MINS_SOURCE_SCOPES,
) -> MajorIndexMinsSourceScope:
    normalized_code = str(ts_code).strip().upper()
    scope = _validated_scope_map(scopes).get(normalized_code)
    if scope is None:
        raise MajorIndexMinsContractError(
            f"unsupported major-index minute code: {ts_code!r}"
        )
    return scope


def effective_codes_for_date(
    trade_date: str | date,
    *,
    scopes: Sequence[MajorIndexMinsSourceScope] = MAJOR_INDEX_MINS_SOURCE_SCOPES,
) -> tuple[str, ...]:
    normalized_date = normalize_major_index_mins_trade_date(trade_date)
    scope_map = _validated_scope_map(scopes)
    return tuple(
        sorted(
            code
            for code, scope in scope_map.items()
            if scope.eligible_on(normalized_date)
        )
    )


def _sha256_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class MajorIndexMinsHistoricalFallbackRule:
    """Published Silver fallback scope for one audited historical source gap."""

    trade_date: str
    target_freq: str
    source_freq: str
    target_codes: tuple[str, ...]
    reason_code: str

    def __post_init__(self) -> None:
        normalized_date = normalize_major_index_mins_trade_date(self.trade_date)
        normalized_target = normalize_major_index_mins_silver_freq(self.target_freq)
        normalized_source = normalize_major_index_mins_source_freq(self.source_freq)
        allowed_source = {
            "5min": "1min",
            "15min": "5min",
            "30min": "5min",
            "60min": "5min",
        }.get(normalized_target)
        if allowed_source != normalized_source:
            raise MajorIndexMinsContractError(
                "unsupported major-index minute historical fallback mapping: "
                f"{normalized_source}->{normalized_target}."
            )
        normalized_codes = tuple(
            sorted(str(code).strip().upper() for code in self.target_codes)
        )
        if not normalized_codes or len(normalized_codes) != len(set(normalized_codes)):
            raise MajorIndexMinsContractError(
                "historical fallback target codes must be non-empty and unique."
            )
        if any(code.endswith(".BJ") for code in normalized_codes):
            raise MajorIndexMinsContractError(
                "historical non-BSE fallback must not include a BJ code."
            )
        effective_codes = set(effective_codes_for_date(normalized_date))
        invalid_codes = tuple(
            code for code in normalized_codes if code not in effective_codes
        )
        if invalid_codes:
            raise MajorIndexMinsContractError(
                "historical fallback codes are outside the effective source scope: "
                f"{invalid_codes!r}."
            )
        normalized_reason = str(self.reason_code).strip()
        if not normalized_reason or not re.fullmatch(r"[a-z0-9_]+", normalized_reason):
            raise MajorIndexMinsContractError(
                "historical fallback reason code must be non-empty ASCII snake_case."
            )
        object.__setattr__(self, "trade_date", normalized_date)
        object.__setattr__(self, "target_freq", normalized_target)
        object.__setattr__(self, "source_freq", normalized_source)
        object.__setattr__(self, "target_codes", normalized_codes)
        object.__setattr__(self, "reason_code", normalized_reason)


MAJOR_INDEX_MINS_NON_BSE_FALLBACK_REVISION = (
    "major_index_mins_non_bse_fallback_v1"
)

_MAJOR_INDEX_MINS_LEGACY_FIVE = (
    "000001.SH",
    "000016.SH",
    "000300.SH",
    "000905.SH",
    "399001.SZ",
)
_MAJOR_INDEX_MINS_SEPTEMBER_2010_SIX = _MAJOR_INDEX_MINS_LEGACY_FIVE + (
    "399006.SZ",
)
_MAJOR_INDEX_MINS_OCTOBER_2024_NINE = (
    "000001.SH",
    "000016.SH",
    "000300.SH",
    "000510.SH",
    "000688.SH",
    "000852.SH",
    "000905.SH",
    "399001.SZ",
    "399006.SZ",
)
_MAJOR_INDEX_MINS_CURRENT_NON_BSE_TEN = (
    "000001.SH",
    "000016.SH",
    "000300.SH",
    "000510.SH",
    "000680.SH",
    "000688.SH",
    "000852.SH",
    "000905.SH",
    "399001.SZ",
    "399006.SZ",
)


def _historical_fallback_rule(
    trade_date: str,
    target_freq: str,
    source_freq: str,
    target_codes: tuple[str, ...],
) -> MajorIndexMinsHistoricalFallbackRule:
    return MajorIndexMinsHistoricalFallbackRule(
        trade_date=trade_date,
        target_freq=target_freq,
        source_freq=source_freq,
        target_codes=target_codes,
        reason_code=f"native_{target_freq.removesuffix('min')}m_source_empty",
    )


MAJOR_INDEX_MINS_NON_BSE_FALLBACK_RULES = (
    _historical_fallback_rule(
        "2009-05-05", "15min", "5min", _MAJOR_INDEX_MINS_LEGACY_FIVE
    ),
    _historical_fallback_rule(
        "2009-06-05", "15min", "5min", _MAJOR_INDEX_MINS_LEGACY_FIVE
    ),
    _historical_fallback_rule(
        "2009-12-04", "15min", "5min", _MAJOR_INDEX_MINS_LEGACY_FIVE
    ),
    _historical_fallback_rule(
        "2010-09-02", "5min", "1min", _MAJOR_INDEX_MINS_SEPTEMBER_2010_SIX
    ),
    _historical_fallback_rule(
        "2024-10-30", "15min", "5min", _MAJOR_INDEX_MINS_OCTOBER_2024_NINE
    ),
    _historical_fallback_rule(
        "2025-07-04", "30min", "5min", _MAJOR_INDEX_MINS_CURRENT_NON_BSE_TEN
    ),
    _historical_fallback_rule(
        "2025-07-04", "60min", "5min", _MAJOR_INDEX_MINS_CURRENT_NON_BSE_TEN
    ),
    _historical_fallback_rule(
        "2025-07-11", "15min", "5min", _MAJOR_INDEX_MINS_CURRENT_NON_BSE_TEN
    ),
    _historical_fallback_rule(
        "2025-07-11", "30min", "5min", _MAJOR_INDEX_MINS_CURRENT_NON_BSE_TEN
    ),
    _historical_fallback_rule(
        "2025-07-11", "60min", "5min", _MAJOR_INDEX_MINS_CURRENT_NON_BSE_TEN
    ),
    _historical_fallback_rule(
        "2025-07-18", "30min", "5min", _MAJOR_INDEX_MINS_CURRENT_NON_BSE_TEN
    ),
    _historical_fallback_rule(
        "2025-07-18", "60min", "5min", _MAJOR_INDEX_MINS_CURRENT_NON_BSE_TEN
    ),
    _historical_fallback_rule(
        "2025-07-25", "60min", "5min", _MAJOR_INDEX_MINS_CURRENT_NON_BSE_TEN
    ),
    _historical_fallback_rule(
        "2025-08-01", "30min", "5min", _MAJOR_INDEX_MINS_CURRENT_NON_BSE_TEN
    ),
    _historical_fallback_rule(
        "2025-08-01", "60min", "5min", _MAJOR_INDEX_MINS_CURRENT_NON_BSE_TEN
    ),
)

_MAJOR_INDEX_MINS_NON_BSE_FALLBACK_BY_KEY = {
    (rule.trade_date, rule.target_freq): rule
    for rule in MAJOR_INDEX_MINS_NON_BSE_FALLBACK_RULES
}
if len(_MAJOR_INDEX_MINS_NON_BSE_FALLBACK_BY_KEY) != len(
    MAJOR_INDEX_MINS_NON_BSE_FALLBACK_RULES
):
    raise MajorIndexMinsContractError(
        "duplicate major-index minute historical fallback rule."
    )


def major_index_mins_historical_fallback_rule(
    *,
    trade_date: str | date,
    target_freq: object,
) -> MajorIndexMinsHistoricalFallbackRule | None:
    normalized_date = normalize_major_index_mins_trade_date(trade_date)
    normalized_target = normalize_major_index_mins_silver_freq(target_freq)
    return _MAJOR_INDEX_MINS_NON_BSE_FALLBACK_BY_KEY.get(
        (normalized_date, normalized_target)
    )


def major_index_mins_historical_fallback_fingerprint() -> str:
    return _sha256_payload(
        {
            "revision": MAJOR_INDEX_MINS_NON_BSE_FALLBACK_REVISION,
            "rules": [
                {
                    "trade_date": rule.trade_date,
                    "target_freq": rule.target_freq,
                    "source_freq": rule.source_freq,
                    "target_codes": rule.target_codes,
                    "reason_code": rule.reason_code,
                }
                for rule in MAJOR_INDEX_MINS_NON_BSE_FALLBACK_RULES
            ],
        }
    )


def source_scope_hash_for_date(
    trade_date: str | date,
    *,
    scopes: Sequence[MajorIndexMinsSourceScope] = MAJOR_INDEX_MINS_SOURCE_SCOPES,
) -> str:
    normalized_date = normalize_major_index_mins_trade_date(trade_date)
    return _sha256_payload(
        {
            "trade_date": normalized_date,
            "expected_codes": effective_codes_for_date(
                normalized_date,
                scopes=scopes,
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class MajorIndexMinsSourceRevision:
    scope_revision: str
    scope_hash: str
    request_hash: str
    result_hash: str
    revision: str


def build_major_index_mins_source_revision(
    *,
    ts_codes: Sequence[str],
    source_freq: str,
    start_datetime: str,
    end_datetime: str,
    rows: Sequence[Mapping[str, object]],
) -> MajorIndexMinsSourceRevision:
    normalized_codes = tuple(sorted(str(code).strip().upper() for code in ts_codes))
    scope_revision = MAJOR_INDEX_MINS_SCOPE_REVISION
    scope_hash = _sha256_payload({"codes": normalized_codes})
    request_hash = _sha256_payload(
        {
            "api_name": "idx_mins",
            "codes": normalized_codes,
            "freq": source_freq,
            "start_date": start_datetime,
            "end_date": end_datetime,
            "fields": MAJOR_INDEX_MINS_SOURCE_COLUMNS,
            "limit": MAJOR_INDEX_MINS_PAGE_LIMIT,
        }
    )
    result_hash = _sha256_payload(
        sorted(
            (dict(row) for row in rows),
            key=lambda row: (str(row.get("ts_code")), str(row.get("trade_time"))),
        )
    )
    revision = _sha256_payload(
        {
            "scope_revision": scope_revision,
            "scope_hash": scope_hash,
            "request_hash": request_hash,
            "result_hash": result_hash,
        }
    )
    return MajorIndexMinsSourceRevision(
        scope_revision=scope_revision,
        scope_hash=scope_hash,
        request_hash=request_hash,
        result_hash=result_hash,
        revision=revision,
    )
