"""Stable contracts for stock minute frequency assets."""

from typing import Literal


STK_MINS_SOURCE_FREQS = (1, 5, 15, 30, 60)
STK_MINS_QFQ_NATIVE_FREQS = STK_MINS_SOURCE_FREQS
STK_MINS_QFQ_DERIVED_FREQS = (90, 120)
STK_MINS_QFQ_FREQS = STK_MINS_QFQ_NATIVE_FREQS + STK_MINS_QFQ_DERIVED_FREQS
STK_MINS_QFQ_DERIVED_SOURCE_FREQS = {
    90: 30,
    120: 60,
}
STK_MINS_FREQS = STK_MINS_SOURCE_FREQS
STK_MINS_RAW_SOURCES = ("tushare", "prod_db")
STK_MINS_RAW_HISTORY_START_DATE = "2009-01-05"
STK_MINS_SILVER_HISTORY_START_DATE = "2014-01-01"
STK_MINS_QFQ_HISTORY_START_DATE = STK_MINS_SILVER_HISTORY_START_DATE
STK_MINS_MACD_KDJ_BASELINE_START_DATE = STK_MINS_QFQ_HISTORY_START_DATE
STK_MINS_CONTINUITY_WINDOW_LIMIT = 10
STK_MINS_CONTINUITY_SAMPLE_LIMIT = 10
StkMinsRawSource = Literal["tushare", "prod_db"]

_STK_MINS_EXCHANGE_BY_TS_CODE_SUFFIX = {
    ".SH": "XSHG",
    ".SZ": "XSHE",
    ".BJ": "BSE",
}

_SILVER_STK_MINS_EXCHANGE_BY_TS_CODE_SUFFIX = {
    ".SH": "SSE",
    ".SZ": "SZSE",
    ".BJ": "BSE",
}


def normalize_stk_mins_freq(freq: int | str) -> int:
    """Normalize a source stock minute frequency to the canonical integer value."""

    try:
        normalized = int(str(freq).strip())
    except (TypeError, ValueError) as error:
        allowed = ", ".join(str(item) for item in STK_MINS_FREQS)
        raise ValueError(f"Unsupported stk_mins freq: {freq!r}. Allowed: {allowed}.") from error

    if normalized not in STK_MINS_FREQS:
        allowed = ", ".join(str(item) for item in STK_MINS_FREQS)
        raise ValueError(f"Unsupported stk_mins freq: {freq!r}. Allowed: {allowed}.")
    return normalized


def normalize_stk_mins_qfq_freq(freq: int | str) -> int:
    """Normalize a gold qfq stock minute frequency to the canonical integer value."""

    try:
        normalized = int(str(freq).strip())
    except (TypeError, ValueError) as error:
        allowed = ", ".join(str(item) for item in STK_MINS_QFQ_FREQS)
        raise ValueError(
            f"Unsupported stk_mins qfq freq: {freq!r}. Allowed: {allowed}."
        ) from error

    if normalized not in STK_MINS_QFQ_FREQS:
        allowed = ", ".join(str(item) for item in STK_MINS_QFQ_FREQS)
        raise ValueError(
            f"Unsupported stk_mins qfq freq: {freq!r}. Allowed: {allowed}."
        )
    return normalized


def qfq_source_freq_for_derived_freq(freq: int | str) -> int:
    normalized = normalize_stk_mins_qfq_freq(freq)
    if normalized not in STK_MINS_QFQ_DERIVED_SOURCE_FREQS:
        allowed = ", ".join(str(item) for item in STK_MINS_QFQ_DERIVED_FREQS)
        raise ValueError(
            f"Unsupported derived stk_mins qfq freq: {freq!r}. Allowed: {allowed}."
        )
    return STK_MINS_QFQ_DERIVED_SOURCE_FREQS[normalized]


def normalize_stk_mins_raw_source(source: str) -> StkMinsRawSource:
    normalized = source.strip().lower()
    if normalized not in STK_MINS_RAW_SOURCES:
        allowed = ", ".join(STK_MINS_RAW_SOURCES)
        raise ValueError(f"Unsupported stk_mins raw source: {source!r}. Allowed: {allowed}.")
    return normalized  # type: ignore[return-value]


def derive_stk_mins_exchange_from_ts_code(ts_code: str) -> str:
    normalized = ts_code.strip().upper()
    for suffix, exchange in _STK_MINS_EXCHANGE_BY_TS_CODE_SUFFIX.items():
        if normalized.endswith(suffix):
            return exchange
    allowed_suffixes = ", ".join(sorted(_STK_MINS_EXCHANGE_BY_TS_CODE_SUFFIX))
    raise ValueError(
        "Unsupported stk_mins ts_code suffix for exchange derivation: "
        f"{ts_code!r}. Allowed suffixes: {allowed_suffixes}."
    )


def derive_silver_stk_mins_exchange_from_ts_code(ts_code: str) -> str:
    normalized = ts_code.strip().upper()
    for suffix, exchange in _SILVER_STK_MINS_EXCHANGE_BY_TS_CODE_SUFFIX.items():
        if normalized.endswith(suffix):
            return exchange
    allowed_suffixes = ", ".join(sorted(_SILVER_STK_MINS_EXCHANGE_BY_TS_CODE_SUFFIX))
    raise ValueError(
        "Unsupported silver stk_mins ts_code suffix for exchange derivation: "
        f"{ts_code!r}. Allowed suffixes: {allowed_suffixes}."
    )
