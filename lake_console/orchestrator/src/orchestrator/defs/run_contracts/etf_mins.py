"""Stable pure contracts for the ETF minute data set."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime

import dagster as dg

from orchestrator.defs.run_contracts.etf_basic import (
    EtfBasicSilverSnapshotReference,
)

ETF_MINS_SOURCE_FREQS = ("1min", "5min", "15min", "30min", "60min")
ETF_MINS_ASSET_FREQS = (1, 5, 15, 30, 60)
ETF_MINS_SENSOR_WINDOW_LIMIT = 10
ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT = 20
ETF_MINS_BOOTSTRAP_MAX_TARGET_FILES = 10_000
ETF_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER = 1.25
ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT = 20
ETF_MINS_HISTORICAL_PROTECTION_CUTOFF = date(2026, 1, 1)
ETF_MINS_SOURCE_COLUMNS = (
    "ts_code",
    "freq",
    "trade_time",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
    "vwap",
    "exchange",
)

ETF_MINS_SOURCE_FREQ_BY_ASSET_FREQ = {
    asset_freq: source_freq
    for asset_freq, source_freq in zip(
        ETF_MINS_ASSET_FREQS,
        ETF_MINS_SOURCE_FREQS,
        strict=True,
    )
}
ETF_MINS_ASSET_FREQ_BY_SOURCE_FREQ = {
    source_freq: asset_freq
    for asset_freq, source_freq in ETF_MINS_SOURCE_FREQ_BY_ASSET_FREQ.items()
}
ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX = {
    "SH": "XSHG",
    "SZ": "XSHE",
}
ETF_MINS_RAW_OBSERVATION_REASON_CODES = (
    "all_frequencies_empty",
    "partial_frequency_empty",
    "expected_code_missing",
    "internal_grid_gap_candidate",
    "boundary_time_variant_candidate",
    "zero_volume_bar_observed",
    "price_domain_anomaly",
    "volume_amount_domain_anomaly",
    "vwap_domain_anomaly",
    "off_session_time_observed",
    "known_non_required_code_present",
    "retained_legacy_code_present",
    "unexplained_new_code_observed",
    "key_contract_anomaly",
    "partition_contract_anomaly",
    "exchange_identity_anomaly",
)
ETF_MINS_RAW_APPROVED_POLICY_VERSION = "etf_mins_gap_policy_v1"
ETF_MINS_RAW_DECISION_BLOCKING_REASON_CODES = (
    "all_frequencies_empty",
    "partial_frequency_empty",
    "expected_code_missing",
    "minute_grid_contract_anomaly",
    "boundary_time_variant_candidate",
    "price_domain_anomaly",
    "volume_amount_domain_anomaly",
    "vwap_domain_anomaly",
    "off_session_time_observed",
    "unexplained_new_code_observed",
    "key_contract_anomaly",
    "partition_contract_anomaly",
    "exchange_identity_anomaly",
)
ETF_MINS_RAW_DECISION_WARNING_REASON_CODES = (
    "full_zero_volume_etf_day_observed",
    "known_non_required_code_present",
    "retained_legacy_code_present",
)

_ISO_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _build_etf_mins_clock_grid(
    *segments: tuple[int, int, int],
) -> tuple[str, ...]:
    return tuple(
        f"{minute // 60:02d}:{minute % 60:02d}:00"
        for start_minute, end_minute, step_minutes in segments
        for minute in range(start_minute, end_minute + 1, step_minutes)
    )


@dataclass(frozen=True, slots=True)
class EtfMinsRawDecisionPolicy:
    """One immutable, registered ETF minute Raw admission policy."""

    version: str
    expected_clock_times_by_source_freq: tuple[tuple[str, tuple[str, ...]], ...]
    blocking_reason_codes: tuple[str, ...]
    warning_reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_kind": "etf_mins_raw_decision_policy",
            "version": self.version,
            "expected_clock_times_by_source_freq": {
                source_freq: list(clock_times)
                for source_freq, clock_times in self.expected_clock_times_by_source_freq
            },
            "blocking_reason_codes": list(self.blocking_reason_codes),
            "warning_reason_codes": list(self.warning_reason_codes),
            "standard_lunch_gap_action": "accept",
            "partial_zero_volume_bar_action": "accept",
            "full_zero_volume_etf_day_action": "warn_and_admit",
            "full_zero_volume_etf_day_frequency_scope": ("all_five_source_frequencies"),
            "known_non_required_code_action": "warn_and_admit",
            "retained_legacy_code_action": "warn_and_admit",
        }

    @property
    def policy_hash(self) -> str:
        return _sha256_json(self.to_dict())

    def expected_clock_times(self, source_freq: object) -> tuple[str, ...]:
        normalized = normalize_etf_mins_source_freq(source_freq)
        return dict(self.expected_clock_times_by_source_freq)[normalized]


_ETF_MINS_RAW_DECISION_POLICIES = {
    ETF_MINS_RAW_APPROVED_POLICY_VERSION: EtfMinsRawDecisionPolicy(
        version=ETF_MINS_RAW_APPROVED_POLICY_VERSION,
        expected_clock_times_by_source_freq=(
            (
                "1min",
                _build_etf_mins_clock_grid(
                    (9 * 60 + 30, 11 * 60 + 30, 1),
                    (13 * 60 + 1, 15 * 60, 1),
                ),
            ),
            (
                "5min",
                _build_etf_mins_clock_grid(
                    (9 * 60 + 30, 11 * 60 + 30, 5),
                    (13 * 60 + 5, 15 * 60, 5),
                ),
            ),
            (
                "15min",
                _build_etf_mins_clock_grid(
                    (9 * 60 + 30, 11 * 60 + 30, 15),
                    (13 * 60 + 15, 15 * 60, 15),
                ),
            ),
            (
                "30min",
                _build_etf_mins_clock_grid(
                    (9 * 60 + 30, 11 * 60 + 30, 30),
                    (13 * 60 + 30, 15 * 60, 30),
                ),
            ),
            (
                "60min",
                _build_etf_mins_clock_grid(
                    (9 * 60 + 30, 11 * 60 + 30, 60),
                    (14 * 60, 15 * 60, 60),
                ),
            ),
        ),
        blocking_reason_codes=ETF_MINS_RAW_DECISION_BLOCKING_REASON_CODES,
        warning_reason_codes=ETF_MINS_RAW_DECISION_WARNING_REASON_CODES,
    )
}


def get_etf_mins_raw_decision_policy(
    version: object,
) -> EtfMinsRawDecisionPolicy:
    normalized = str(version or "").strip()
    try:
        return _ETF_MINS_RAW_DECISION_POLICIES[normalized]
    except KeyError as error:
        raise ValueError(
            f"ETF minute Raw decision policy is not registered: {normalized!r}."
        ) from error


@dataclass(frozen=True, slots=True)
class EtfMinsRequestableTarget:
    """One code from the frozen ETF Basic request scope."""

    ts_code: str
    list_date: date
    exchange: str


@dataclass(frozen=True, slots=True)
class EtfMinsProdCoverageReference:
    """Small immutable five-frequency Prod coverage fact for one trade date."""

    trade_date: str
    basic_reference_fingerprint: str
    expected_code_count: int
    expected_code_hash: str
    frequency_coverages: tuple[tuple[str, int, int, int], ...]
    coverage_observed_at: str
    coverage_fingerprint: str

    def validate(self) -> EtfMinsProdCoverageReference:
        normalized_trade_date = normalize_etf_mins_trade_date(self.trade_date)
        normalized_basic_fingerprint = _normalize_sha256(
            self.basic_reference_fingerprint,
            field_name="basic_reference_fingerprint",
        )
        expected_code_count = _positive_int(
            self.expected_code_count,
            field_name="expected_code_count",
        )
        normalized_expected_code_hash = _normalize_sha256(
            self.expected_code_hash,
            field_name="expected_code_hash",
        )
        normalized_coverages = _normalize_etf_mins_frequency_coverages(
            self.frequency_coverages,
            expected_code_count=expected_code_count,
        )
        if any(missing_count != 0 for _, _, _, missing_count in normalized_coverages):
            raise ValueError(
                "ETF minute Prod coverage reference requires all five frequencies ready."
            )
        normalized_observed_at = _normalize_timezone_datetime(
            self.coverage_observed_at,
            field_name="coverage_observed_at",
        )
        normalized_fingerprint = _normalize_sha256(
            self.coverage_fingerprint,
            field_name="coverage_fingerprint",
        )
        expected_fingerprint = _etf_mins_coverage_fingerprint(
            trade_date=normalized_trade_date,
            basic_reference_fingerprint=normalized_basic_fingerprint,
            expected_code_count=expected_code_count,
            expected_code_hash=normalized_expected_code_hash,
            frequency_coverages=normalized_coverages,
            coverage_observed_at=normalized_observed_at,
        )
        if normalized_fingerprint != expected_fingerprint:
            raise ValueError("ETF minute coverage_fingerprint is invalid.")
        return self

    def to_config_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "trade_date": self.trade_date,
            "basic_reference_fingerprint": self.basic_reference_fingerprint,
            "expected_code_count": self.expected_code_count,
            "expected_code_hash": self.expected_code_hash,
            "frequency_coverages": {
                source_freq: {
                    "expected_code_count": expected_count,
                    "present_code_count": present_count,
                    "missing_code_count": missing_count,
                }
                for source_freq, expected_count, present_count, missing_count in (
                    self.frequency_coverages
                )
            },
            "coverage_observed_at": self.coverage_observed_at,
            "coverage_fingerprint": self.coverage_fingerprint,
        }

    @classmethod
    def from_config_mapping(
        cls,
        value: Mapping[str, object] | None,
    ) -> EtfMinsProdCoverageReference:
        if not isinstance(value, Mapping):
            raise TypeError("prod_coverage_reference must be a mapping.")
        coverage_value = value.get("frequency_coverages")
        if not isinstance(coverage_value, Mapping):
            raise TypeError(
                "prod_coverage_reference.frequency_coverages must be a mapping."
            )
        normalized_coverages: list[tuple[str, int, int, int]] = []
        for source_freq in ETF_MINS_SOURCE_FREQS:
            item = coverage_value.get(source_freq)
            if not isinstance(item, Mapping):
                raise TypeError(
                    "prod_coverage_reference.frequency_coverages is incomplete."
                )
            normalized_coverages.append(
                (
                    source_freq,
                    _non_negative_int(
                        item.get("expected_code_count"),
                        field_name=f"{source_freq}.expected_code_count",
                    ),
                    _non_negative_int(
                        item.get("present_code_count"),
                        field_name=f"{source_freq}.present_code_count",
                    ),
                    _non_negative_int(
                        item.get("missing_code_count"),
                        field_name=f"{source_freq}.missing_code_count",
                    ),
                )
            )
        return cls(
            trade_date=str(value.get("trade_date") or ""),
            basic_reference_fingerprint=str(
                value.get("basic_reference_fingerprint") or ""
            ),
            expected_code_count=_positive_int(
                value.get("expected_code_count"),
                field_name="expected_code_count",
            ),
            expected_code_hash=str(value.get("expected_code_hash") or ""),
            frequency_coverages=tuple(normalized_coverages),
            coverage_observed_at=str(value.get("coverage_observed_at") or ""),
            coverage_fingerprint=str(value.get("coverage_fingerprint") or ""),
        ).validate()


class EtfMinsFrequencyCoverageConfig(dg.Config):
    """One typed frequency entry carried inside daily Raw run config."""

    source_freq: str
    expected_code_count: int
    present_code_count: int
    missing_code_count: int


class EtfMinsProdCoverageConfig(dg.Config):
    """Dagster-serializable form of the immutable Prod coverage reference."""

    trade_date: str
    basic_reference_fingerprint: str
    expected_code_count: int
    expected_code_hash: str
    frequency_coverages: list[EtfMinsFrequencyCoverageConfig]
    coverage_observed_at: str
    coverage_fingerprint: str

    def to_reference(self) -> EtfMinsProdCoverageReference:
        payload = self.model_dump()
        coverage_items = payload.pop("frequency_coverages")
        payload["frequency_coverages"] = {
            str(item["source_freq"]): {
                "expected_code_count": item["expected_code_count"],
                "present_code_count": item["present_code_count"],
                "missing_code_count": item["missing_code_count"],
            }
            for item in coverage_items
        }
        return EtfMinsProdCoverageReference.from_config_mapping(payload)


class EtfMinsRawConfig(dg.Config):
    """The two frozen references accepted by every daily ETF minute Raw asset."""

    basic_snapshot_reference: EtfBasicSilverSnapshotReference
    prod_coverage_reference: EtfMinsProdCoverageConfig


def build_etf_mins_raw_run_config(
    *,
    partition_key: str,
    basic_reference: EtfBasicSilverSnapshotReference,
    prod_coverage_reference: EtfMinsProdCoverageReference,
) -> dict[str, object]:
    """Serialize one identical reference pair for all five Raw asset ops."""

    normalized_partition = normalize_etf_mins_trade_date(partition_key)
    normalized_basic = basic_reference.validate_contract()
    normalized_coverage = prod_coverage_reference.validate()
    if normalized_coverage.trade_date != normalized_partition:
        raise ValueError(
            "ETF minute coverage reference trade_date does not match the run partition."
        )
    if normalized_coverage.basic_reference_fingerprint != (
        normalized_basic.reference_fingerprint
    ):
        raise ValueError(
            "ETF minute coverage reference is not bound to the frozen Basic reference."
        )
    if (
        normalized_coverage.expected_code_count
        != normalized_basic.requestable_code_count
    ):
        raise ValueError(
            "ETF minute coverage reference expected count does not match frozen Basic."
        )
    config = {
        "basic_snapshot_reference": normalized_basic.model_dump(),
        "prod_coverage_reference": {
            **{
                key: value
                for key, value in normalized_coverage.to_config_dict().items()
                if key != "frequency_coverages"
            },
            "frequency_coverages": [
                {
                    "source_freq": source_freq,
                    "expected_code_count": expected_count,
                    "present_code_count": present_count,
                    "missing_code_count": missing_count,
                }
                for source_freq, expected_count, present_count, missing_count in (
                    normalized_coverage.frequency_coverages
                )
            ],
        },
    }
    return {
        "ops": {
            f"raw_etf_mins_{asset_freq}m": {"config": config}
            for asset_freq in ETF_MINS_ASSET_FREQS
        }
    }


def normalize_etf_mins_requestable_targets(
    targets: Iterable[EtfMinsRequestableTarget | Mapping[str, object]],
) -> tuple[EtfMinsRequestableTarget, ...]:
    normalized: list[EtfMinsRequestableTarget] = []
    seen_codes: set[str] = set()
    for target in targets:
        if isinstance(target, EtfMinsRequestableTarget):
            ts_code_value = target.ts_code
            list_date_value = target.list_date
            exchange_value = target.exchange
        elif isinstance(target, Mapping):
            ts_code_value = target.get("ts_code")
            list_date_value = target.get("list_date")
            exchange_value = target.get("exchange")
        else:
            raise TypeError("ETF minute requestable target must be a mapping.")

        ts_code = str(ts_code_value or "").strip().upper()
        if not ts_code:
            raise ValueError("ETF minute requestable target ts_code must not be empty.")
        if ts_code in seen_codes:
            raise ValueError(f"ETF minute requestable target is duplicated: {ts_code}.")
        seen_codes.add(ts_code)
        if isinstance(list_date_value, datetime) or not isinstance(
            list_date_value,
            date,
        ):
            raise TypeError("ETF minute requestable target list_date must be DATE.")
        exchange = str(exchange_value or "").strip().upper()
        suffix = ts_code.rsplit(".", 1)[-1] if "." in ts_code else ""
        if suffix not in ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX:
            raise ValueError("ETF minute requestable target must end with .SH or .SZ.")
        if exchange != suffix:
            raise ValueError(
                "ETF minute requestable target exchange must match its code suffix."
            )
        normalized.append(
            EtfMinsRequestableTarget(
                ts_code=ts_code,
                list_date=list_date_value,
                exchange=exchange,
            )
        )
    if not normalized:
        raise ValueError("ETF minute requestable targets must not be empty.")
    return tuple(sorted(normalized, key=lambda target: target.ts_code))


def expected_etf_mins_targets_for_trade_date(
    targets: Iterable[EtfMinsRequestableTarget | Mapping[str, object]],
    *,
    trade_date: date | str,
) -> tuple[EtfMinsRequestableTarget, ...]:
    normalized_trade_date = date.fromisoformat(
        normalize_etf_mins_trade_date(trade_date)
    )
    return tuple(
        target
        for target in normalize_etf_mins_requestable_targets(targets)
        if target.list_date <= normalized_trade_date
    )


def compute_etf_mins_expected_code_hash(
    targets: Iterable[EtfMinsRequestableTarget | Mapping[str, object]],
    *,
    trade_date: date | str,
) -> str:
    expected_targets = expected_etf_mins_targets_for_trade_date(
        targets,
        trade_date=trade_date,
    )
    return _sha256_json([target.ts_code for target in expected_targets])


def build_etf_mins_prod_coverage_reference(
    *,
    trade_date: date | str,
    basic_reference_fingerprint: str,
    expected_code_count: int,
    expected_code_hash: str,
    frequency_coverages: Iterable[tuple[str, int, int, int]],
    coverage_observed_at: str,
) -> EtfMinsProdCoverageReference:
    normalized_trade_date = normalize_etf_mins_trade_date(trade_date)
    normalized_basic_fingerprint = _normalize_sha256(
        basic_reference_fingerprint,
        field_name="basic_reference_fingerprint",
    )
    normalized_expected_count = _positive_int(
        expected_code_count,
        field_name="expected_code_count",
    )
    normalized_expected_hash = _normalize_sha256(
        expected_code_hash,
        field_name="expected_code_hash",
    )
    normalized_coverages = _normalize_etf_mins_frequency_coverages(
        frequency_coverages,
        expected_code_count=normalized_expected_count,
    )
    normalized_observed_at = _normalize_timezone_datetime(
        coverage_observed_at,
        field_name="coverage_observed_at",
    )
    reference = EtfMinsProdCoverageReference(
        trade_date=normalized_trade_date,
        basic_reference_fingerprint=normalized_basic_fingerprint,
        expected_code_count=normalized_expected_count,
        expected_code_hash=normalized_expected_hash,
        frequency_coverages=normalized_coverages,
        coverage_observed_at=normalized_observed_at,
        coverage_fingerprint=_etf_mins_coverage_fingerprint(
            trade_date=normalized_trade_date,
            basic_reference_fingerprint=normalized_basic_fingerprint,
            expected_code_count=normalized_expected_count,
            expected_code_hash=normalized_expected_hash,
            frequency_coverages=normalized_coverages,
            coverage_observed_at=normalized_observed_at,
        ),
    )
    return reference.validate()


def normalize_etf_mins_source_freq(value: object) -> str:
    normalized = str(value).strip().lower()
    if normalized not in ETF_MINS_SOURCE_FREQS:
        allowed = ", ".join(ETF_MINS_SOURCE_FREQS)
        raise ValueError(
            f"ETF minute source frequency must be one of {allowed}; got {value!r}."
        )
    return normalized


def normalize_etf_mins_asset_freq(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError(  # noqa: TRY004
            "ETF minute asset frequency must not be boolean."
        )
    try:
        normalized = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"ETF minute asset frequency is invalid: {value!r}."
        ) from error
    if normalized not in ETF_MINS_ASSET_FREQS:
        allowed = ", ".join(str(freq) for freq in ETF_MINS_ASSET_FREQS)
        raise ValueError(
            f"ETF minute asset frequency must be one of {allowed}; got {value!r}."
        )
    return normalized


def source_freq_for_etf_mins_asset_freq(value: object) -> str:
    return ETF_MINS_SOURCE_FREQ_BY_ASSET_FREQ[normalize_etf_mins_asset_freq(value)]


def asset_freq_for_etf_mins_source_freq(value: object) -> int:
    return ETF_MINS_ASSET_FREQ_BY_SOURCE_FREQ[normalize_etf_mins_source_freq(value)]


def normalize_etf_mins_path_freq(value: object) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return source_freq_for_etf_mins_asset_freq(value)
    return normalize_etf_mins_source_freq(value)


def normalize_etf_mins_trade_date(value: object) -> str:
    if isinstance(value, datetime):
        raise ValueError(  # noqa: TRY004
            "ETF minute trade_date must not include a time component."
        )
    if isinstance(value, date):
        return value.isoformat()
    normalized = str(value).strip()
    if not _ISO_TRADE_DATE_RE.fullmatch(normalized):
        raise ValueError("ETF minute trade_date must use YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(
            "ETF minute trade_date must be a valid calendar date."
        ) from error
    return parsed.isoformat()


def expected_etf_mins_source_exchange(ts_code: object) -> str:
    normalized_code = str(ts_code).strip().upper()
    suffix = normalized_code.rsplit(".", 1)[-1] if "." in normalized_code else ""
    try:
        return ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX[suffix]
    except KeyError as error:
        raise ValueError(
            f"ETF minute ts_code must end with .SH or .SZ; got {ts_code!r}."
        ) from error


def raw_etf_mins_check_names(value: object) -> tuple[str, ...]:
    asset_freq = normalize_etf_mins_asset_freq(value)
    asset_name = f"raw_etf_mins_{asset_freq}m"
    return (
        f"{asset_name}_file_contract_check",
        f"{asset_name}_request_scope_check",
        f"{asset_name}_bar_domain_check",
    )


def silver_etf_mins_check_names(value: object) -> tuple[str, ...]:
    asset_freq = normalize_etf_mins_asset_freq(value)
    asset_name = f"silver_etf_mins_{asset_freq}m"
    return (
        f"{asset_name}_file_contract_check",
        f"{asset_name}_raw_equivalence_check",
    )


def _normalize_etf_mins_frequency_coverages(
    values: Iterable[tuple[str, int, int, int]],
    *,
    expected_code_count: int,
) -> tuple[tuple[str, int, int, int], ...]:
    normalized = tuple(
        (
            normalize_etf_mins_source_freq(source_freq),
            _non_negative_int(
                expected_count,
                field_name=f"{source_freq}.expected_code_count",
            ),
            _non_negative_int(
                present_count,
                field_name=f"{source_freq}.present_code_count",
            ),
            _non_negative_int(
                missing_count,
                field_name=f"{source_freq}.missing_code_count",
            ),
        )
        for source_freq, expected_count, present_count, missing_count in values
    )
    if tuple(item[0] for item in normalized) != ETF_MINS_SOURCE_FREQS:
        raise ValueError(
            "ETF minute coverage must contain the five canonical frequencies once."
        )
    for source_freq, expected_count, present_count, missing_count in normalized:
        if expected_count != expected_code_count:
            raise ValueError(
                f"ETF minute {source_freq} expected count does not match the reference."
            )
        if present_count > expected_count or missing_count != (
            expected_count - present_count
        ):
            raise ValueError(
                f"ETF minute {source_freq} coverage counts are inconsistent."
            )
    return normalized


def _etf_mins_coverage_fingerprint(
    *,
    trade_date: str,
    basic_reference_fingerprint: str,
    expected_code_count: int,
    expected_code_hash: str,
    frequency_coverages: tuple[tuple[str, int, int, int], ...],
    coverage_observed_at: str,
) -> str:
    return _sha256_json(
        {
            "trade_date": trade_date,
            "basic_reference_fingerprint": basic_reference_fingerprint,
            "expected_code_count": expected_code_count,
            "expected_code_hash": expected_code_hash,
            "frequency_coverages": list(frequency_coverages),
            "coverage_observed_at": coverage_observed_at,
        }
    )


def _normalize_sha256(value: object, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256.")
    return normalized


def _normalize_timezone_datetime(value: object, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"{field_name} must use ISO-8601.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset.")
    return parsed.isoformat()


def _positive_int(value: object, *, field_name: str) -> int:
    normalized = _non_negative_int(value, field_name=field_name)
    if normalized == 0:
        raise ValueError(f"{field_name} must be positive.")
    return normalized


def _non_negative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be a non-negative integer.")
    try:
        normalized = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a non-negative integer.") from error
    if normalized < 0:
        raise ValueError(f"{field_name} must be a non-negative integer.")
    return normalized


def _sha256_json(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ETF_MINS_ASSET_FREQS",
    "ETF_MINS_ASSET_FREQ_BY_SOURCE_FREQ",
    "ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT",
    "ETF_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER",
    "ETF_MINS_BOOTSTRAP_MAX_TARGET_FILES",
    "ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT",
    "ETF_MINS_HISTORICAL_PROTECTION_CUTOFF",
    "ETF_MINS_RAW_APPROVED_POLICY_VERSION",
    "ETF_MINS_RAW_DECISION_BLOCKING_REASON_CODES",
    "ETF_MINS_RAW_DECISION_WARNING_REASON_CODES",
    "ETF_MINS_RAW_OBSERVATION_REASON_CODES",
    "ETF_MINS_SENSOR_WINDOW_LIMIT",
    "ETF_MINS_SOURCE_COLUMNS",
    "ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX",
    "ETF_MINS_SOURCE_FREQS",
    "ETF_MINS_SOURCE_FREQ_BY_ASSET_FREQ",
    "EtfMinsFrequencyCoverageConfig",
    "EtfMinsProdCoverageConfig",
    "EtfMinsProdCoverageReference",
    "EtfMinsRawConfig",
    "EtfMinsRawDecisionPolicy",
    "EtfMinsRequestableTarget",
    "asset_freq_for_etf_mins_source_freq",
    "build_etf_mins_prod_coverage_reference",
    "build_etf_mins_raw_run_config",
    "compute_etf_mins_expected_code_hash",
    "expected_etf_mins_source_exchange",
    "expected_etf_mins_targets_for_trade_date",
    "get_etf_mins_raw_decision_policy",
    "normalize_etf_mins_asset_freq",
    "normalize_etf_mins_path_freq",
    "normalize_etf_mins_requestable_targets",
    "normalize_etf_mins_source_freq",
    "normalize_etf_mins_trade_date",
    "raw_etf_mins_check_names",
    "silver_etf_mins_check_names",
    "source_freq_for_etf_mins_asset_freq",
]
