"""Shared SQL and audit contract for the wealth market turnover gold asset."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import silver_stk_mins_path, silver_stock_daily_path
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    normalize_stk_mins_freq,
)

WEALTH_MARKET_TURNOVER_TYPE = "stock"
WEALTH_MARKET_TURNOVER_MARKET = "CN_A"
WEALTH_MARKET_TURNOVER_BUILD_STATUS = "READY"
WEALTH_MARKET_TURNOVER_BUILD_VERSION = "v2"
WEALTH_MARKET_TURNOVER_BUILD_NOTE = (
    "bse_close_auction_reconciled_from_silver_stock_daily"
)
WEALTH_MARKET_TURNOVER_BSE_SUFFIX = ".BJ"
WEALTH_MARKET_TURNOVER_CLOSE_TIME = "15:00:00"
WEALTH_MARKET_TURNOVER_CHECK_NAME = "gold_wealth_market_turnover_integrity_check"

GOLD_WEALTH_MARKET_TURNOVER_COLUMNS = tuple(
    column.name for column in GOLD_WEALTH_MARKET_TURNOVER_SCHEMA
)
GOLD_WEALTH_MARKET_TURNOVER_COLUMN_TYPES = {
    column.name: column.type.upper() for column in GOLD_WEALTH_MARKET_TURNOVER_SCHEMA
}


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverMinuteSourcePath:
    freq: int
    path: Path


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverSourcePaths:
    minute_paths: tuple[WealthMarketTurnoverMinuteSourcePath, ...]
    stock_daily_path: Path


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverIntegrityAudit:
    passed: bool
    failure_stage: str | None
    reason_code: str | None
    checked_row_count: int
    failed_row_count: int
    missing_file_paths: tuple[str, ...]
    sample_rows: tuple[dict[str, object], ...]
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverWriteAudit:
    file_path: Path
    row_count: int
    observed_columns: tuple[str, ...]
    source_row_count: int
    total_amount: str
    total_vol: int
    security_count_by_freq: dict[str, int]
    latest_trade_time_by_freq: dict[str, str]
    bse_security_count: int
    bse_residual_vol_by_freq: dict[str, int]
    bse_residual_amount_by_freq: dict[str, str]
    bse_rounding_residual_code_count_by_freq: dict[str, int]


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverCorrectionStats:
    bse_security_count: int
    residual_vol_by_freq: dict[str, int]
    residual_amount_by_freq: dict[str, str]
    rounding_residual_code_count_by_freq: dict[str, int]


def wealth_market_turnover_source_paths(
    lake_root: Path,
    partition_key: str,
    freqs: Sequence[int] = STK_MINS_FREQS,
) -> WealthMarketTurnoverSourcePaths:
    normalized_freqs = tuple(normalize_stk_mins_freq(freq) for freq in freqs)
    if normalized_freqs != tuple(STK_MINS_FREQS):
        allowed = ", ".join(str(freq) for freq in STK_MINS_FREQS)
        raise ValueError(
            "wealth market turnover requires the full silver stk_mins freq set: "
            f"{allowed}."
        )
    return WealthMarketTurnoverSourcePaths(
        minute_paths=tuple(
            WealthMarketTurnoverMinuteSourcePath(
                freq=freq,
                path=silver_stk_mins_path(lake_root, freq, partition_key),
            )
            for freq in normalized_freqs
        ),
        stock_daily_path=silver_stock_daily_path(lake_root, partition_key),
    )


def wealth_market_turnover_select_sql(
    *,
    source_paths: WealthMarketTurnoverSourcePaths,
    partition_key: str,
    built_at_sql: str = "current_timestamp",
) -> str:
    if not source_paths.minute_paths:
        raise ValueError("wealth market turnover minute_paths must not be empty.")
    source_unions = "\nUNION ALL\n".join(
        _silver_stk_mins_source_select(input_path)
        for input_path in source_paths.minute_paths
    )
    freq_values = ", ".join(f"({freq})" for freq in STK_MINS_FREQS)
    return f"""
WITH minute_source_rows AS (
  {source_unions}
),
freqs(freq) AS (
  VALUES {freq_values}
),
daily_bse_rows AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(vol AS DECIMAL(38,4)) * 100 AS daily_vol_shares,
    CAST(amount AS DECIMAL(38,4)) * 1000 AS daily_amount_yuan
  FROM {read_parquet(source_paths.stock_daily_path, hive_partitioning=False)}
  WHERE ends_with(upper(trim(CAST(ts_code AS VARCHAR))),
                  {duckdb_string(WEALTH_MARKET_TURNOVER_BSE_SUFFIX)})
),
minute_bse_totals_by_code_freq AS (
  SELECT
    freq,
    ts_code,
    sum(CAST(vol AS DECIMAL(38,4))) AS minute_vol_shares,
    sum(CAST(amount AS DECIMAL(38,4))) AS minute_amount_yuan
  FROM minute_source_rows
  WHERE ends_with(upper(trim(ts_code)),
                  {duckdb_string(WEALTH_MARKET_TURNOVER_BSE_SUFFIX)})
  GROUP BY freq, ts_code
),
bse_residuals_by_code_freq AS (
  SELECT
    freqs.freq,
    daily_bse_rows.ts_code,
    daily_bse_rows.daily_vol_shares
      - coalesce(minute_bse_totals_by_code_freq.minute_vol_shares, 0)
      AS residual_vol,
    daily_bse_rows.daily_amount_yuan
      - coalesce(minute_bse_totals_by_code_freq.minute_amount_yuan, 0)
      AS residual_amount
  FROM daily_bse_rows
  CROSS JOIN freqs
  LEFT JOIN minute_bse_totals_by_code_freq
    ON minute_bse_totals_by_code_freq.freq = freqs.freq
   AND minute_bse_totals_by_code_freq.ts_code = daily_bse_rows.ts_code
),
bse_correction_by_freq AS (
  SELECT
    freqs.freq,
    coalesce(sum(bse_residuals_by_code_freq.residual_vol), 0)
      AS residual_vol,
    coalesce(sum(bse_residuals_by_code_freq.residual_amount), 0)
      AS residual_amount
  FROM freqs
  LEFT JOIN bse_residuals_by_code_freq USING (freq)
  GROUP BY freqs.freq
),
point_rows_base AS (
  SELECT
    freq,
    trade_date,
    trade_time,
    sum(CAST(amount AS DECIMAL(38,4))) AS amount_yuan,
    sum(CAST(vol AS DECIMAL(38,4))) AS vol_shares,
    CAST(count(DISTINCT ts_code) AS INTEGER) AS security_count
  FROM minute_source_rows
  GROUP BY freq, trade_date, trade_time
),
point_rows_corrected AS (
  SELECT
    point_rows_base.freq,
    point_rows_base.trade_date,
    point_rows_base.trade_time,
    CAST(
      round(
        (
          point_rows_base.amount_yuan
          + CASE
              WHEN CAST(point_rows_base.trade_time AS TIME)
                   = TIME {duckdb_string(WEALTH_MARKET_TURNOVER_CLOSE_TIME)}
              THEN bse_correction_by_freq.residual_amount
              ELSE 0
            END
        ) / 1000,
        2
      ) AS DECIMAL(20,2)
    ) AS amount,
    CAST(
      round(
        point_rows_base.vol_shares
        + CASE
            WHEN CAST(point_rows_base.trade_time AS TIME)
                 = TIME {duckdb_string(WEALTH_MARKET_TURNOVER_CLOSE_TIME)}
            THEN bse_correction_by_freq.residual_vol
            ELSE 0
          END,
        0
      ) AS BIGINT
    ) AS vol,
    point_rows_base.security_count
  FROM point_rows_base
  JOIN bse_correction_by_freq USING (freq)
),
point_json AS (
  SELECT
    freq,
    trade_date,
    to_json(
      list(
        struct_pack(
          tradeTime := strftime(trade_time, '%H:%M'),
          tradeTimeTs := strftime(trade_time, '%Y-%m-%d %H:%M:%S'),
          amount := amount,
          vol := vol,
          securityCount := security_count
        )
        ORDER BY trade_time
      )
    )::JSON AS points_json
  FROM point_rows_corrected
  GROUP BY freq, trade_date
),
source_summary AS (
  SELECT
    trade_date,
    freq,
    max(trade_time) AS latest_trade_time,
    CAST(count(DISTINCT ts_code) AS INTEGER) AS security_count,
    CAST(count(*) AS BIGINT) AS source_row_count
  FROM minute_source_rows
  GROUP BY trade_date, freq
),
corrected_summary AS (
  SELECT
    trade_date,
    freq,
    CAST(round(sum(amount), 2) AS DECIMAL(20,2)) AS total_amount,
    CAST(sum(vol) AS BIGINT) AS total_vol
  FROM point_rows_corrected
  GROUP BY trade_date, freq
),
summary AS (
  SELECT
    CAST({duckdb_string(WEALTH_MARKET_TURNOVER_TYPE)} AS VARCHAR) AS type,
    CAST({duckdb_string(WEALTH_MARKET_TURNOVER_MARKET)} AS VARCHAR) AS market,
    trade_date,
    CAST(freq AS SMALLINT) AS freq,
    CAST({duckdb_string(WEALTH_MARKET_TURNOVER_BUILD_STATUS)} AS VARCHAR)
      AS build_status,
    source_summary.latest_trade_time,
    corrected_summary.total_amount,
    corrected_summary.total_vol,
    source_summary.security_count,
    source_summary.source_row_count,
    CAST({duckdb_string(WEALTH_MARKET_TURNOVER_BUILD_VERSION)} AS VARCHAR)
      AS build_version,
    CAST({built_at_sql} AS TIMESTAMP WITH TIME ZONE) AS built_at,
    CAST({duckdb_string(WEALTH_MARKET_TURNOVER_BUILD_NOTE)} AS VARCHAR)
      AS build_note
  FROM source_summary
  JOIN corrected_summary USING (trade_date, freq)
)
SELECT
  summary.type,
  summary.market,
  summary.trade_date,
  summary.freq,
  summary.build_status,
  summary.latest_trade_time,
  summary.total_amount,
  summary.total_vol,
  summary.security_count,
  summary.source_row_count,
  point_json.points_json,
  summary.build_version,
  summary.built_at,
  summary.build_note
FROM summary
JOIN point_json USING (trade_date, freq)
WHERE summary.trade_date = DATE {duckdb_string(partition_key)}
ORDER BY summary.freq
"""


def write_gold_wealth_market_turnover_partition(
    *,
    duckdb_resource: Any,
    source_paths: WealthMarketTurnoverSourcePaths,
    partition_key: str,
    staging_path: Path,
    target_path: Path,
    built_at_sql: str = "current_timestamp",
) -> WealthMarketTurnoverWriteAudit:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    _assert_same_filesystem(staging_path=staging_path, target_path=target_path)
    candidate_audit = build_gold_wealth_market_turnover_candidate(
        duckdb_resource=duckdb_resource,
        source_paths=source_paths,
        partition_key=partition_key,
        candidate_path=staging_path,
        built_at_sql=built_at_sql,
    )
    try:
        os.replace(staging_path, target_path)
        correction_stats = WealthMarketTurnoverCorrectionStats(
            bse_security_count=candidate_audit.bse_security_count,
            residual_vol_by_freq=candidate_audit.bse_residual_vol_by_freq,
            residual_amount_by_freq=candidate_audit.bse_residual_amount_by_freq,
            rounding_residual_code_count_by_freq=(
                candidate_audit.bse_rounding_residual_code_count_by_freq
            ),
        )
        with duckdb_resource.connect() as audit_connection:
            _disable_external_file_cache(audit_connection)
            return summarize_gold_wealth_market_turnover_file(
                connection=audit_connection,
                target_path=target_path,
                correction_stats=correction_stats,
            )
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise


def build_gold_wealth_market_turnover_candidate(
    *,
    duckdb_resource: Any,
    source_paths: WealthMarketTurnoverSourcePaths,
    partition_key: str,
    candidate_path: Path,
    built_at_sql: str = "current_timestamp",
) -> WealthMarketTurnoverWriteAudit:
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    if candidate_path.exists():
        candidate_path.unlink()
    try:
        with duckdb_resource.connect() as write_connection:
            _disable_external_file_cache(write_connection)
            correction_stats = _validate_source_files(
                connection=write_connection,
                source_paths=source_paths,
                partition_key=partition_key,
            )
            write_connection.execute(
                copy_query_to_parquet(
                    wealth_market_turnover_select_sql(
                        source_paths=source_paths,
                        partition_key=partition_key,
                        built_at_sql=built_at_sql,
                    ),
                    candidate_path,
                ),
            )
        with duckdb_resource.connect() as audit_connection:
            _disable_external_file_cache(audit_connection)
            file_audit = audit_gold_wealth_market_turnover_file_contract(
                connection=audit_connection,
                target_path=candidate_path,
                partition_key=partition_key,
            )
            if not file_audit.passed:
                raise RuntimeError(
                    "wealth market turnover file contract failed before promote: "
                    f"reason_code={file_audit.reason_code}."
                )
            recompute_audit = audit_gold_wealth_market_turnover_recomputed_from_sources(
                connection=audit_connection,
                target_path=candidate_path,
                source_paths=source_paths,
                partition_key=partition_key,
                source_files_validated=True,
            )
            if not recompute_audit.passed:
                raise RuntimeError(
                    "wealth market turnover source recompute audit failed before promote: "
                    f"reason_code={recompute_audit.reason_code}."
                )
            return summarize_gold_wealth_market_turnover_file(
                connection=audit_connection,
                target_path=candidate_path,
                correction_stats=correction_stats,
            )
    except Exception:
        if candidate_path.exists():
            candidate_path.unlink()
        raise


def audit_gold_wealth_market_turnover_file_contract(
    *,
    connection,
    target_path: Path,
    partition_key: str,
) -> WealthMarketTurnoverIntegrityAudit:
    if not target_path.exists():
        return _failed_audit(
            failure_stage="file_contract",
            reason_code="missing_file",
            missing_file_paths=(str(target_path),),
            metadata={"file_path": str(target_path), "partition_key": partition_key},
        )

    schema_result = _schema_result(connection, target_path)
    if schema_result["schema_matches"] is not True:
        return _failed_audit(
            failure_stage="file_contract",
            reason_code="schema_mismatch",
            checked_row_count=0,
            metadata={
                "file_path": str(target_path),
                "partition_key": partition_key,
                **schema_result,
            },
        )

    row_count = _row_count(connection, target_path)
    if row_count != len(STK_MINS_FREQS):
        return _failed_audit(
            failure_stage="file_contract",
            reason_code="row_count_not_five",
            checked_row_count=row_count,
            failed_row_count=abs(row_count - len(STK_MINS_FREQS)),
            metadata={
                "file_path": str(target_path),
                "partition_key": partition_key,
                "row_count": row_count,
            },
        )

    invalid_rows = _file_contract_invalid_rows(connection, target_path, partition_key)
    if invalid_rows:
        return _failed_audit(
            failure_stage="file_contract",
            reason_code="invalid_contract_rows",
            checked_row_count=row_count,
            failed_row_count=len(invalid_rows),
            sample_rows=tuple(invalid_rows),
            metadata={
                "file_path": str(target_path),
                "partition_key": partition_key,
                "invalid_row_count": len(invalid_rows),
            },
        )

    observed_freqs = _observed_freqs(connection, target_path)
    if observed_freqs != tuple(STK_MINS_FREQS):
        return _failed_audit(
            failure_stage="file_contract",
            reason_code="freq_set_mismatch",
            checked_row_count=row_count,
            metadata={
                "file_path": str(target_path),
                "partition_key": partition_key,
                "observed_freqs": list(observed_freqs),
                "expected_freqs": list(STK_MINS_FREQS),
            },
        )

    duplicate_key_count = _duplicate_target_key_count(connection, target_path)
    if duplicate_key_count:
        return _failed_audit(
            failure_stage="file_contract",
            reason_code="duplicate_business_key",
            checked_row_count=row_count,
            failed_row_count=duplicate_key_count,
            metadata={
                "file_path": str(target_path),
                "partition_key": partition_key,
                "duplicate_key_count": duplicate_key_count,
            },
        )

    points_failure = _points_json_failure(connection, target_path)
    if points_failure is not None:
        return _failed_audit(
            failure_stage="file_contract",
            reason_code=points_failure["reason_code"],
            checked_row_count=row_count,
            failed_row_count=1,
            sample_rows=(points_failure,),
            metadata={
                "file_path": str(target_path),
                "partition_key": partition_key,
                "points_json_failure": points_failure,
            },
        )

    return WealthMarketTurnoverIntegrityAudit(
        passed=True,
        failure_stage=None,
        reason_code=None,
        checked_row_count=row_count,
        failed_row_count=0,
        missing_file_paths=(),
        sample_rows=(),
        metadata={
            "file_path": str(target_path),
            "partition_key": partition_key,
            "row_count": row_count,
            "observed_freqs": list(observed_freqs),
        },
    )


def audit_gold_wealth_market_turnover_recomputed_from_sources(
    *,
    connection,
    target_path: Path,
    source_paths: WealthMarketTurnoverSourcePaths,
    partition_key: str,
    source_files_validated: bool = False,
) -> WealthMarketTurnoverIntegrityAudit:
    missing_input_paths = tuple(
        str(path)
        for path in _source_file_paths(source_paths)
        if not path.exists()
    )
    if missing_input_paths:
        return _failed_audit(
            failure_stage="recomputed_from_sources",
            reason_code="missing_source_input",
            missing_file_paths=missing_input_paths,
            metadata={
                "gold_file_path": str(target_path),
                "partition_key": partition_key,
                "missing_file_paths": list(missing_input_paths),
            },
        )
    if not target_path.exists():
        return _failed_audit(
            failure_stage="recomputed_from_sources",
            reason_code="missing_gold_file",
            missing_file_paths=(str(target_path),),
            metadata={"gold_file_path": str(target_path), "partition_key": partition_key},
        )

    if not source_files_validated:
        try:
            _validate_source_files(
                connection=connection,
                source_paths=source_paths,
                partition_key=partition_key,
            )
        except (FileNotFoundError, RuntimeError, ValueError) as error:
            return _failed_audit(
                failure_stage="recomputed_from_sources",
                reason_code=_source_validation_reason_code(error),
                checked_row_count=0,
                failed_row_count=1,
                sample_rows=(
                    {
                        "error_type": type(error).__name__,
                        "message": str(error)[:500],
                    },
                ),
                metadata={
                    "gold_file_path": str(target_path),
                    "input_file_paths": [
                        str(path) for path in _source_file_paths(source_paths)
                    ],
                    "partition_key": partition_key,
                },
            )

    target_rows = _normalised_target_rows(connection, target_path)
    recomputed_rows = _normalised_recomputed_rows(
        connection=connection,
        source_paths=source_paths,
        partition_key=partition_key,
    )
    if target_rows != recomputed_rows:
        mismatch_sample = _mismatch_sample(target_rows, recomputed_rows)
        return _failed_audit(
            failure_stage="recomputed_from_sources",
            reason_code="gold_source_recompute_mismatch",
            checked_row_count=len(target_rows),
            failed_row_count=len(mismatch_sample) or 1,
            sample_rows=tuple(mismatch_sample),
            metadata={
                "gold_file_path": str(target_path),
                "input_file_paths": [str(path) for path in _source_file_paths(source_paths)],
                "partition_key": partition_key,
                "target_row_count": len(target_rows),
                "recomputed_row_count": len(recomputed_rows),
            },
        )

    return WealthMarketTurnoverIntegrityAudit(
        passed=True,
        failure_stage=None,
        reason_code=None,
        checked_row_count=len(target_rows),
        failed_row_count=0,
        missing_file_paths=(),
        sample_rows=(),
        metadata={
            "gold_file_path": str(target_path),
            "input_file_paths": [str(path) for path in _source_file_paths(source_paths)],
            "partition_key": partition_key,
            "row_count": len(target_rows),
        },
    )


def summarize_gold_wealth_market_turnover_file(
    *,
    connection,
    target_path: Path,
    correction_stats: WealthMarketTurnoverCorrectionStats | None = None,
) -> WealthMarketTurnoverWriteAudit:
    observed_columns = tuple(_column_names(connection, target_path))
    row_count = _row_count(connection, target_path)
    row = connection.execute(
        f"""
        SELECT
          CAST(sum(source_row_count) AS BIGINT) AS source_row_count,
          CAST(sum(total_amount) AS VARCHAR) AS total_amount,
          CAST(sum(total_vol) AS BIGINT) AS total_vol
        FROM {read_parquet(target_path, hive_partitioning=False)}
        """
    ).fetchone()
    security_count_by_freq = {
        str(freq): int(security_count)
        for freq, security_count in connection.execute(
            f"""
            SELECT freq, security_count
            FROM {read_parquet(target_path, hive_partitioning=False)}
            ORDER BY freq
            """
        ).fetchall()
    }
    latest_trade_time_by_freq = {
        str(freq): _normalise_value(latest_trade_time)
        for freq, latest_trade_time in connection.execute(
            f"""
            SELECT freq, latest_trade_time
            FROM {read_parquet(target_path, hive_partitioning=False)}
            ORDER BY freq
            """
        ).fetchall()
    }
    stats = correction_stats or WealthMarketTurnoverCorrectionStats(
        bse_security_count=0,
        residual_vol_by_freq={str(freq): 0 for freq in STK_MINS_FREQS},
        residual_amount_by_freq={str(freq): "0" for freq in STK_MINS_FREQS},
        rounding_residual_code_count_by_freq={
            str(freq): 0 for freq in STK_MINS_FREQS
        },
    )
    return WealthMarketTurnoverWriteAudit(
        file_path=target_path,
        row_count=row_count,
        observed_columns=observed_columns,
        source_row_count=int(row[0] or 0),
        total_amount=str(row[1] or "0"),
        total_vol=int(row[2] or 0),
        security_count_by_freq=security_count_by_freq,
        latest_trade_time_by_freq=latest_trade_time_by_freq,
        bse_security_count=stats.bse_security_count,
        bse_residual_vol_by_freq=stats.residual_vol_by_freq,
        bse_residual_amount_by_freq=stats.residual_amount_by_freq,
        bse_rounding_residual_code_count_by_freq=(
            stats.rounding_residual_code_count_by_freq
        ),
    )


def _silver_stk_mins_source_select(
    input_path: WealthMarketTurnoverMinuteSourcePath,
) -> str:
    return f"""
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(freq AS SMALLINT) AS freq,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(trade_time AS TIMESTAMP) AS trade_time,
    CAST(vol AS BIGINT) AS vol,
    CAST(amount AS DECIMAL(38,4)) AS amount
  FROM {read_parquet(input_path.path, hive_partitioning=False)}
"""


def _disable_external_file_cache(connection) -> None:
    connection.execute("SET enable_external_file_cache=false")


def _validate_source_files(
    *,
    connection,
    source_paths: WealthMarketTurnoverSourcePaths,
    partition_key: str,
) -> WealthMarketTurnoverCorrectionStats:
    if tuple(path.freq for path in source_paths.minute_paths) != tuple(STK_MINS_FREQS):
        raise ValueError("wealth market turnover input paths must cover all source freqs.")
    for input_path in source_paths.minute_paths:
        if not input_path.path.exists():
            raise FileNotFoundError(
                f"Missing silver stk_mins file for freq={input_path.freq}: {input_path.path}"
            )
        _require_columns(
            connection,
            input_path.path,
            ("ts_code", "freq", "trade_date", "trade_time", "vol", "amount"),
            reason_code="minute_schema_mismatch",
        )
        row_count = int(
            connection.execute(
                count_parquet_query(input_path.path, hive_partitioning=False)
            ).fetchone()[0]
        )
        if row_count == 0:
            raise RuntimeError(
                f"Silver stk_mins file is empty for freq={input_path.freq}: {input_path.path}"
            )
        invalid_scope_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {read_parquet(input_path.path, hive_partitioning=False)}
                WHERE CAST(freq AS INTEGER) != {input_path.freq}
                   OR CAST(trade_date AS DATE) != DATE {duckdb_string(partition_key)}
                   OR ts_code IS NULL
                   OR trim(CAST(ts_code AS VARCHAR)) = ''
                   OR trade_time IS NULL
                   OR vol IS NULL
                   OR amount IS NULL
                   OR CAST(vol AS DECIMAL(38,4)) < 0
                   OR CAST(amount AS DECIMAL(38,4)) < 0
                """
            ).fetchone()[0]
        )
        if invalid_scope_count:
            raise RuntimeError(
                "Silver stk_mins input has invalid key/date/freq rows for "
                f"freq={input_path.freq}: invalid_row_count={invalid_scope_count}."
            )
        duplicate_key_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM (
                  SELECT ts_code, trade_time
                  FROM {read_parquet(input_path.path, hive_partitioning=False)}
                  GROUP BY ts_code, trade_time
                  HAVING count(*) > 1
                ) duplicate_keys
                """
            ).fetchone()[0]
        )
        if duplicate_key_count:
            raise RuntimeError(
                "Silver stk_mins input has duplicate ts_code/trade_time keys for "
                f"freq={input_path.freq}: duplicate_key_count={duplicate_key_count}."
            )

    daily_path = source_paths.stock_daily_path
    if not daily_path.exists():
        raise FileNotFoundError(
            f"missing_stock_daily_source: {daily_path}"
        )
    _require_columns(
        connection,
        daily_path,
        ("ts_code", "trade_date", "vol", "amount"),
        reason_code="stock_daily_schema_mismatch",
    )
    daily_row_count = _row_count(connection, daily_path)
    if daily_row_count == 0:
        raise RuntimeError("stock_daily_empty")
    invalid_daily_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {read_parquet(daily_path, hive_partitioning=False)}
            WHERE CAST(trade_date AS DATE) != DATE {duckdb_string(partition_key)}
               OR ts_code IS NULL
               OR trim(CAST(ts_code AS VARCHAR)) = ''
               OR vol IS NULL
               OR amount IS NULL
               OR CAST(vol AS DECIMAL(38,4)) < 0
               OR CAST(amount AS DECIMAL(38,4)) < 0
            """
        ).fetchone()[0]
    )
    if invalid_daily_count:
        raise RuntimeError(
            "stock_daily_partition_mismatch: "
            f"invalid_row_count={invalid_daily_count}."
        )
    duplicate_daily_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM (
              SELECT ts_code
              FROM {read_parquet(daily_path, hive_partitioning=False)}
              GROUP BY ts_code
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
    )
    if duplicate_daily_count:
        raise RuntimeError(
            "stock_daily_duplicate_key: "
            f"duplicate_key_count={duplicate_daily_count}."
        )

    _validate_bse_code_sets_and_close_points(
        connection=connection,
        source_paths=source_paths,
    )
    return _validate_and_summarize_bse_residuals(
        connection=connection,
        source_paths=source_paths,
    )


def _require_columns(
    connection,
    path: Path,
    required_columns: Sequence[str],
    *,
    reason_code: str,
) -> None:
    observed = set(_column_names(connection, path))
    missing = [column for column in required_columns if column not in observed]
    if missing:
        raise RuntimeError(f"{reason_code}: missing_columns={missing}.")


def _validate_bse_code_sets_and_close_points(
    *,
    connection,
    source_paths: WealthMarketTurnoverSourcePaths,
) -> None:
    daily_path = source_paths.stock_daily_path
    daily_codes_sql = f"""
      SELECT upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code
      FROM {read_parquet(daily_path, hive_partitioning=False)}
      WHERE ends_with(upper(trim(CAST(ts_code AS VARCHAR))),
                      {duckdb_string(WEALTH_MARKET_TURNOVER_BSE_SUFFIX)})
    """
    for minute_path in source_paths.minute_paths:
        minute_codes_sql = f"""
          SELECT DISTINCT upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code
          FROM {read_parquet(minute_path.path, hive_partitioning=False)}
          WHERE ends_with(upper(trim(CAST(ts_code AS VARCHAR))),
                          {duckdb_string(WEALTH_MARKET_TURNOVER_BSE_SUFFIX)})
        """
        mismatch_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM (
                  ({daily_codes_sql} EXCEPT {minute_codes_sql})
                  UNION ALL
                  ({minute_codes_sql} EXCEPT {daily_codes_sql})
                ) mismatches
                """
            ).fetchone()[0]
        )
        if mismatch_count:
            raise RuntimeError(
                "bse_code_set_mismatch: "
                f"freq={minute_path.freq}, mismatch_count={mismatch_count}."
            )
        invalid_close_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM (
                  SELECT
                    daily_codes.ts_code,
                    count(minute_rows.ts_code) AS close_row_count
                  FROM ({daily_codes_sql}) daily_codes
                  LEFT JOIN {read_parquet(minute_path.path, hive_partitioning=False)} minute_rows
                    ON upper(trim(CAST(minute_rows.ts_code AS VARCHAR))) = daily_codes.ts_code
                   AND CAST(minute_rows.trade_time AS TIME)
                       = TIME {duckdb_string(WEALTH_MARKET_TURNOVER_CLOSE_TIME)}
                  GROUP BY daily_codes.ts_code
                  HAVING count(minute_rows.ts_code) != 1
                ) invalid_close_rows
                """
            ).fetchone()[0]
        )
        if invalid_close_count:
            raise RuntimeError(
                "bse_close_point_missing: "
                f"freq={minute_path.freq}, invalid_code_count={invalid_close_count}."
            )


def _validate_and_summarize_bse_residuals(
    *,
    connection,
    source_paths: WealthMarketTurnoverSourcePaths,
) -> WealthMarketTurnoverCorrectionStats:
    residual_sql = _bse_residual_rows_sql(source_paths)
    minute_source_sql = "\nUNION ALL\n".join(
        _silver_stk_mins_source_select(path)
        for path in source_paths.minute_paths
    )
    rows = connection.execute(
        f"""
        SELECT
          freq,
          CAST(round(sum(residual_vol), 0) AS BIGINT) AS residual_vol,
          CAST(sum(residual_amount) AS VARCHAR) AS residual_amount,
          count(*) FILTER (
            WHERE residual_vol = 0 AND residual_amount != 0
          ) AS rounding_residual_code_count,
          count(*) FILTER (WHERE residual_vol < 0) AS negative_vol_count,
          count(*) FILTER (
            WHERE residual_vol > 0 AND residual_amount <= 0
          ) AS nonpositive_amount_count
        FROM ({residual_sql}) residuals
        GROUP BY freq
        ORDER BY freq
        """
    ).fetchall()
    observed_freqs = tuple(int(row[0]) for row in rows)
    if observed_freqs not in ((), tuple(STK_MINS_FREQS)):
        raise RuntimeError(
            "bse_residual_freq_set_mismatch: "
            f"observed_freqs={list(observed_freqs)}."
        )
    if any(int(row[4]) > 0 for row in rows):
        raise RuntimeError("negative_bse_volume_residual")
    if any(int(row[5]) > 0 for row in rows):
        raise RuntimeError("nonpositive_bse_amount_residual")
    if any(Decimal(str(row[2])) < 0 for row in rows):
        raise RuntimeError("negative_bse_aggregate_amount_residual")

    close_freq_count = int(
        connection.execute(
            f"""
            SELECT count(DISTINCT freq)
            FROM (
              {minute_source_sql}
            ) minute_rows
            WHERE CAST(trade_time AS TIME)
                  = TIME {duckdb_string(WEALTH_MARKET_TURNOVER_CLOSE_TIME)}
            """
        ).fetchone()[0]
    )
    if close_freq_count != len(STK_MINS_FREQS):
        raise RuntimeError("missing_close_aggregate_point")

    bse_security_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {read_parquet(source_paths.stock_daily_path, hive_partitioning=False)}
            WHERE ends_with(upper(trim(CAST(ts_code AS VARCHAR))),
                            {duckdb_string(WEALTH_MARKET_TURNOVER_BSE_SUFFIX)})
            """
        ).fetchone()[0]
    )
    residual_vol_by_freq = {str(freq): 0 for freq in STK_MINS_FREQS}
    residual_amount_by_freq = {str(freq): "0" for freq in STK_MINS_FREQS}
    rounding_count_by_freq = {str(freq): 0 for freq in STK_MINS_FREQS}
    for row in rows:
        freq = str(int(row[0]))
        residual_vol_by_freq[freq] = int(row[1])
        residual_amount_by_freq[freq] = _normalise_decimal(row[2])
        rounding_count_by_freq[freq] = int(row[3])
    return WealthMarketTurnoverCorrectionStats(
        bse_security_count=bse_security_count,
        residual_vol_by_freq=residual_vol_by_freq,
        residual_amount_by_freq=residual_amount_by_freq,
        rounding_residual_code_count_by_freq=rounding_count_by_freq,
    )


def _bse_residual_rows_sql(source_paths: WealthMarketTurnoverSourcePaths) -> str:
    minute_unions = "\nUNION ALL\n".join(
        _silver_stk_mins_source_select(path) for path in source_paths.minute_paths
    )
    freq_values = ", ".join(f"({freq})" for freq in STK_MINS_FREQS)
    return f"""
      WITH minute_source_rows AS (
        {minute_unions}
      ),
      freqs(freq) AS (VALUES {freq_values}),
      daily_bse_rows AS (
        SELECT
          upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code,
          CAST(vol AS DECIMAL(38,4)) * 100 AS daily_vol_shares,
          CAST(amount AS DECIMAL(38,4)) * 1000 AS daily_amount_yuan
        FROM {read_parquet(source_paths.stock_daily_path, hive_partitioning=False)}
        WHERE ends_with(upper(trim(CAST(ts_code AS VARCHAR))),
                        {duckdb_string(WEALTH_MARKET_TURNOVER_BSE_SUFFIX)})
      ),
      minute_totals AS (
        SELECT
          freq,
          upper(trim(ts_code)) AS ts_code,
          sum(CAST(vol AS DECIMAL(38,4))) AS minute_vol_shares,
          sum(CAST(amount AS DECIMAL(38,4))) AS minute_amount_yuan
        FROM minute_source_rows
        WHERE ends_with(upper(trim(ts_code)),
                        {duckdb_string(WEALTH_MARKET_TURNOVER_BSE_SUFFIX)})
        GROUP BY freq, ts_code
      )
      SELECT
        freqs.freq,
        daily_bse_rows.ts_code,
        daily_bse_rows.daily_vol_shares
          - coalesce(minute_totals.minute_vol_shares, 0) AS residual_vol,
        daily_bse_rows.daily_amount_yuan
          - coalesce(minute_totals.minute_amount_yuan, 0) AS residual_amount
      FROM daily_bse_rows
      CROSS JOIN freqs
      LEFT JOIN minute_totals
        ON minute_totals.freq = freqs.freq
       AND minute_totals.ts_code = daily_bse_rows.ts_code
    """


def _source_file_paths(
    source_paths: WealthMarketTurnoverSourcePaths,
) -> tuple[Path, ...]:
    return tuple(path.path for path in source_paths.minute_paths) + (
        source_paths.stock_daily_path,
    )


def _source_validation_reason_code(error: Exception) -> str:
    message = str(error)
    known_reason_codes = (
        "missing_stock_daily_source",
        "stock_daily_schema_mismatch",
        "stock_daily_empty",
        "stock_daily_partition_mismatch",
        "stock_daily_duplicate_key",
        "bse_code_set_mismatch",
        "bse_close_point_missing",
        "negative_bse_volume_residual",
        "nonpositive_bse_amount_residual",
        "negative_bse_aggregate_amount_residual",
        "missing_close_aggregate_point",
    )
    for reason_code in known_reason_codes:
        if reason_code in message:
            return reason_code
    if "Missing silver stk_mins" in message:
        return "missing_source_input"
    if "minute_schema_mismatch" in message:
        return "minute_schema_mismatch"
    if "invalid key/date/freq" in message:
        return "minute_scope_mismatch"
    if "duplicate ts_code/trade_time" in message:
        return "minute_duplicate_key"
    return "invalid_source_input"


def _assert_same_filesystem(*, staging_path: Path, target_path: Path) -> None:
    staging_device = os.stat(staging_path.parent).st_dev
    target_device = os.stat(target_path.parent).st_dev
    if staging_device != target_device:
        raise RuntimeError(
            "wealth_market_turnover staging and target must be on the same filesystem"
        )


def _schema_result(connection, path: Path) -> dict[str, object]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    columns = [str(row[0]) for row in rows]
    column_types = {str(row[0]): str(row[1]).upper() for row in rows}
    expected_columns = list(GOLD_WEALTH_MARKET_TURNOVER_COLUMNS)
    expected_types = GOLD_WEALTH_MARKET_TURNOVER_COLUMN_TYPES
    missing_columns = [column for column in expected_columns if column not in columns]
    unexpected_columns = [column for column in columns if column not in expected_columns]
    type_mismatches = {
        column: {
            "expected": expected_type,
            "actual": column_types.get(column),
        }
        for column, expected_type in expected_types.items()
        if column in column_types and column_types[column] != expected_type
    }
    return {
        "schema_matches": not (missing_columns or unexpected_columns or type_mismatches),
        "observed_columns": columns,
        "missing_columns": missing_columns,
        "unexpected_columns": unexpected_columns,
        "type_mismatches": type_mismatches,
    }


def _row_count(connection, path: Path) -> int:
    return int(
        connection.execute(count_parquet_query(path, hive_partitioning=False)).fetchone()[0]
    )


def _column_names(connection, path: Path) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return [str(row[0]) for row in rows]


def _file_contract_invalid_rows(
    connection,
    path: Path,
    partition_key: str,
) -> tuple[dict[str, object], ...]:
    rows = connection.execute(
        f"""
        SELECT type, market, trade_date, freq, build_status, build_note
        FROM {read_parquet(path, hive_partitioning=False)}
        WHERE type IS NULL
           OR market IS NULL
           OR trade_date IS NULL
           OR freq IS NULL
           OR build_status IS NULL
           OR latest_trade_time IS NULL
           OR total_amount IS NULL
           OR total_vol IS NULL
           OR security_count IS NULL
           OR source_row_count IS NULL
           OR points_json IS NULL
           OR build_version IS NULL
           OR built_at IS NULL
           OR type != {duckdb_string(WEALTH_MARKET_TURNOVER_TYPE)}
           OR market != {duckdb_string(WEALTH_MARKET_TURNOVER_MARKET)}
           OR CAST(trade_date AS DATE) != DATE {duckdb_string(partition_key)}
           OR build_status != {duckdb_string(WEALTH_MARKET_TURNOVER_BUILD_STATUS)}
           OR build_version != {duckdb_string(WEALTH_MARKET_TURNOVER_BUILD_VERSION)}
           OR build_note != {duckdb_string(WEALTH_MARKET_TURNOVER_BUILD_NOTE)}
        LIMIT 10
        """
    ).fetchall()
    return tuple(
        {
            "type": row[0],
            "market": row[1],
            "trade_date": _normalise_value(row[2]),
            "freq": int(row[3]) if row[3] is not None else None,
            "build_status": row[4],
            "build_note": row[5],
        }
        for row in rows
    )


def _observed_freqs(connection, path: Path) -> tuple[int, ...]:
    rows = connection.execute(
        f"""
        SELECT DISTINCT CAST(freq AS INTEGER) AS freq
        FROM {read_parquet(path, hive_partitioning=False)}
        ORDER BY freq
        """
    ).fetchall()
    return tuple(int(row[0]) for row in rows)


def _duplicate_target_key_count(connection, path: Path) -> int:
    return int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM (
              SELECT type, market, trade_date, freq
              FROM {read_parquet(path, hive_partitioning=False)}
              GROUP BY type, market, trade_date, freq
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
    )


def _points_json_failure(connection, path: Path) -> dict[str, object] | None:
    rows = connection.execute(
        f"""
        SELECT freq, CAST(points_json AS VARCHAR)
        FROM {read_parquet(path, hive_partitioning=False)}
        ORDER BY freq
        """
    ).fetchall()
    for freq, points_payload in rows:
        try:
            points = json.loads(points_payload)
        except json.JSONDecodeError:
            return {
                "reason_code": "points_json_not_parseable",
                "freq": int(freq),
            }
        if not isinstance(points, list) or not points:
            return {
                "reason_code": "points_json_empty_or_not_array",
                "freq": int(freq),
            }
        trade_time_values = []
        for point in points:
            if not isinstance(point, dict):
                return {
                    "reason_code": "points_json_point_not_object",
                    "freq": int(freq),
                }
            trade_time_ts = point.get("tradeTimeTs")
            if not isinstance(trade_time_ts, str) or not trade_time_ts:
                return {
                    "reason_code": "points_json_missing_trade_time_ts",
                    "freq": int(freq),
                }
            trade_time_values.append(trade_time_ts)
        if trade_time_values != sorted(trade_time_values):
            return {
                "reason_code": "points_json_trade_time_not_sorted",
                "freq": int(freq),
            }
    return None


def _normalised_target_rows(connection, path: Path) -> dict[int, dict[str, object]]:
    rows = connection.execute(
        f"""
        SELECT
          type,
          market,
          trade_date,
          freq,
          build_status,
          latest_trade_time,
          CAST(total_amount AS VARCHAR) AS total_amount,
          total_vol,
          security_count,
          source_row_count,
          CAST(points_json AS VARCHAR) AS points_json,
          build_version,
          build_note
        FROM {read_parquet(path, hive_partitioning=False)}
        ORDER BY freq
        """
    ).fetchall()
    return {
        int(row[3]): _normalise_compare_row(row)
        for row in rows
    }


def _normalised_recomputed_rows(
    *,
    connection,
    source_paths: WealthMarketTurnoverSourcePaths,
    partition_key: str,
) -> dict[int, dict[str, object]]:
    rows = connection.execute(
        wealth_market_turnover_select_sql(
            source_paths=source_paths,
            partition_key=partition_key,
            built_at_sql="TIMESTAMP '2000-01-01 00:00:00'",
        )
    ).fetchall()
    return {
        int(row[3]): _normalise_compare_row(
            (
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[9],
                row[10],
                row[11],
                row[13],
            )
        )
        for row in rows
    }


def _normalise_compare_row(row: Sequence[Any]) -> dict[str, object]:
    points_payload = row[10]
    points = json.loads(points_payload) if isinstance(points_payload, str) else points_payload
    return {
        "type": row[0],
        "market": row[1],
        "trade_date": _normalise_value(row[2]),
        "freq": int(row[3]),
        "build_status": row[4],
        "latest_trade_time": _normalise_value(row[5]),
        "total_amount": _normalise_decimal(row[6]),
        "total_vol": int(row[7]),
        "security_count": int(row[8]),
        "source_row_count": int(row[9]),
        "points_json": _normalise_points(points),
        "build_version": row[11],
        "build_note": row[12],
    }


def _normalise_points(points: Any) -> tuple[dict[str, object], ...]:
    if isinstance(points, str):
        points = json.loads(points)
    return tuple(
        {
            "tradeTime": point["tradeTime"],
            "tradeTimeTs": point["tradeTimeTs"],
            "amount": _normalise_decimal(point["amount"]),
            "vol": int(point["vol"]),
            "securityCount": int(point["securityCount"]),
        }
        for point in points
    )


def _mismatch_sample(
    target_rows: Mapping[int, Mapping[str, object]],
    recomputed_rows: Mapping[int, Mapping[str, object]],
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for freq in sorted(set(target_rows) | set(recomputed_rows)):
        target_row = target_rows.get(freq)
        recomputed_row = recomputed_rows.get(freq)
        if target_row != recomputed_row:
            samples.append(
                {
                    "freq": freq,
                    "target": dict(target_row or {}),
                    "recomputed": dict(recomputed_row or {}),
                }
            )
        if len(samples) >= 5:
            break
    return samples


def _normalise_value(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _normalise_decimal(value: Any) -> str:
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    return format(decimal_value.normalize(), "f")


def _failed_audit(
    *,
    failure_stage: str,
    reason_code: str,
    checked_row_count: int = 0,
    failed_row_count: int = 0,
    missing_file_paths: Sequence[str] = (),
    sample_rows: Sequence[dict[str, object]] = (),
    metadata: Mapping[str, object] | None = None,
) -> WealthMarketTurnoverIntegrityAudit:
    return WealthMarketTurnoverIntegrityAudit(
        passed=False,
        failure_stage=failure_stage,
        reason_code=reason_code,
        checked_row_count=checked_row_count,
        failed_row_count=failed_row_count,
        missing_file_paths=tuple(missing_file_paths),
        sample_rows=tuple(sample_rows),
        metadata=dict(metadata or {}),
    )
