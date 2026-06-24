"""Shared SQL and audit contract for the wealth market turnover gold asset."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import silver_stk_mins_path
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
WEALTH_MARKET_TURNOVER_BUILD_VERSION = "v1"
WEALTH_MARKET_TURNOVER_CHECK_NAME = "gold_wealth_market_turnover_integrity_check"

GOLD_WEALTH_MARKET_TURNOVER_COLUMNS = tuple(
    column.name for column in GOLD_WEALTH_MARKET_TURNOVER_SCHEMA
)
GOLD_WEALTH_MARKET_TURNOVER_COLUMN_TYPES = {
    column.name: column.type.upper() for column in GOLD_WEALTH_MARKET_TURNOVER_SCHEMA
}


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverInputPath:
    freq: int
    path: Path


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


def wealth_market_turnover_input_paths(
    lake_root: Path,
    partition_key: str,
    freqs: Sequence[int] = STK_MINS_FREQS,
) -> tuple[WealthMarketTurnoverInputPath, ...]:
    normalized_freqs = tuple(normalize_stk_mins_freq(freq) for freq in freqs)
    if normalized_freqs != tuple(STK_MINS_FREQS):
        allowed = ", ".join(str(freq) for freq in STK_MINS_FREQS)
        raise ValueError(
            "wealth market turnover requires the full silver stk_mins freq set: "
            f"{allowed}."
        )
    return tuple(
        WealthMarketTurnoverInputPath(
            freq=freq,
            path=silver_stk_mins_path(lake_root, freq, partition_key),
        )
        for freq in normalized_freqs
    )


def wealth_market_turnover_select_sql(
    *,
    input_paths: Sequence[WealthMarketTurnoverInputPath],
    partition_key: str,
    built_at_sql: str = "current_timestamp",
) -> str:
    if not input_paths:
        raise ValueError("wealth market turnover input_paths must not be empty.")
    source_unions = "\nUNION ALL\n".join(
        _silver_stk_mins_source_select(input_path) for input_path in input_paths
    )
    return f"""
WITH source_rows AS (
  {source_unions}
),
point_rows AS (
  SELECT
    freq,
    trade_date,
    trade_time,
    CAST(round(sum(amount) / 1000, 2) AS DECIMAL(20,2)) AS amount,
    CAST(sum(vol) AS BIGINT) AS vol,
    CAST(count(DISTINCT ts_code) AS INTEGER) AS security_count
  FROM source_rows
  GROUP BY freq, trade_date, trade_time
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
  FROM point_rows
  GROUP BY freq, trade_date
),
summary AS (
  SELECT
    CAST({duckdb_string(WEALTH_MARKET_TURNOVER_TYPE)} AS VARCHAR) AS type,
    CAST({duckdb_string(WEALTH_MARKET_TURNOVER_MARKET)} AS VARCHAR) AS market,
    trade_date,
    CAST(freq AS SMALLINT) AS freq,
    CAST({duckdb_string(WEALTH_MARKET_TURNOVER_BUILD_STATUS)} AS VARCHAR)
      AS build_status,
    max(trade_time) AS latest_trade_time,
    CAST(round(sum(amount) / 1000, 2) AS DECIMAL(20,2)) AS total_amount,
    CAST(sum(vol) AS BIGINT) AS total_vol,
    CAST(count(DISTINCT ts_code) AS INTEGER) AS security_count,
    CAST(count(*) AS BIGINT) AS source_row_count,
    CAST({duckdb_string(WEALTH_MARKET_TURNOVER_BUILD_VERSION)} AS VARCHAR)
      AS build_version,
    CAST({built_at_sql} AS TIMESTAMP WITH TIME ZONE) AS built_at,
    CAST(NULL AS VARCHAR) AS build_note
  FROM source_rows
  GROUP BY trade_date, freq
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
    connection,
    input_paths: Sequence[WealthMarketTurnoverInputPath],
    partition_key: str,
    target_path: Path,
    built_at_sql: str = "current_timestamp",
) -> WealthMarketTurnoverWriteAudit:
    _validate_silver_input_files(
        connection=connection,
        input_paths=input_paths,
        partition_key=partition_key,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    try:
        connection.execute(
            copy_query_to_parquet(
                wealth_market_turnover_select_sql(
                    input_paths=input_paths,
                    partition_key=partition_key,
                    built_at_sql=built_at_sql,
                ),
                temporary_path,
            )
        )
        file_audit = audit_gold_wealth_market_turnover_file_contract(
            connection=connection,
            target_path=temporary_path,
            partition_key=partition_key,
        )
        if not file_audit.passed:
            raise RuntimeError(
                "wealth market turnover file contract failed before replace: "
                f"reason_code={file_audit.reason_code}."
            )
        recompute_audit = audit_gold_wealth_market_turnover_recomputed_from_silver(
            connection=connection,
            target_path=temporary_path,
            input_paths=input_paths,
            partition_key=partition_key,
        )
        if not recompute_audit.passed:
            raise RuntimeError(
                "wealth market turnover silver recompute audit failed before replace: "
                f"reason_code={recompute_audit.reason_code}."
            )
        os.replace(temporary_path, target_path)
        return summarize_gold_wealth_market_turnover_file(
            connection=connection,
            target_path=target_path,
        )
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
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


def audit_gold_wealth_market_turnover_recomputed_from_silver(
    *,
    connection,
    target_path: Path,
    input_paths: Sequence[WealthMarketTurnoverInputPath],
    partition_key: str,
) -> WealthMarketTurnoverIntegrityAudit:
    missing_input_paths = tuple(
        str(input_path.path) for input_path in input_paths if not input_path.path.exists()
    )
    if missing_input_paths:
        return _failed_audit(
            failure_stage="recomputed_from_silver",
            reason_code="missing_silver_input",
            missing_file_paths=missing_input_paths,
            metadata={
                "gold_file_path": str(target_path),
                "partition_key": partition_key,
                "missing_file_paths": list(missing_input_paths),
            },
        )
    if not target_path.exists():
        return _failed_audit(
            failure_stage="recomputed_from_silver",
            reason_code="missing_gold_file",
            missing_file_paths=(str(target_path),),
            metadata={"gold_file_path": str(target_path), "partition_key": partition_key},
        )

    target_rows = _normalised_target_rows(connection, target_path)
    recomputed_rows = _normalised_recomputed_rows(
        connection=connection,
        input_paths=input_paths,
        partition_key=partition_key,
    )
    if target_rows != recomputed_rows:
        mismatch_sample = _mismatch_sample(target_rows, recomputed_rows)
        return _failed_audit(
            failure_stage="recomputed_from_silver",
            reason_code="gold_silver_recompute_mismatch",
            checked_row_count=len(target_rows),
            failed_row_count=len(mismatch_sample) or 1,
            sample_rows=tuple(mismatch_sample),
            metadata={
                "gold_file_path": str(target_path),
                "input_file_paths": [str(input_path.path) for input_path in input_paths],
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
            "input_file_paths": [str(input_path.path) for input_path in input_paths],
            "partition_key": partition_key,
            "row_count": len(target_rows),
        },
    )


def summarize_gold_wealth_market_turnover_file(
    *,
    connection,
    target_path: Path,
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
    return WealthMarketTurnoverWriteAudit(
        file_path=target_path,
        row_count=row_count,
        observed_columns=observed_columns,
        source_row_count=int(row[0] or 0),
        total_amount=str(row[1] or "0"),
        total_vol=int(row[2] or 0),
        security_count_by_freq=security_count_by_freq,
        latest_trade_time_by_freq=latest_trade_time_by_freq,
    )


def _silver_stk_mins_source_select(input_path: WealthMarketTurnoverInputPath) -> str:
    return f"""
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(freq AS SMALLINT) AS freq,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(trade_time AS TIMESTAMP) AS trade_time,
    CAST(vol AS DOUBLE) AS vol,
    CAST(amount AS DOUBLE) AS amount
  FROM {read_parquet(input_path.path, hive_partitioning=False)}
"""


def _validate_silver_input_files(
    *,
    connection,
    input_paths: Sequence[WealthMarketTurnoverInputPath],
    partition_key: str,
) -> None:
    if tuple(input_path.freq for input_path in input_paths) != tuple(STK_MINS_FREQS):
        raise ValueError("wealth market turnover input paths must cover all source freqs.")
    for input_path in input_paths:
        if not input_path.path.exists():
            raise FileNotFoundError(
                f"Missing silver stk_mins file for freq={input_path.freq}: {input_path.path}"
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
        SELECT type, market, trade_date, freq, build_status
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
          build_version
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
    input_paths: Sequence[WealthMarketTurnoverInputPath],
    partition_key: str,
) -> dict[int, dict[str, object]]:
    rows = connection.execute(
        wealth_market_turnover_select_sql(
            input_paths=input_paths,
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
    if isinstance(value, Decimal):
        return format(value, "f")
    return format(Decimal(str(value)), "f")


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
