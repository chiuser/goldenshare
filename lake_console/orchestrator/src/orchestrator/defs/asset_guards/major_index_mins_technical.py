"""Bounded physical readiness for major-index minute technical assets."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    previous_expected_trade_date,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.major_index_mins_technical_writer import (
    audit_major_index_mins_technical_relation,
    audit_major_index_mins_technical_state_relation,
    major_index_mins_technical_continuity_failure_count,
    major_index_mins_technical_relation_counts,
)
from orchestrator.defs.paths import (
    gold_major_index_mins_path,
    gold_major_index_mins_technical_path,
    gold_major_index_mins_technical_state_path,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    normalize_major_index_mins_trade_date,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    MAJOR_INDEX_MINS_TECHNICAL_FREQS,
    expected_major_index_mins_technical_codes,
    major_index_mins_technical_checks,
    major_index_mins_technical_continuing_codes,
    major_index_mins_technical_state_checks,
)


@dataclass(frozen=True, slots=True)
class MajorIndexMinsTechnicalReadiness:
    trade_date: str
    ready: bool
    expected_file_count: int
    materialized_file_count: int
    checks_passed: bool
    reason_code: str
    reason: str
    scanned_file_count: int = 0
    failed_check_names: tuple[str, ...] = ()
    missing_file_paths: tuple[str, ...] = ()

    @property
    def all_missing(self) -> bool:
        return self.materialized_file_count == 0

    @property
    def partial(self) -> bool:
        return 0 < self.materialized_file_count < self.expected_file_count


def _normalize_expected_dates(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        sorted({normalize_major_index_mins_trade_date(value) for value in values})
    )


def _readiness(
    *,
    trade_date: str,
    ready: bool,
    expected_file_count: int,
    materialized_file_count: int,
    checks_passed: bool,
    reason_code: str,
    reason: str,
    scanned_paths: set[Path] | None = None,
    failed_check_names: Sequence[str] = (),
    missing_paths: Sequence[Path] = (),
) -> MajorIndexMinsTechnicalReadiness:
    if ready != (materialized_file_count == expected_file_count and checks_passed):
        raise ValueError(
            "major-index minute technical readiness must be ready only when "
            "all expected files exist and checks pass"
        )
    return MajorIndexMinsTechnicalReadiness(
        trade_date=trade_date,
        ready=ready,
        expected_file_count=expected_file_count,
        materialized_file_count=materialized_file_count,
        checks_passed=checks_passed,
        reason_code=reason_code,
        reason=reason,
        scanned_file_count=len(scanned_paths or ()),
        failed_check_names=tuple(dict.fromkeys(failed_check_names)),
        missing_file_paths=tuple(str(path) for path in missing_paths[:20]),
    )


def _target_paths(
    lake_root: Path,
    trade_date: str,
) -> tuple[Path, ...]:
    return tuple(
        path
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
        for path in (
            gold_major_index_mins_technical_path(lake_root, freq, trade_date),
            gold_major_index_mins_technical_state_path(lake_root, freq, trade_date),
        )
    )


def _state_paths(
    lake_root: Path,
    trade_date: str,
) -> tuple[Path, ...]:
    return tuple(
        gold_major_index_mins_technical_state_path(lake_root, freq, trade_date)
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
    )


def _validate_state_frequency(
    *,
    connection: duckdb.DuckDBPyConnection,
    lake_root: Path,
    trade_date: str,
    expected_trade_dates: tuple[str, ...],
    freq: int,
    scanned_paths: set[Path],
) -> tuple[tuple[str, ...], tuple[Path, ...]]:
    technical_path = gold_major_index_mins_technical_path(lake_root, freq, trade_date)
    state_path = gold_major_index_mins_technical_state_path(lake_root, freq, trade_date)
    required_paths = [technical_path, state_path]
    previous_date = previous_expected_trade_date(expected_trade_dates, trade_date)
    continuing_codes = major_index_mins_technical_continuing_codes(trade_date)
    previous_technical_path = None
    previous_state_path = None
    if continuing_codes:
        if previous_date is None:
            return major_index_mins_technical_state_checks(freq), ()
        previous_technical_path = gold_major_index_mins_technical_path(
            lake_root, freq, previous_date
        )
        previous_state_path = gold_major_index_mins_technical_state_path(
            lake_root, freq, previous_date
        )
        required_paths.extend((previous_technical_path, previous_state_path))
    missing_paths = tuple(path for path in required_paths if not path.exists())
    if missing_paths:
        return major_index_mins_technical_state_checks(freq), missing_paths

    scanned_paths.update(required_paths)
    technical_relation = read_parquet(technical_path, hive_partitioning=False)
    state_relation = read_parquet(state_path, hive_partitioning=False)
    audit = audit_major_index_mins_technical_state_relation(
        connection,
        relation_sql=state_relation,
        expected_codes=expected_major_index_mins_technical_codes(trade_date),
        freq=freq,
        trade_date=trade_date,
        technical_relation_sql=technical_relation,
    )
    failed = bool(audit.errors)
    if continuing_codes:
        failed = failed or bool(
            major_index_mins_technical_continuity_failure_count(
                connection=connection,
                current_technical_relation=technical_relation,
                previous_technical_relation=read_parquet(
                    previous_technical_path,
                    hive_partitioning=False,
                ),
                previous_state_relation=read_parquet(
                    previous_state_path,
                    hive_partitioning=False,
                ),
                continuing_codes=continuing_codes,
                freq=freq,
                previous_trade_date=previous_date,
            )
        )
    return (
        major_index_mins_technical_state_checks(freq) if failed else (),
        (),
    )


def major_index_mins_technical_target_readiness(
    *,
    connection: duckdb.DuckDBPyConnection,
    lake_root: Path,
    trade_date: str,
    expected_trade_dates: Sequence[str],
) -> MajorIndexMinsTechnicalReadiness:
    """Validate all 14 target files, or classify an absent/partial target."""

    normalized_date = normalize_major_index_mins_trade_date(trade_date)
    normalized_dates = _normalize_expected_dates(expected_trade_dates)
    target_paths = _target_paths(lake_root, normalized_date)
    existing_paths = tuple(path for path in target_paths if path.exists())
    if not existing_paths:
        return _readiness(
            trade_date=normalized_date,
            ready=False,
            expected_file_count=len(target_paths),
            materialized_file_count=0,
            checks_passed=False,
            reason_code="target_absent",
            reason="major-index minute technical target is absent",
        )
    if len(existing_paths) != len(target_paths):
        missing_paths = tuple(path for path in target_paths if not path.exists())
        return _readiness(
            trade_date=normalized_date,
            ready=False,
            expected_file_count=len(target_paths),
            materialized_file_count=len(existing_paths),
            checks_passed=False,
            reason_code="target_partial",
            reason="major-index minute technical target is partially materialized",
            missing_paths=missing_paths,
        )

    failed_checks: list[str] = []
    missing_dependencies: list[Path] = []
    scanned_paths: set[Path] = set()
    try:
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
            technical_path = gold_major_index_mins_technical_path(
                lake_root, freq, normalized_date
            )
            source_path = gold_major_index_mins_path(lake_root, freq, normalized_date)
            if not source_path.exists():
                failed_checks.extend(major_index_mins_technical_checks(freq))
                missing_dependencies.append(source_path)
                continue
            scanned_paths.update((technical_path, source_path))
            technical_relation = read_parquet(technical_path, hive_partitioning=False)
            source_relation = read_parquet(source_path, hive_partitioning=False)
            source_row_count = int(
                connection.execute(
                    f"SELECT count(*) FROM {source_relation}"
                ).fetchone()[0]
            )
            audit = audit_major_index_mins_technical_relation(
                connection,
                relation_sql=technical_relation,
                expected_codes=expected_major_index_mins_technical_codes(
                    normalized_date
                ),
                freq=freq,
                trade_date=normalized_date,
                expected_row_count=source_row_count,
            )
            relation_counts = major_index_mins_technical_relation_counts(
                connection=connection,
                target_relation=technical_relation,
                source_relation=source_relation,
                partition_key=normalized_date,
                freq=freq,
            )
            if audit.errors or any(relation_counts.values()):
                failed_checks.extend(major_index_mins_technical_checks(freq))

            state_failures, state_missing = _validate_state_frequency(
                connection=connection,
                lake_root=lake_root,
                trade_date=normalized_date,
                expected_trade_dates=normalized_dates,
                freq=freq,
                scanned_paths=scanned_paths,
            )
            failed_checks.extend(state_failures)
            missing_dependencies.extend(state_missing)
    except Exception:  # noqa: BLE001 - readiness must fail closed on corrupt facts.
        failed_checks = [
            check_name
            for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
            for check_name in (
                *major_index_mins_technical_checks(freq),
                *major_index_mins_technical_state_checks(freq),
            )
        ]

    checks_passed = not failed_checks and not missing_dependencies
    return _readiness(
        trade_date=normalized_date,
        ready=checks_passed,
        expected_file_count=len(target_paths),
        materialized_file_count=len(target_paths),
        checks_passed=checks_passed,
        reason_code="ready" if checks_passed else "target_invalid",
        reason=(
            "major-index minute technical target is ready"
            if checks_passed
            else "major-index minute technical target failed blocking semantics"
        ),
        scanned_paths=scanned_paths,
        failed_check_names=failed_checks,
        missing_paths=missing_dependencies,
    )


def major_index_mins_technical_state_readiness(
    *,
    connection: duckdb.DuckDBPyConnection,
    lake_root: Path,
    trade_date: str,
    expected_trade_dates: Sequence[str],
) -> MajorIndexMinsTechnicalReadiness:
    """Validate the seven recursive state assets for one expected date."""

    normalized_date = normalize_major_index_mins_trade_date(trade_date)
    normalized_dates = _normalize_expected_dates(expected_trade_dates)
    state_paths = _state_paths(lake_root, normalized_date)
    existing_paths = tuple(path for path in state_paths if path.exists())
    if not existing_paths:
        return _readiness(
            trade_date=normalized_date,
            ready=False,
            expected_file_count=len(state_paths),
            materialized_file_count=0,
            checks_passed=False,
            reason_code="state_absent",
            reason="major-index minute technical state is absent",
        )
    if len(existing_paths) != len(state_paths):
        missing_paths = tuple(path for path in state_paths if not path.exists())
        return _readiness(
            trade_date=normalized_date,
            ready=False,
            expected_file_count=len(state_paths),
            materialized_file_count=len(existing_paths),
            checks_passed=False,
            reason_code="state_partial",
            reason="major-index minute technical state is partially materialized",
            missing_paths=missing_paths,
        )

    failed_checks: list[str] = []
    missing_dependencies: list[Path] = []
    scanned_paths: set[Path] = set()
    try:
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
            state_failures, state_missing = _validate_state_frequency(
                connection=connection,
                lake_root=lake_root,
                trade_date=normalized_date,
                expected_trade_dates=normalized_dates,
                freq=freq,
                scanned_paths=scanned_paths,
            )
            failed_checks.extend(state_failures)
            missing_dependencies.extend(state_missing)
    except Exception:  # noqa: BLE001 - readiness must fail closed on corrupt facts.
        failed_checks = [
            check_name
            for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
            for check_name in major_index_mins_technical_state_checks(freq)
        ]

    checks_passed = not failed_checks and not missing_dependencies
    return _readiness(
        trade_date=normalized_date,
        ready=checks_passed,
        expected_file_count=len(state_paths),
        materialized_file_count=len(state_paths),
        checks_passed=checks_passed,
        reason_code="ready" if checks_passed else "state_invalid",
        reason=(
            "major-index minute technical state is ready"
            if checks_passed
            else "major-index minute technical state failed blocking semantics"
        ),
        scanned_paths=scanned_paths,
        failed_check_names=failed_checks,
        missing_paths=missing_dependencies,
    )


__all__ = [
    "MajorIndexMinsTechnicalReadiness",
    "major_index_mins_technical_state_readiness",
    "major_index_mins_technical_target_readiness",
]
