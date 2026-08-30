"""Prod code-coverage readiness for the ETF minute Raw chain."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from orchestrator.defs.prod_db.etf_mins import (
    ProdEtfMinsCodeCoverageProbe,
    probe_prod_etf_mins_code_coverage,
)
from orchestrator.defs.resources import ProdPostgresResource
from orchestrator.defs.run_contracts.etf_basic import (
    EtfBasicSilverSnapshotReference,
    compute_etf_requestable_target_hash,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_SOURCE_FREQS,
    EtfMinsProdCoverageReference,
    EtfMinsRequestableTarget,
    build_etf_mins_prod_coverage_reference,
    compute_etf_mins_expected_code_hash,
    expected_etf_mins_targets_for_trade_date,
    normalize_etf_mins_requestable_targets,
    normalize_etf_mins_trade_date,
)


@dataclass(frozen=True, slots=True)
class EtfMinsProdSourceReadiness:
    ready: bool
    reason_code: str
    coverage_status: ProdEtfMinsCodeCoverageProbe | None
    coverage_reference: EtfMinsProdCoverageReference | None


def etf_mins_prod_source_ready_for_trade_date(
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    basic_reference: EtfBasicSilverSnapshotReference,
    requestable_targets: Iterable[
        EtfMinsRequestableTarget | Mapping[str, object]
    ],
    observed_at: datetime,
) -> EtfMinsProdSourceReadiness:
    """Run the one five-frequency coverage query used before a daily Raw run."""

    try:
        normalized_targets = _validate_targets_match_basic_reference(
            basic_reference=basic_reference,
            requestable_targets=requestable_targets,
        )
        normalized_trade_date = normalize_etf_mins_trade_date(trade_date)
        expected_targets = expected_etf_mins_targets_for_trade_date(
            normalized_targets,
            trade_date=normalized_trade_date,
        )
        if not expected_targets:
            raise ValueError("ETF minute expected target set must not be empty.")
    except ValueError:
        return EtfMinsProdSourceReadiness(
            ready=False,
            reason_code="etf_basic_reference_changed",
            coverage_status=None,
            coverage_reference=None,
        )

    coverage_status = probe_prod_etf_mins_code_coverage(
        prod_postgres=prod_postgres,
        trade_dates=(normalized_trade_date,),
        requestable_targets=normalized_targets,
    )
    if not coverage_status.ready:
        return EtfMinsProdSourceReadiness(
            ready=False,
            reason_code=coverage_status.reason_code,
            coverage_status=coverage_status,
            coverage_reference=None,
        )

    try:
        reference = _build_reference_from_ready_coverage(
            trade_date=normalized_trade_date,
            basic_reference=basic_reference,
            requestable_targets=normalized_targets,
            coverage_status=coverage_status,
            observed_at=observed_at,
        )
    except ValueError:
        return EtfMinsProdSourceReadiness(
            ready=False,
            reason_code="prod_etf_mins_code_coverage_inconsistent",
            coverage_status=coverage_status,
            coverage_reference=None,
        )
    return EtfMinsProdSourceReadiness(
        ready=True,
        reason_code="prod_etf_mins_source_ready",
        coverage_status=coverage_status,
        coverage_reference=reference,
    )


def validate_etf_mins_prod_coverage_reference(
    *,
    partition_key: str,
    basic_reference: EtfBasicSilverSnapshotReference,
    requestable_targets: Iterable[
        EtfMinsRequestableTarget | Mapping[str, object]
    ],
    coverage_reference: EtfMinsProdCoverageReference,
) -> EtfMinsProdCoverageReference:
    """Revalidate a carried coverage fact without querying Prod again."""

    normalized_trade_date = normalize_etf_mins_trade_date(partition_key)
    normalized_targets = _validate_targets_match_basic_reference(
        basic_reference=basic_reference,
        requestable_targets=requestable_targets,
    )
    coverage_reference.validate()
    if coverage_reference.trade_date != normalized_trade_date:
        raise ValueError("ETF minute coverage reference does not match the partition.")
    if (
        coverage_reference.basic_reference_fingerprint
        != basic_reference.reference_fingerprint
    ):
        raise ValueError("ETF minute coverage reference uses a different Basic snapshot.")
    expected_targets = expected_etf_mins_targets_for_trade_date(
        normalized_targets,
        trade_date=normalized_trade_date,
    )
    if coverage_reference.expected_code_count != len(expected_targets):
        raise ValueError("ETF minute coverage expected count has changed.")
    expected_code_hash = compute_etf_mins_expected_code_hash(
        normalized_targets,
        trade_date=normalized_trade_date,
    )
    if coverage_reference.expected_code_hash != expected_code_hash:
        raise ValueError("ETF minute coverage expected code hash has changed.")
    return coverage_reference


def _validate_targets_match_basic_reference(
    *,
    basic_reference: EtfBasicSilverSnapshotReference,
    requestable_targets: Iterable[
        EtfMinsRequestableTarget | Mapping[str, object]
    ],
) -> tuple[EtfMinsRequestableTarget, ...]:
    basic_reference.validate_contract()
    normalized_targets = normalize_etf_mins_requestable_targets(requestable_targets)
    target_rows = tuple(
        {
            "ts_code": target.ts_code,
            "list_date": target.list_date,
            "exchange": target.exchange,
        }
        for target in normalized_targets
    )
    if (
        len(normalized_targets) != basic_reference.requestable_code_count
        or compute_etf_requestable_target_hash(target_rows)
        != basic_reference.requestable_code_hash
    ):
        raise ValueError("ETF minute targets do not match the frozen Basic reference.")
    return normalized_targets


def _build_reference_from_ready_coverage(
    *,
    trade_date: str,
    basic_reference: EtfBasicSilverSnapshotReference,
    requestable_targets: tuple[EtfMinsRequestableTarget, ...],
    coverage_status: ProdEtfMinsCodeCoverageProbe,
    observed_at: datetime,
) -> EtfMinsProdCoverageReference:
    coverage_by_key = coverage_status.coverage_by_key()
    expected_targets = expected_etf_mins_targets_for_trade_date(
        requestable_targets,
        trade_date=trade_date,
    )
    frequency_coverages = tuple(
        (
            source_freq,
            coverage_by_key[(trade_date, source_freq)].expected_code_count,
            coverage_by_key[(trade_date, source_freq)].present_code_count,
            coverage_by_key[(trade_date, source_freq)].missing_code_count,
        )
        for source_freq in ETF_MINS_SOURCE_FREQS
    )
    if any(item[1] != len(expected_targets) for item in frequency_coverages):
        raise ValueError("ETF minute coverage expected counts do not match Basic.")
    return build_etf_mins_prod_coverage_reference(
        trade_date=trade_date,
        basic_reference_fingerprint=basic_reference.reference_fingerprint,
        expected_code_count=len(expected_targets),
        expected_code_hash=compute_etf_mins_expected_code_hash(
            requestable_targets,
            trade_date=trade_date,
        ),
        frequency_coverages=frequency_coverages,
        coverage_observed_at=observed_at.isoformat(),
    )


__all__ = [
    "EtfMinsProdSourceReadiness",
    "etf_mins_prod_source_ready_for_trade_date",
    "validate_etf_mins_prod_coverage_reference",
]
