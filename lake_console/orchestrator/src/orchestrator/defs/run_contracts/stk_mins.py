"""Stable contracts for stock minute frequency assets."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time
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
STK_MINS_RAW_RUN_START = time(19, 30)
STK_MINS_RAW_SENSOR_MINIMUM_INTERVAL_SECONDS = 900
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


@dataclass(frozen=True, slots=True)
class ProdStkMinsCompletionReference:
    """Small immutable source-completion fact passed from sensor to raw assets."""

    task_run_id: int
    trade_date: str
    ended_at: str
    full_market: bool
    frequency_set_hash: str
    expected_code_count: int
    expected_code_hash: str
    frequency_code_counts: tuple[tuple[int, int], ...]
    coverage_observed_at: str
    reference_fingerprint: str

    def validate(self) -> "ProdStkMinsCompletionReference":
        if self.task_run_id <= 0:
            raise ValueError("prod_completion_reference.task_run_id must be positive.")
        if not self.full_market:
            raise ValueError("prod_completion_reference.full_market must be true.")
        normalized_trade_date = _normalize_iso_trade_date(
            self.trade_date,
            field_name="prod_completion_reference.trade_date",
        )
        normalized_ended_at = _normalize_timezone_datetime(
            self.ended_at,
            field_name="prod_completion_reference.ended_at",
        )
        normalized_observed_at = _normalize_timezone_datetime(
            self.coverage_observed_at,
            field_name="prod_completion_reference.coverage_observed_at",
        )
        if normalized_ended_at > normalized_observed_at:
            raise ValueError(
                "prod_completion_reference.coverage_observed_at must not precede ended_at."
            )
        if self.expected_code_count <= 0:
            raise ValueError(
                "prod_completion_reference.expected_code_count must be positive."
            )
        if _normalize_md5(self.expected_code_hash, field_name="expected_code_hash") != self.expected_code_hash:
            raise ValueError("prod_completion_reference.expected_code_hash must be lowercase MD5.")
        if (
            _normalize_sha256(
                self.frequency_set_hash,
                field_name="frequency_set_hash",
            )
            != self.frequency_set_hash
        ):
            raise ValueError("prod_completion_reference.frequency_set_hash must be lowercase SHA-256.")
        if (
            _normalize_sha256(
                self.reference_fingerprint,
                field_name="reference_fingerprint",
            )
            != self.reference_fingerprint
        ):
            raise ValueError(
                "prod_completion_reference.reference_fingerprint must be lowercase SHA-256."
            )
        expected_counts = tuple(
            (freq, self.expected_code_count) for freq in STK_MINS_SOURCE_FREQS
        )
        if self.frequency_code_counts != expected_counts:
            raise ValueError(
                "prod_completion_reference.frequency_code_counts must contain each "
                "source frequency exactly once at expected_code_count."
            )
        expected_frequency_set_hash = stk_mins_frequency_set_hash(STK_MINS_SOURCE_FREQS)
        if self.frequency_set_hash != expected_frequency_set_hash:
            raise ValueError(
                "prod_completion_reference.frequency_set_hash does not match source frequencies."
            )
        expected_fingerprint = _completion_reference_fingerprint(
            task_run_id=self.task_run_id,
            trade_date=normalized_trade_date,
            ended_at=normalized_ended_at.isoformat(),
            expected_code_count=self.expected_code_count,
            expected_code_hash=self.expected_code_hash,
            frequency_code_counts=self.frequency_code_counts,
            coverage_observed_at=normalized_observed_at.isoformat(),
        )
        if self.reference_fingerprint != expected_fingerprint:
            raise ValueError("prod_completion_reference.reference_fingerprint is invalid.")
        return self

    def to_config_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "task_run_id": self.task_run_id,
            "trade_date": self.trade_date,
            "ended_at": self.ended_at,
            "full_market": self.full_market,
            "frequency_set_hash": self.frequency_set_hash,
            "expected_code_count": self.expected_code_count,
            "expected_code_hash": self.expected_code_hash,
            "frequency_code_counts": {
                str(freq): count for freq, count in self.frequency_code_counts
            },
            "coverage_observed_at": self.coverage_observed_at,
            "reference_fingerprint": self.reference_fingerprint,
        }

    @classmethod
    def from_config_mapping(
        cls,
        value: Mapping[str, object] | None,
    ) -> "ProdStkMinsCompletionReference":
        if not isinstance(value, Mapping):
            raise ValueError("prod_completion_reference must be a mapping.")
        counts_value = value.get("frequency_code_counts")
        if not isinstance(counts_value, Mapping):
            raise ValueError(
                "prod_completion_reference.frequency_code_counts must be a mapping."
            )
        try:
            frequency_code_counts = tuple(
                (freq, int(counts_value[str(freq)]))
                for freq in STK_MINS_SOURCE_FREQS
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "prod_completion_reference.frequency_code_counts is incomplete."
            ) from error
        reference = cls(
            task_run_id=_positive_int(value.get("task_run_id"), field_name="task_run_id"),
            trade_date=str(value.get("trade_date") or ""),
            ended_at=str(value.get("ended_at") or ""),
            full_market=value.get("full_market") is True,
            frequency_set_hash=str(value.get("frequency_set_hash") or ""),
            expected_code_count=_positive_int(
                value.get("expected_code_count"),
                field_name="expected_code_count",
            ),
            expected_code_hash=str(value.get("expected_code_hash") or ""),
            frequency_code_counts=frequency_code_counts,
            coverage_observed_at=str(value.get("coverage_observed_at") or ""),
            reference_fingerprint=str(value.get("reference_fingerprint") or ""),
        )
        return reference.validate()


def build_prod_stk_mins_completion_reference(
    *,
    task_run_id: int,
    trade_date: str,
    ended_at: str,
    expected_code_count: int,
    expected_code_hash: str,
    frequency_code_counts: Mapping[int, int],
    coverage_observed_at: str,
) -> ProdStkMinsCompletionReference:
    """Build the only run-config source-completion reference shape."""

    normalized_trade_date = _normalize_iso_trade_date(
        trade_date,
        field_name="trade_date",
    )
    normalized_ended_at = _normalize_timezone_datetime(
        ended_at,
        field_name="ended_at",
    ).isoformat()
    normalized_observed_at = _normalize_timezone_datetime(
        coverage_observed_at,
        field_name="coverage_observed_at",
    ).isoformat()
    normalized_code_hash = _normalize_md5(
        expected_code_hash,
        field_name="expected_code_hash",
    )
    normalized_counts = tuple(
        (freq, int(frequency_code_counts.get(freq, -1)))
        for freq in STK_MINS_SOURCE_FREQS
    )
    reference = ProdStkMinsCompletionReference(
        task_run_id=_positive_int(task_run_id, field_name="task_run_id"),
        trade_date=normalized_trade_date,
        ended_at=normalized_ended_at,
        full_market=True,
        frequency_set_hash=stk_mins_frequency_set_hash(STK_MINS_SOURCE_FREQS),
        expected_code_count=_positive_int(
            expected_code_count,
            field_name="expected_code_count",
        ),
        expected_code_hash=normalized_code_hash,
        frequency_code_counts=normalized_counts,
        coverage_observed_at=normalized_observed_at,
        reference_fingerprint=_completion_reference_fingerprint(
            task_run_id=_positive_int(task_run_id, field_name="task_run_id"),
            trade_date=normalized_trade_date,
            ended_at=normalized_ended_at,
            expected_code_count=_positive_int(
                expected_code_count,
                field_name="expected_code_count",
            ),
            expected_code_hash=normalized_code_hash,
            frequency_code_counts=normalized_counts,
            coverage_observed_at=normalized_observed_at,
        ),
    )
    return reference.validate()


def stk_mins_frequency_set_hash(freqs: tuple[int, ...]) -> str:
    normalized = tuple(sorted({normalize_stk_mins_freq(freq) for freq in freqs}))
    if normalized != STK_MINS_SOURCE_FREQS:
        raise ValueError("freqs must equal the five canonical source frequencies.")
    return _sha256_json(list(normalized))


def _completion_reference_fingerprint(
    *,
    task_run_id: int,
    trade_date: str,
    ended_at: str,
    expected_code_count: int,
    expected_code_hash: str,
    frequency_code_counts: tuple[tuple[int, int], ...],
    coverage_observed_at: str,
) -> str:
    return _sha256_json(
        {
            "task_run_id": task_run_id,
            "trade_date": trade_date,
            "ended_at": ended_at,
            "full_market": True,
            "frequency_set_hash": stk_mins_frequency_set_hash(STK_MINS_SOURCE_FREQS),
            "expected_code_count": expected_code_count,
            "expected_code_hash": expected_code_hash,
            "frequency_code_counts": list(frequency_code_counts),
            "coverage_observed_at": coverage_observed_at,
        }
    )


def _normalize_iso_trade_date(value: str, *, field_name: str) -> str:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date().isoformat()
    except ValueError as error:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.") from error


def _normalize_timezone_datetime(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError as error:
        raise ValueError(f"{field_name} must use ISO-8601 datetime format.") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone offset.")
    return parsed


def _normalize_md5(value: str, *, field_name: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 32 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"{field_name} must be a lowercase MD5.")
    return normalized


def _normalize_sha256(value: str, *, field_name: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"{field_name} must be a lowercase SHA-256.")
    return normalized


def _positive_int(value: object, *, field_name: str) -> int:
    try:
        normalized = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a positive integer.") from error
    if normalized <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return normalized


def _sha256_json(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
