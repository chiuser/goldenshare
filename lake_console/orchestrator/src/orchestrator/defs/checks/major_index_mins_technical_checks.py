"""Blocking checks for major-index minute technical and state assets."""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    load_stock_mins_expected_trade_dates,
    previous_expected_trade_date,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.major_index_mins_technical_writer import (
    audit_major_index_mins_technical_relation,
    audit_major_index_mins_technical_state_relation,
    major_index_mins_technical_continuity_failure_count,
    major_index_mins_technical_relation_counts,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.paths import (
    gold_major_index_mins_technical_path,
    gold_major_index_mins_technical_state_path,
    silver_major_index_mins_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_HISTORY_START_DATE,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    MAJOR_INDEX_MINS_TECHNICAL_FREQS,
    expected_major_index_mins_technical_codes,
    major_index_mins_technical_asset_key,
    major_index_mins_technical_checks,
    major_index_mins_technical_continuing_codes,
    major_index_mins_technical_state_asset_key,
    major_index_mins_technical_state_checks,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
)

_TECHNICAL_CHECK_KINDS = (
    "contract",
    "source_coverage",
    "partition_frequency",
    "key_integrity",
    "warmup_and_finite",
    "no_future_input",
)
_STATE_CHECK_KINDS = (
    "contract",
    "coverage",
    "last_trade_time",
    "continuity",
)


def _single_partition_key(
    context: dg.AssetCheckExecutionContext,
) -> str | None:
    partition_keys = tuple(sorted(set(context.partition_keys)))
    return partition_keys[0] if len(partition_keys) == 1 else None


def _result(
    *,
    passed: bool,
    scope: CheckScope,
    partition_key: str | None,
    file_path: Path | None,
    checked_row_count: int,
    failed_row_count: int,
    failed_rules: Sequence[str],
    reason_code: str,
    input_file_paths: Sequence[Path] = (),
    missing_file_paths: Sequence[Path] = (),
    failure_samples: Sequence[dict[str, object]] = (),
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=scope,
            file_path=file_path,
            input_file_paths=input_file_paths,
            missing_file_paths=missing_file_paths,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
            extra_metadata={
                "partition_key": partition_key,
                "failed_rule_names": list(failed_rules),
                "reason_code": reason_code,
                "failure_samples": list(failure_samples)[:3],
            },
        ),
    )


def _missing_result(
    *,
    partition_key: str | None,
    target_path: Path | None,
    required_paths: Sequence[Path],
) -> dg.AssetCheckResult | None:
    missing_paths = tuple(path for path in required_paths if not path.exists())
    if not missing_paths:
        return None
    return _result(
        passed=False,
        scope=CheckScope.FILE_EXISTS,
        partition_key=partition_key,
        file_path=target_path,
        checked_row_count=0,
        failed_row_count=len(missing_paths),
        failed_rules=("required_files_exist",),
        reason_code="file_missing",
        input_file_paths=required_paths,
        missing_file_paths=missing_paths,
    )


def _expected_trade_dates(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
) -> tuple[str, ...]:
    calendar_path = silver_trade_calendar_path(lake_root_path)
    if not calendar_path.exists():
        return ()
    with duckdb_resource.connect() as connection:
        return load_stock_mins_expected_trade_dates(
            connection,
            calendar_path,
            min_trade_date=MAJOR_INDEX_MINS_HISTORY_START_DATE,
            evaluated_at=datetime.now(UTC),
            same_day_register_start=None,
        )


def evaluate_major_index_mins_technical_check(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
    freq: int,
    check_kind: str,
) -> dg.AssetCheckResult:
    if check_kind not in _TECHNICAL_CHECK_KINDS:
        raise ValueError(f"unsupported technical check kind: {check_kind}")
    technical_path = gold_major_index_mins_technical_path(
        lake_root_path, freq, partition_key
    )
    source_path = silver_major_index_mins_path(
        lake_root_path, f"{freq}min", partition_key
    )
    missing = _missing_result(
        partition_key=partition_key,
        target_path=technical_path,
        required_paths=(technical_path, source_path),
    )
    if missing is not None:
        return missing

    try:
        with duckdb_resource.connect() as connection:
            technical_relation = read_parquet(
                technical_path, hive_partitioning=False
            )
            source_relation = read_parquet(source_path, hive_partitioning=False)
            expected_codes = expected_major_index_mins_technical_codes(
                partition_key
            )
            source_row_count = int(
                connection.execute(
                    f"SELECT count(*) FROM {source_relation}"
                ).fetchone()[0]
            )
            audit = audit_major_index_mins_technical_relation(
                connection,
                relation_sql=technical_relation,
                expected_codes=expected_codes,
                freq=freq,
                trade_date=partition_key,
                expected_row_count=source_row_count,
            )
            relation_counts = major_index_mins_technical_relation_counts(
                connection=connection,
                target_relation=technical_relation,
                source_relation=source_relation,
                partition_key=partition_key,
                freq=freq,
            )
            if check_kind == "contract":
                failed_rules = tuple(
                    error
                    for error in audit.errors
                    if error in {"schema", "partition_frequency_and_finite"}
                )
                failed_count = sum(
                    int(sample["count"])
                    for sample in audit.failure_samples
                    if sample["rule"] == "invalid"
                ) + int("schema" in failed_rules)
                scope = CheckScope.SCHEMA
            elif check_kind == "warmup_and_finite":
                failed_rules = tuple(
                    error
                    for error in audit.errors
                    if error in {"warmup", "partition_frequency_and_finite"}
                )
                failed_count = sum(
                    int(sample["count"])
                    for sample in audit.failure_samples
                    if sample["rule"] in {"warmup", "invalid"}
                )
                scope = CheckScope.VALUE_SANITY
            else:
                failed_count = relation_counts[check_kind]
                failed_rules = (check_kind,) if failed_count else ()
                scope = {
                    "source_coverage": CheckScope.RECONCILIATION,
                    "partition_frequency": CheckScope.PARTITION_ALIGNMENT,
                    "key_integrity": CheckScope.KEY_UNIQUENESS,
                    "no_future_input": CheckScope.REFERENTIAL_INTEGRITY,
                }[check_kind]
            return _result(
                passed=not failed_rules,
                scope=scope,
                partition_key=partition_key,
                file_path=technical_path,
                checked_row_count=audit.row_count,
                failed_row_count=failed_count,
                failed_rules=failed_rules,
                reason_code=(
                    "ready" if not failed_rules else f"{check_kind}_failed"
                ),
                input_file_paths=(source_path,),
                failure_samples=audit.failure_samples,
            )
    except Exception as error:  # noqa: BLE001 - checks report corrupt facts.
        return _result(
            passed=False,
            scope=CheckScope.SCHEMA,
            partition_key=partition_key,
            file_path=technical_path,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("parquet_readable",),
            reason_code="technical_check_unreadable",
            input_file_paths=(source_path,),
            failure_samples=({"error_type": type(error).__name__},),
        )


def evaluate_major_index_mins_technical_state_check(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
    freq: int,
    check_kind: str,
    expected_trade_dates: Sequence[str] | None = None,
) -> dg.AssetCheckResult:
    if check_kind not in _STATE_CHECK_KINDS:
        raise ValueError(f"unsupported state check kind: {check_kind}")
    technical_path = gold_major_index_mins_technical_path(
        lake_root_path, freq, partition_key
    )
    state_path = gold_major_index_mins_technical_state_path(
        lake_root_path, freq, partition_key
    )
    missing = _missing_result(
        partition_key=partition_key,
        target_path=state_path,
        required_paths=(state_path, technical_path),
    )
    if missing is not None:
        return missing

    try:
        dates = tuple(expected_trade_dates or ()) or _expected_trade_dates(
            lake_root_path=lake_root_path,
            duckdb_resource=duckdb_resource,
        )
        previous_date = previous_expected_trade_date(dates, partition_key)
        continuing_codes = major_index_mins_technical_continuing_codes(
            partition_key
        )
        if (
            check_kind == "continuity"
            and continuing_codes
            and previous_date is None
        ):
            return _result(
                passed=False,
                scope=CheckScope.REFERENTIAL_INTEGRITY,
                partition_key=partition_key,
                file_path=state_path,
                checked_row_count=0,
                failed_row_count=len(continuing_codes),
                failed_rules=("strict_previous_expected_date",),
                reason_code="previous_expected_date_missing",
                input_file_paths=(technical_path,),
                failure_samples=(
                    {
                        "rule": "strict_previous_expected_date",
                        "codes": list(continuing_codes[:3]),
                    },
                ),
            )
        previous_state_path = (
            gold_major_index_mins_technical_state_path(
                lake_root_path, freq, previous_date
            )
            if previous_date is not None and continuing_codes
            else None
        )
        previous_technical_path = (
            gold_major_index_mins_technical_path(
                lake_root_path, freq, previous_date
            )
            if previous_date is not None and continuing_codes
            else None
        )
        if check_kind == "continuity":
            required_previous = tuple(
                path
                for path in (previous_state_path, previous_technical_path)
                if path is not None
            )
            missing_previous = _missing_result(
                partition_key=partition_key,
                target_path=state_path,
                required_paths=required_previous,
            )
            if missing_previous is not None:
                return missing_previous

        with duckdb_resource.connect() as connection:
            state_relation = read_parquet(state_path, hive_partitioning=False)
            technical_relation = read_parquet(
                technical_path, hive_partitioning=False
            )
            audit = audit_major_index_mins_technical_state_relation(
                connection,
                relation_sql=state_relation,
                expected_codes=expected_major_index_mins_technical_codes(
                    partition_key
                ),
                freq=freq,
                trade_date=partition_key,
                technical_relation_sql=technical_relation,
            )
            if check_kind == "continuity":
                failed_count = 0
                if continuing_codes:
                    failed_count = major_index_mins_technical_continuity_failure_count(
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
                failed_rules = ("continuity",) if failed_count else ()
                scope = CheckScope.REFERENTIAL_INTEGRITY
            else:
                relevant_errors = {
                    "contract": {"schema", "contract", "key_integrity"},
                    "coverage": {"coverage"},
                    "last_trade_time": {"last_trade_time"},
                }[check_kind]
                failed_rules = tuple(
                    error for error in audit.errors if error in relevant_errors
                )
                relevant_samples = {
                    "contract": {"invalid", "duplicate"},
                    "coverage": {"scope"},
                    "last_trade_time": {"last_trade_time"},
                }[check_kind]
                failed_count = sum(
                    int(sample["count"])
                    for sample in audit.failure_samples
                    if sample["rule"] in relevant_samples
                ) + int("schema" in failed_rules)
                scope = {
                    "contract": CheckScope.SCHEMA,
                    "coverage": CheckScope.RECONCILIATION,
                    "last_trade_time": CheckScope.PARTITION_ALIGNMENT,
                }[check_kind]
            input_paths = [technical_path]
            input_paths.extend(
                path
                for path in (previous_state_path, previous_technical_path)
                if check_kind == "continuity" and path is not None
            )
            return _result(
                passed=not failed_rules,
                scope=scope,
                partition_key=partition_key,
                file_path=state_path,
                checked_row_count=audit.row_count,
                failed_row_count=failed_count,
                failed_rules=failed_rules,
                reason_code=(
                    "ready" if not failed_rules else f"{check_kind}_failed"
                ),
                input_file_paths=tuple(input_paths),
                failure_samples=audit.failure_samples,
            )
    except Exception as error:  # noqa: BLE001 - checks report corrupt facts.
        return _result(
            passed=False,
            scope=CheckScope.SCHEMA,
            partition_key=partition_key,
            file_path=state_path,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("parquet_readable",),
            reason_code="state_check_unreadable",
            input_file_paths=(technical_path,),
            failure_samples=({"error_type": type(error).__name__},),
        )


def _build_technical_check(
    *,
    freq: int,
    name: str,
    check_kind: str,
) -> dg.AssetsDefinition:
    asset_key = major_index_mins_technical_asset_key(freq)

    @dg.asset_check(
        asset=dg.AssetKey(asset_key),
        name=name,
        partitions_def=cn_major_index_mins_trade_days,
        blocking=True,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        partition_key = _single_partition_key(context)
        if partition_key is None:
            return _result(
                passed=False,
                scope=CheckScope.PARTITION_ALIGNMENT,
                partition_key=None,
                file_path=None,
                checked_row_count=0,
                failed_row_count=0,
                failed_rules=("single_partition_execution",),
                reason_code="multiple_partition_execution",
            )
        return evaluate_major_index_mins_technical_check(
            lake_root_path=lake_root.root(),
            duckdb_resource=duckdb,
            partition_key=partition_key,
            freq=freq,
            check_kind=check_kind,
        )

    return check


def _build_state_check(
    *,
    freq: int,
    name: str,
    check_kind: str,
) -> dg.AssetsDefinition:
    state_key = major_index_mins_technical_state_asset_key(freq)
    technical_key = major_index_mins_technical_asset_key(freq)

    @dg.asset_check(
        asset=dg.AssetKey(state_key),
        additional_deps=[dg.AssetKey(technical_key)],
        name=name,
        partitions_def=cn_major_index_mins_trade_days,
        blocking=True,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        partition_key = _single_partition_key(context)
        if partition_key is None:
            return _result(
                passed=False,
                scope=CheckScope.PARTITION_ALIGNMENT,
                partition_key=None,
                file_path=None,
                checked_row_count=0,
                failed_row_count=0,
                failed_rules=("single_partition_execution",),
                reason_code="multiple_partition_execution",
            )
        return evaluate_major_index_mins_technical_state_check(
            lake_root_path=lake_root.root(),
            duckdb_resource=duckdb,
            partition_key=partition_key,
            freq=freq,
            check_kind=check_kind,
        )

    return check


GOLD_MAJOR_INDEX_MINS_TECHNICAL_CHECK_DEFINITIONS = tuple(
    _build_technical_check(freq=freq, name=name, check_kind=check_kind)
    for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
    for name, check_kind in zip(
        major_index_mins_technical_checks(freq),
        _TECHNICAL_CHECK_KINDS,
        strict=True,
    )
)

GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_CHECK_DEFINITIONS = tuple(
    _build_state_check(freq=freq, name=name, check_kind=check_kind)
    for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
    for name, check_kind in zip(
        major_index_mins_technical_state_checks(freq),
        _STATE_CHECK_KINDS,
        strict=True,
    )
)

__all__ = [
    "GOLD_MAJOR_INDEX_MINS_TECHNICAL_CHECK_DEFINITIONS",
    "GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_CHECK_DEFINITIONS",
    "evaluate_major_index_mins_technical_check",
    "evaluate_major_index_mins_technical_state_check",
]
