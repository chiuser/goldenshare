"""Stable contracts for stock minute frequency assets."""

from typing import Literal


STK_MINS_FREQS = (1, 5, 15, 30, 60)
STK_MINS_RAW_SOURCES = ("tushare", "prod_db")
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
    """Normalize a stock minute frequency to the canonical integer value."""

    try:
        normalized = int(str(freq).strip())
    except (TypeError, ValueError) as error:
        allowed = ", ".join(str(item) for item in STK_MINS_FREQS)
        raise ValueError(f"Unsupported stk_mins freq: {freq!r}. Allowed: {allowed}.") from error

    if normalized not in STK_MINS_FREQS:
        allowed = ", ".join(str(item) for item in STK_MINS_FREQS)
        raise ValueError(f"Unsupported stk_mins freq: {freq!r}. Allowed: {allowed}.")
    return normalized


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
