"""Single partition-attributable core checks for index minute assets."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.index_mins_raw import (
    raw_index_mins_1m,
    raw_index_mins_5m,
    raw_index_mins_15m,
    raw_index_mins_30m,
    raw_index_mins_60m,
)
from orchestrator.defs.assets.index_mins_silver import (
    _assert_schema,
    _derived_diagnostics,
    _native_source_sql,
    _validate_relation,
)
from orchestrator.defs.assets.index_mins_silver_defs import (
    silver_index_mins_1m,
    silver_index_mins_5m,
    silver_index_mins_15m,
    silver_index_mins_30m,
    silver_index_mins_60m,
    silver_index_mins_90m,
    silver_index_mins_120m,
)
from orchestrator.defs.duckdb_sql import describe_parquet_query, read_parquet
from orchestrator.defs.partitions import cn_a_index_mins_trade_days
from orchestrator.defs.paths import raw_index_mins_path, silver_index_mins_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_MINS_SCHEMA,
    SILVER_INDEX_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


_CODE_PATTERN = r"^[0-9A-Z]{1,12}\.[A-Z0-9]{2,8}$"


def _partition_key(context: dg.AssetCheckExecutionContext) -> str | None:
    partition_keys = tuple(sorted(set(context.partition_keys)))
    return partition_keys[0] if len(partition_keys) == 1 else None


def _metadata_result(
    *,
    passed: bool,
    partition_key: str | None,
    file_path: Path | None,
    checked_row_count: int,
    failed_row_count: int,
    failed_rules: Sequence[str],
    reason_code: str,
    failure_samples: Sequence[dict[str, object]] = (),
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            file_path=file_path,
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


def _sample_rows(connection: Any, relation: str, condition: str) -> list[dict[str, object]]:
    rows = connection.execute(
        f"SELECT * FROM {relation} WHERE {condition} LIMIT 3"
    ).fetchall()
    columns = [str(row[0]) for row in connection.execute(
        f"DESCRIBE SELECT * FROM {relation}"
    ).fetchall()]
    return [
        {
            column: value.isoformat() if hasattr(value, "isoformat") else value
            for column, value in zip(columns, row, strict=True)
        }
        for row in rows
    ]


def _schema_matches(connection: Any, path: Path, schema: Sequence[object]) -> bool:
    expected = tuple((str(column.name), str(column.type).upper()) for column in schema)
    observed = tuple(
        (str(row[0]), str(row[1]).upper().split("(", 1)[0])
        for row in connection.execute(describe_parquet_query(path)).fetchall()
    )
    return observed == expected


def _raw_invalid_predicate(*, partition_key: str, source_freq: str) -> str:
    return f"""
        ts_code IS NULL
        OR NOT regexp_matches(upper(trim(CAST(ts_code AS VARCHAR))), '{_CODE_PATTERN}')
        OR freq IS NULL OR CAST(freq AS VARCHAR) <> '{source_freq}'
        OR trade_time IS NULL OR CAST(trade_time AS DATE) <> CAST('{partition_key}' AS DATE)
        OR open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
        OR NOT isfinite(CAST(open AS DOUBLE))
        OR NOT isfinite(CAST(close AS DOUBLE))
        OR NOT isfinite(CAST(high AS DOUBLE))
        OR NOT isfinite(CAST(low AS DOUBLE))
        OR open <= 0 OR close <= 0 OR high <= 0 OR low <= 0
        OR high < low OR open < low OR open > high
        OR close < low OR close > high
        OR vol IS NULL OR amount IS NULL
        OR NOT isfinite(CAST(vol AS DOUBLE)) OR NOT isfinite(CAST(amount AS DOUBLE))
        OR vol < 0 OR amount < 0
        OR (vwap IS NOT NULL AND (
            NOT isfinite(CAST(vwap AS DOUBLE)) OR CAST(vwap AS DOUBLE) < 0
        ))
    """


def _raw_core_result(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb_resource: DuckDBResource,
    source_freq: str,
) -> dg.AssetCheckResult:
    partition_key = _partition_key(context)
    if partition_key is None:
        return _metadata_result(
            passed=False,
            partition_key=None,
            file_path=None,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("single_partition_execution",),
            reason_code="multiple_partition_execution",
        )
    path = raw_index_mins_path(lake_root.root(), source_freq, partition_key)
    if not path.exists():
        return _metadata_result(
            passed=False,
            partition_key=partition_key,
            file_path=path,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("file_exists",),
            reason_code="file_missing",
        )
    try:
        with duckdb_resource.connect() as connection:
            relation = read_parquet(path, hive_partitioning=False)
            schema_ok = _schema_matches(connection, path, RAW_INDEX_MINS_SCHEMA)
            row_count = int(connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0])
            invalid_predicate = _raw_invalid_predicate(
                partition_key=partition_key,
                source_freq=source_freq,
            )
            invalid_count = int(
                connection.execute(
                    f"SELECT count(*) FROM {relation} WHERE {invalid_predicate}"
                ).fetchone()[0]
            )
            duplicate_count = int(
                connection.execute(
                    f"SELECT count(*) - count(DISTINCT (ts_code, freq, trade_time)) FROM {relation}"
                ).fetchone()[0]
            )
            failed_rules: list[str] = []
            if not schema_ok:
                failed_rules.append("schema_matches_contract")
            if row_count <= 0:
                failed_rules.append("row_count_positive")
            if invalid_count:
                failed_rules.append("identity_partition_value_domain")
            if duplicate_count:
                failed_rules.append("business_key_unique")
            samples = _sample_rows(connection, relation, invalid_predicate) if invalid_count else []
            return _metadata_result(
                passed=not failed_rules,
                partition_key=partition_key,
                file_path=path,
                checked_row_count=row_count,
                failed_row_count=invalid_count + duplicate_count,
                failed_rules=failed_rules,
                reason_code="ready" if not failed_rules else "raw_core_check_failed",
                failure_samples=samples,
            )
    except Exception as error:  # noqa: BLE001 - check must report corrupt files.
        return _metadata_result(
            passed=False,
            partition_key=partition_key,
            file_path=path,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("parquet_readable",),
            reason_code="parquet_unreadable",
            failure_samples=({"error_type": type(error).__name__},),
        )


def _silver_core_result(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb_resource: DuckDBResource,
    silver_freq: int,
) -> dg.AssetCheckResult:
    partition_key = _partition_key(context)
    if partition_key is None:
        return _metadata_result(
            passed=False,
            partition_key=None,
            file_path=None,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("single_partition_execution",),
            reason_code="multiple_partition_execution",
        )
    target_path = silver_index_mins_path(lake_root.root(), silver_freq, partition_key)
    if not target_path.exists():
        return _metadata_result(
            passed=False,
            partition_key=partition_key,
            file_path=target_path,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("file_exists",),
            reason_code="file_missing",
        )

    derived = silver_freq >= 90
    source_freq = "30min" if silver_freq == 90 else "60min" if silver_freq == 120 else f"{silver_freq}min"
    source_path = (
        silver_index_mins_path(lake_root.root(), source_freq, partition_key)
        if derived
        else raw_index_mins_path(lake_root.root(), source_freq, partition_key)
    )
    try:
        with duckdb_resource.connect() as connection:
            _assert_schema(connection, target_path, SILVER_INDEX_MINS_SCHEMA, label="index_mins Silver")
            target_relation = read_parquet(target_path, hive_partitioning=False)
            expected_row_count: int | None = None
            failed_rules: list[str] = []
            failed_row_count = 0
            if not source_path.exists():
                failed_rules.append("source_file_exists")
            else:
                source_schema = SILVER_INDEX_MINS_SCHEMA if derived else RAW_INDEX_MINS_SCHEMA
                _assert_schema(connection, source_path, source_schema, label="index_mins source")
                source_relation = read_parquet(source_path, hive_partitioning=False)
                source_sql = _native_source_sql(source_relation)
                source_validation = _validate_relation(
                    connection,
                    relation_sql=source_sql,
                    expected_freq=source_freq,
                    partition_key=partition_key,
                    require_null_vwap=False,
                )
                if source_validation.invalid_row_count or source_validation.duplicate_key_count:
                    failed_rules.append("source_contract")
                    failed_row_count += source_validation.invalid_row_count + source_validation.duplicate_key_count
                if not derived:
                    expected_row_count = source_validation.row_count
                else:
                    diagnostics = _derived_diagnostics(
                        connection,
                        source_sql=source_sql,
                        silver_freq=f"{silver_freq}min",
                        partition_key=partition_key,
                    )
                    expected_row_count = diagnostics["generated_window_count"]
                    if diagnostics["incomplete_window_count"]:
                        failed_rules.append("derived_window_complete")
                        failed_row_count += diagnostics["incomplete_window_count"]
                    if diagnostics["exchange_mismatch_window_count"]:
                        failed_rules.append("derived_exchange_unique")
                        failed_row_count += diagnostics["exchange_mismatch_window_count"]
                    if diagnostics["generated_window_count"] <= 0:
                        failed_rules.append("derived_window_generated")
            target_validation = _validate_relation(
                connection,
                relation_sql=target_relation,
                expected_freq=f"{silver_freq}min",
                partition_key=partition_key,
                require_null_vwap=derived,
            )
            row_count = target_validation.row_count
            if expected_row_count is not None and row_count != expected_row_count:
                failed_rules.append("output_row_count_matches_source_or_windows")
            if target_validation.invalid_row_count:
                failed_rules.append("output_value_domain")
                failed_row_count += target_validation.invalid_row_count
            if target_validation.duplicate_key_count:
                failed_rules.append("output_business_key_unique")
                failed_row_count += target_validation.duplicate_key_count
            if derived and target_validation.non_null_vwap_count:
                failed_rules.append("derived_vwap_is_null")
                failed_row_count += target_validation.non_null_vwap_count
            return _metadata_result(
                passed=not failed_rules,
                partition_key=partition_key,
                file_path=target_path,
                checked_row_count=row_count,
                failed_row_count=failed_row_count,
                failed_rules=failed_rules,
                reason_code="ready" if not failed_rules else "silver_core_check_failed",
            )
    except Exception as error:  # noqa: BLE001 - check must report corrupt files.
        return _metadata_result(
            passed=False,
            partition_key=partition_key,
            file_path=target_path,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("parquet_schema_and_contract",),
            reason_code="silver_contract_unreadable",
            failure_samples=({"error_type": type(error).__name__},),
        )


def _build_raw_check(*, asset: object, name: str, source_freq: str):
    @dg.asset_check(
        asset=asset,
        name=name,
        partitions_def=cn_a_index_mins_trade_days,
        blocking=True,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return _raw_core_result(
            context=context,
            lake_root=lake_root,
            duckdb_resource=duckdb,
            source_freq=source_freq,
        )

    return check


def _build_silver_check(*, asset: object, name: str, silver_freq: int, source_deps: Sequence[object]):
    @dg.asset_check(
        asset=asset,
        additional_deps=list(source_deps),
        name=name,
        partitions_def=cn_a_index_mins_trade_days,
        blocking=True,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return _silver_core_result(
            context=context,
            lake_root=lake_root,
            duckdb_resource=duckdb,
            silver_freq=silver_freq,
        )

    return check


raw_index_mins_1m_core_check = _build_raw_check(
    asset=raw_index_mins_1m, name="raw_index_mins_1m_core_check", source_freq="1min"
)
raw_index_mins_5m_core_check = _build_raw_check(
    asset=raw_index_mins_5m, name="raw_index_mins_5m_core_check", source_freq="5min"
)
raw_index_mins_15m_core_check = _build_raw_check(
    asset=raw_index_mins_15m, name="raw_index_mins_15m_core_check", source_freq="15min"
)
raw_index_mins_30m_core_check = _build_raw_check(
    asset=raw_index_mins_30m, name="raw_index_mins_30m_core_check", source_freq="30min"
)
raw_index_mins_60m_core_check = _build_raw_check(
    asset=raw_index_mins_60m, name="raw_index_mins_60m_core_check", source_freq="60min"
)

silver_index_mins_1m_core_check = _build_silver_check(
    asset=silver_index_mins_1m,
    name="silver_index_mins_1m_core_check",
    silver_freq=1,
    source_deps=(raw_index_mins_1m,),
)
silver_index_mins_5m_core_check = _build_silver_check(
    asset=silver_index_mins_5m,
    name="silver_index_mins_5m_core_check",
    silver_freq=5,
    source_deps=(raw_index_mins_5m,),
)
silver_index_mins_15m_core_check = _build_silver_check(
    asset=silver_index_mins_15m,
    name="silver_index_mins_15m_core_check",
    silver_freq=15,
    source_deps=(raw_index_mins_15m,),
)
silver_index_mins_30m_core_check = _build_silver_check(
    asset=silver_index_mins_30m,
    name="silver_index_mins_30m_core_check",
    silver_freq=30,
    source_deps=(raw_index_mins_30m,),
)
silver_index_mins_60m_core_check = _build_silver_check(
    asset=silver_index_mins_60m,
    name="silver_index_mins_60m_core_check",
    silver_freq=60,
    source_deps=(raw_index_mins_60m,),
)
silver_index_mins_90m_core_check = _build_silver_check(
    asset=silver_index_mins_90m,
    name="silver_index_mins_90m_core_check",
    silver_freq=90,
    source_deps=(silver_index_mins_30m,),
)
silver_index_mins_120m_core_check = _build_silver_check(
    asset=silver_index_mins_120m,
    name="silver_index_mins_120m_core_check",
    silver_freq=120,
    source_deps=(silver_index_mins_60m,),
)


__all__ = [
    "raw_index_mins_1m_core_check",
    "raw_index_mins_5m_core_check",
    "raw_index_mins_15m_core_check",
    "raw_index_mins_30m_core_check",
    "raw_index_mins_60m_core_check",
    "silver_index_mins_1m_core_check",
    "silver_index_mins_5m_core_check",
    "silver_index_mins_15m_core_check",
    "silver_index_mins_30m_core_check",
    "silver_index_mins_60m_core_check",
    "silver_index_mins_90m_core_check",
    "silver_index_mins_120m_core_check",
]
