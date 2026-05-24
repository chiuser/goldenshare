import os
from datetime import date
from pathlib import Path
import time
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.assets.index_daily import (
    INDEX_DAILY_RAW_COLUMN_TYPES,
    load_active_index_entries,
    materialize_silver_index_daily_partitions,
)
from orchestrator.defs.checks.index_daily_checks import INDEX_DAILY_HISTORY_BACKFILL_CHECK_EVALUATORS
from orchestrator.defs.duckdb_sql import (
    INDEX_DAILY_RAW_COLUMNS,
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_index_trade_days
from orchestrator.defs.paths import (
    raw_index_daily_path,
    silver_index_daily_active_pool_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource, TushareResource
from orchestrator.defs.tushare_api_io import (
    TUSHARE_API_SOURCE_METHOD,
    TUSHARE_INDEX_DAILY_MIN_REQUEST_INTERVAL_SECONDS,
    TUSHARE_INDEX_DAILY_PAGE_LIMIT,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger


RAW_INDEX_DAILY_ASSET_KEY = dg.AssetKey("raw_tushare_index_daily")
SILVER_INDEX_DAILY_ASSET_KEY = dg.AssetKey("silver_index_daily")


class IndexDailyRepairByCodesConfig(dg.Config):
    ts_codes: list[str]
    start_date: str
    end_date: str
    dry_run: bool = True
    force: bool = False


@dg.op(name="repair_index_daily_by_codes", required_resource_keys={"lake_root", "duckdb", "tushare"})
def repair_index_daily_by_codes(
    context: dg.OpExecutionContext,
    config: IndexDailyRepairByCodesConfig,
) -> dict[str, Any]:
    lake_root: LakeRootResource = context.resources.lake_root
    duckdb: DuckDBResource = context.resources.duckdb
    tushare: TushareResource = context.resources.tushare
    lake_root.ensure_available_for_run()

    requested_ts_codes = _normalize_requested_ts_codes(config.ts_codes)
    start_date = _parse_iso_date(config.start_date, field_name="start_date")
    end_date = _parse_iso_date(config.end_date, field_name="end_date")
    if start_date > end_date:
        raise ValueError("index_daily repair requires start_date <= end_date.")

    lake_root_path = lake_root.root()
    target_trade_dates = _load_sse_open_trade_dates(
        lake_root_path=lake_root_path,
        duckdb=duckdb,
        start_date=start_date,
        end_date=end_date,
    )
    if not target_trade_dates:
        raise RuntimeError(
            "No SSE open trade dates found in silver_trade_calendar for "
            f"{config.start_date}...{config.end_date}."
        )

    _ensure_index_trade_days_registered(context, target_trade_dates)
    active_index_entries = _load_active_index_entries(
        lake_root_path=lake_root_path,
        duckdb=duckdb,
    )
    active_index_codes = {entry["ts_code"] for entry in active_index_entries}
    missing_active_codes = [
        ts_code for ts_code in requested_ts_codes if ts_code not in active_index_codes
    ]
    if missing_active_codes:
        raise RuntimeError(
            "index_daily repair ts_codes must exist in silver_index_daily_active_pool. "
            f"Missing: {missing_active_codes[:20]}"
        )

    existing_row_summary = _existing_requested_code_rows(
        lake_root_path=lake_root_path,
        duckdb=duckdb,
        target_trade_dates=target_trade_dates,
        requested_ts_codes=requested_ts_codes,
    )
    plan_metadata = {
        "start_date": config.start_date,
        "end_date": config.end_date,
        "dry_run": config.dry_run,
        "force": config.force,
        "requested_ts_codes": requested_ts_codes,
        "requested_ts_code_count": len(requested_ts_codes),
        "target_trade_dates": target_trade_dates,
        "target_partition_count": len(target_trade_dates),
        "active_pool_count": len(active_index_entries),
        "estimated_request_count": len(requested_ts_codes),
        "estimated_page_count_minimum": len(requested_ts_codes),
        "limit": TUSHARE_INDEX_DAILY_PAGE_LIMIT,
        "existing_requested_code_rows": existing_row_summary,
    }

    if config.dry_run:
        context.add_output_metadata(plan_metadata)
        context.log.info("index_daily repair dry run completed; no Tushare calls or lake writes.")
        return {
            **plan_metadata,
            "materialized": False,
            "raw_metadata": {},
            "silver_partition_metadata": {},
        }

    if existing_row_summary["raw_missing_count"]:
        raise RuntimeError(
            "index_daily repair requires existing raw partitions before merging code rows. "
            f"Missing sample paths: {existing_row_summary['raw_missing_sample_paths']}"
        )

    if existing_row_summary["existing_row_count"] and not config.force:
        raise RuntimeError(
            "index_daily repair found existing rows for requested ts_codes. "
            "Narrow the date range or set force=true to replace requested code rows. "
            f"Sample: {existing_row_summary['existing_row_samples']}"
        )

    source_date_to_partition_key = {
        partition_key.replace("-", ""): partition_key for partition_key in target_trade_dates
    }
    log = DgStdoutLogger("index_daily_repair")
    repair_rows, fetch_metadata = _fetch_index_daily_rows_for_codes(
        tushare=tushare,
        requested_ts_codes=requested_ts_codes,
        source_date_to_partition_key=source_date_to_partition_key,
        fields=INDEX_DAILY_RAW_COLUMNS,
        limit=TUSHARE_INDEX_DAILY_PAGE_LIMIT,
        log=log,
    )
    if not repair_rows:
        raise RuntimeError(
            "Tushare index_daily returned 0 rows for requested ts_codes and date range."
        )

    repair_rows_by_partition_key = _group_repair_rows_by_partition_key(
        repair_rows=repair_rows,
        source_date_to_partition_key=source_date_to_partition_key,
    )
    affected_partition_keys = sorted(repair_rows_by_partition_key)
    raw_partition_metadata = _merge_index_daily_repair_rows_into_raw_partitions(
        lake_root_path=lake_root_path,
        duckdb=duckdb,
        repair_rows_by_partition_key=repair_rows_by_partition_key,
        requested_ts_codes=requested_ts_codes,
        log=log,
    )
    silver_partition_metadata = materialize_silver_index_daily_partitions(
        lake_root_path=lake_root_path,
        duckdb=duckdb,
        partition_keys=affected_partition_keys,
        log=log,
    )
    still_missing_trade_dates_by_code = _still_missing_trade_dates_by_code(
        requested_ts_codes=requested_ts_codes,
        target_trade_dates=target_trade_dates,
        repair_rows=repair_rows,
        source_date_to_partition_key=source_date_to_partition_key,
    )

    for partition_key in affected_partition_keys:
        raw_path = raw_index_daily_path(lake_root_path, partition_key)
        context.log_event(
            dg.AssetMaterialization(
                asset_key=RAW_INDEX_DAILY_ASSET_KEY,
                partition=partition_key,
                metadata={
                    **raw_partition_metadata[partition_key],
                    "layer": "raw",
                    "source_api": "index_daily",
                    "source_method": TUSHARE_API_SOURCE_METHOD,
                    "path": str(raw_path),
                    "columns": list(INDEX_DAILY_RAW_COLUMNS),
                    "limit": fetch_metadata["limit"],
                    "request_count": fetch_metadata["request_count"],
                    "page_count": fetch_metadata["page_count"],
                    "requested_ts_codes": requested_ts_codes,
                    "repair_run_id": context.run_id,
                },
            )
        )
        context.log_event(
            dg.AssetMaterialization(
                asset_key=SILVER_INDEX_DAILY_ASSET_KEY,
                partition=partition_key,
                metadata={
                    **silver_partition_metadata[partition_key],
                    "layer": "silver",
                    "data_contract": "active_index_daily",
                    "requested_ts_codes": requested_ts_codes,
                    "repair_run_id": context.run_id,
                },
            )
        )

    inserted_row_count = sum(
        item["inserted_row_count"] for item in raw_partition_metadata.values()
    )
    replaced_row_count = sum(
        item["replaced_row_count"] for item in raw_partition_metadata.values()
    )
    output_metadata = {
        **plan_metadata,
        **fetch_metadata,
        "returned_row_count": fetch_metadata["row_count"],
        "inserted_row_count": inserted_row_count,
        "replaced_row_count": replaced_row_count,
        "affected_partition_keys": affected_partition_keys,
        "affected_partition_count": len(affected_partition_keys),
        "raw_partition_metadata": raw_partition_metadata,
        "silver_partition_metadata": silver_partition_metadata,
        "still_missing_trade_dates_by_code": still_missing_trade_dates_by_code,
        "materialized": True,
    }
    context.add_output_metadata(output_metadata)
    return output_metadata


@dg.op(required_resource_keys={"lake_root", "duckdb"})
def evaluate_index_daily_repair_by_codes_checks(
    context: dg.OpExecutionContext,
    repair_summary: dict[str, Any],
) -> None:
    if not repair_summary.get("materialized"):
        context.log.info("index_daily repair dry run skipped asset check evaluations.")
        return

    lake_root: LakeRootResource = context.resources.lake_root
    duckdb: DuckDBResource = context.resources.duckdb
    failed_blocking_checks: list[str] = []
    affected_partition_keys = tuple(str(value) for value in repair_summary["affected_partition_keys"])

    for partition_key in affected_partition_keys:
        target_materialization_by_asset = {
            RAW_INDEX_DAILY_ASSET_KEY: _latest_target_materialization_data(
                context,
                asset_key=RAW_INDEX_DAILY_ASSET_KEY,
                partition_key=partition_key,
            ),
            SILVER_INDEX_DAILY_ASSET_KEY: _latest_target_materialization_data(
                context,
                asset_key=SILVER_INDEX_DAILY_ASSET_KEY,
                partition_key=partition_key,
            ),
        }
        for check_evaluator in INDEX_DAILY_HISTORY_BACKFILL_CHECK_EVALUATORS:
            result = check_evaluator.evaluate((partition_key,), lake_root.root(), duckdb)
            context.log_event(
                dg.AssetCheckEvaluation(
                    asset_key=check_evaluator.asset_key,
                    check_name=check_evaluator.check_name,
                    passed=bool(result.passed),
                    metadata=result.metadata,
                    target_materialization_data=target_materialization_by_asset[
                        check_evaluator.asset_key
                    ],
                    severity=result.severity,
                    blocking=check_evaluator.blocking,
                    partition=partition_key,
                )
            )
            if check_evaluator.blocking and not result.passed:
                failed_blocking_checks.append(f"{check_evaluator.check_name}[{partition_key}]")

    if failed_blocking_checks:
        raise RuntimeError(
            "index_daily repair blocking checks failed: "
            f"{failed_blocking_checks}"
        )


def _normalize_requested_ts_codes(ts_codes: list[str]) -> list[str]:
    normalized_ts_codes = [str(ts_code).strip() for ts_code in ts_codes]
    empty_positions = [
        position for position, ts_code in enumerate(normalized_ts_codes, start=1) if not ts_code
    ]
    if empty_positions:
        raise ValueError(f"index_daily repair ts_codes contain empty values: {empty_positions}")
    if not normalized_ts_codes:
        raise ValueError("index_daily repair ts_codes must not be empty.")

    seen_codes: set[str] = set()
    duplicate_codes: list[str] = []
    for ts_code in normalized_ts_codes:
        if ts_code in seen_codes and ts_code not in duplicate_codes:
            duplicate_codes.append(ts_code)
        seen_codes.add(ts_code)
    if duplicate_codes:
        raise ValueError(f"index_daily repair ts_codes must be unique: {duplicate_codes}")
    return normalized_ts_codes


def _parse_iso_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format: {value}") from exc


def _load_sse_open_trade_dates(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    start_date: date,
    end_date: date,
) -> list[str]:
    calendar_path = silver_trade_calendar_path(lake_root_path)
    if not calendar_path.exists():
        raise FileNotFoundError(f"Missing silver trade calendar file: {calendar_path}")

    with duckdb.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT strftime(trade_date, '%Y-%m-%d') AS trade_date
            FROM {read_parquet(calendar_path, hive_partitioning=False)}
            WHERE exchange = 'SSE'
              AND is_open = true
              AND trade_date BETWEEN DATE {duckdb_string(start_date.isoformat())}
                                 AND DATE {duckdb_string(end_date.isoformat())}
            ORDER BY trade_date
            """
        ).fetchall()
    return [str(row[0]) for row in rows]


def _ensure_index_trade_days_registered(
    context: dg.OpExecutionContext,
    target_trade_dates: list[str],
) -> None:
    registered_partition_keys = set(
        context.instance.get_dynamic_partitions(cn_a_index_trade_days.name)
    )
    missing_partition_keys = [
        partition_key
        for partition_key in target_trade_dates
        if partition_key not in registered_partition_keys
    ]
    if missing_partition_keys:
        raise RuntimeError(
            "index_daily repair target trade dates are not registered in "
            f"{cn_a_index_trade_days.name}: {missing_partition_keys}"
        )


def _load_active_index_entries(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> list[dict[str, str]]:
    active_pool_path = silver_index_daily_active_pool_path(lake_root_path)
    if not active_pool_path.exists():
        raise FileNotFoundError(f"Missing silver index daily active pool file: {active_pool_path}")

    with duckdb.connect() as connection:
        active_index_entries = load_active_index_entries(connection, active_pool_path)
    if not active_index_entries:
        raise RuntimeError("silver_index_daily_active_pool has no ts_code values.")
    return active_index_entries


def _existing_requested_code_rows(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    target_trade_dates: list[str],
    requested_ts_codes: list[str],
) -> dict[str, Any]:
    raw_missing_paths: list[str] = []
    existing_row_counts: dict[str, int] = {}
    existing_row_samples: list[dict[str, Any]] = []
    requested_codes_sql = ", ".join(duckdb_string(ts_code) for ts_code in requested_ts_codes)

    with duckdb.connect() as connection:
        for partition_key in target_trade_dates:
            raw_path = raw_index_daily_path(lake_root_path, partition_key)
            if not raw_path.exists():
                raw_missing_paths.append(str(raw_path))
                continue

            source_query = read_parquet(raw_path, hive_partitioning=False)
            row_count = int(
                connection.execute(
                    f"""
                    SELECT count(*)
                    FROM {source_query}
                    WHERE ts_code IN ({requested_codes_sql})
                    """
                ).fetchone()[0]
            )
            existing_row_counts[partition_key] = row_count
            if row_count and len(existing_row_samples) < 20:
                rows = connection.execute(
                    f"""
                    SELECT ts_code, trade_date
                    FROM {source_query}
                    WHERE ts_code IN ({requested_codes_sql})
                    ORDER BY ts_code, trade_date
                    LIMIT {20 - len(existing_row_samples)}
                    """
                ).fetchall()
                existing_row_samples.extend(
                    {"ts_code": str(row[0]), "trade_date": str(row[1])}
                    for row in rows
                )

    return {
        "raw_missing_count": len(raw_missing_paths),
        "raw_missing_sample_paths": raw_missing_paths[:20],
        "existing_row_count": sum(existing_row_counts.values()),
        "existing_row_counts": existing_row_counts,
        "existing_row_samples": existing_row_samples,
    }


def _fetch_index_daily_rows_for_codes(
    *,
    tushare: TushareResource,
    requested_ts_codes: list[str],
    source_date_to_partition_key: dict[str, str],
    fields: tuple[str, ...],
    limit: int,
    log: DgStdoutLogger,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_dates = set(source_date_to_partition_key)
    start_date = min(source_dates)
    end_date = max(source_dates)
    repair_rows: list[dict[str, Any]] = []
    returned_ts_codes: set[str] = set()
    page_count = 0
    last_request_started_at: float | None = None

    log.stdout(
        "repair_fetch_start",
        codes=len(requested_ts_codes),
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    for index_position, ts_code in enumerate(requested_ts_codes, start=1):
        offset = 0
        code_row_count = 0
        code_page_count = 0
        while True:
            api_params = {
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
                "limit": limit,
                "offset": offset,
            }
            last_request_started_at = _wait_for_next_request_slot(
                last_request_started_at,
                TUSHARE_INDEX_DAILY_MIN_REQUEST_INTERVAL_SECONDS,
            )
            result = tushare.call("index_daily", api_params, fields)
            if result.columns != fields and (result.columns or result.rows):
                raise RuntimeError(
                    f"Tushare index_daily returned columns {list(result.columns)}, "
                    f"expected {list(fields)}."
                )

            page_rows = [
                row
                for row in result.rows
                if str(row.get("ts_code", "")).strip() == ts_code
                and str(row.get("trade_date", "")).strip() in source_dates
            ]
            repair_rows.extend(page_rows)
            if page_rows:
                returned_ts_codes.add(ts_code)
            code_row_count += len(page_rows)
            page_count += 1
            code_page_count += 1
            if len(result.rows) < limit:
                break
            offset += limit

        log.stdout(
            "repair_fetch_progress",
            progress=f"{index_position}/{len(requested_ts_codes)}",
            code=ts_code,
            rows=code_row_count,
            pages=code_page_count,
            total_rows=len(repair_rows),
        )

    return repair_rows, {
        "source_method": TUSHARE_API_SOURCE_METHOD,
        "api_name": "index_daily",
        "params": {
            "code_scope": "requested_ts_codes",
            "start_date": start_date,
            "end_date": end_date,
        },
        "fields": list(fields),
        "limit": limit,
        "page_count": page_count,
        "request_count": page_count,
        "row_count": len(repair_rows),
        "returned_ts_codes": sorted(returned_ts_codes),
        "returned_ts_code_count": len(returned_ts_codes),
        "min_request_interval_seconds": TUSHARE_INDEX_DAILY_MIN_REQUEST_INTERVAL_SECONDS,
    }


def _group_repair_rows_by_partition_key(
    *,
    repair_rows: list[dict[str, Any]],
    source_date_to_partition_key: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    repair_rows_by_partition_key: dict[str, list[dict[str, Any]]] = {}
    for repair_row in repair_rows:
        source_date = str(repair_row.get("trade_date", "")).strip()
        partition_key = source_date_to_partition_key.get(source_date)
        if partition_key is None:
            continue
        repair_rows_by_partition_key.setdefault(partition_key, []).append(repair_row)
    return repair_rows_by_partition_key


def _merge_index_daily_repair_rows_into_raw_partitions(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    repair_rows_by_partition_key: dict[str, list[dict[str, Any]]],
    requested_ts_codes: list[str],
    log: DgStdoutLogger,
) -> dict[str, dict[str, Any]]:
    raw_partition_metadata: dict[str, dict[str, Any]] = {}
    requested_codes_sql = ", ".join(duckdb_string(ts_code) for ts_code in requested_ts_codes)
    field_select_sql = ", ".join(
        f"CAST({_quote_identifier(field)} AS {INDEX_DAILY_RAW_COLUMN_TYPES[field]}) "
        f"AS {_quote_identifier(field)}"
        for field in INDEX_DAILY_RAW_COLUMNS
    )
    column_defs = ", ".join(
        f"{_quote_identifier(field)} {INDEX_DAILY_RAW_COLUMN_TYPES[field]}"
        for field in INDEX_DAILY_RAW_COLUMNS
    )
    placeholders = ", ".join("?" for _ in INDEX_DAILY_RAW_COLUMNS)

    with duckdb.connect() as connection:
        for partition_key, repair_rows in sorted(repair_rows_by_partition_key.items()):
            raw_path = raw_index_daily_path(lake_root_path, partition_key)
            if not raw_path.exists():
                raise FileNotFoundError(f"Missing raw index daily file: {raw_path}")

            source_date = partition_key.replace("-", "")
            invalid_rows = [
                row for row in repair_rows if str(row.get("trade_date", "")).strip() != source_date
            ]
            if invalid_rows:
                raise RuntimeError(
                    "index_daily repair rows contain trade_date outside target partition: "
                    f"{partition_key}"
                )

            connection.execute("DROP TABLE IF EXISTS repair_rows")
            connection.execute(f"CREATE TEMP TABLE repair_rows ({column_defs})")
            values = [
                [_clean_tushare_value(row.get(field)) for field in INDEX_DAILY_RAW_COLUMNS]
                for row in repair_rows
            ]
            connection.executemany(f"INSERT INTO repair_rows VALUES ({placeholders})", values)

            existing_source_query = read_parquet(raw_path, hive_partitioning=False)
            existing_row_count = int(
                connection.execute(f"SELECT count(*) FROM {existing_source_query}").fetchone()[0]
            )
            replaced_row_count = int(
                connection.execute(
                    f"""
                    SELECT count(*)
                    FROM {existing_source_query}
                    WHERE ts_code IN ({requested_codes_sql})
                    """
                ).fetchone()[0]
            )
            combined_query = f"""
            WITH existing_kept AS (
              SELECT {field_select_sql}
              FROM {existing_source_query}
              WHERE ts_code NOT IN ({requested_codes_sql})
            ),
            repair_casted AS (
              SELECT {field_select_sql}
              FROM repair_rows
            )
            SELECT *
            FROM existing_kept
            UNION ALL
            SELECT *
            FROM repair_casted
            """
            duplicate_key_count = int(
                connection.execute(
                    f"""
                    SELECT count(*)
                    FROM (
                      SELECT ts_code, trade_date
                      FROM ({combined_query}) combined_rows
                      GROUP BY ts_code, trade_date
                      HAVING count(*) > 1
                    ) duplicate_keys
                    """
                ).fetchone()[0]
            )
            if duplicate_key_count:
                raise RuntimeError(
                    "index_daily repair would create duplicate raw keys for "
                    f"{partition_key}: {duplicate_key_count}"
                )

            final_row_count = int(
                connection.execute(
                    f"SELECT count(*) FROM ({combined_query}) combined_rows"
                ).fetchone()[0]
            )
            temporary_path = raw_path.with_name(f"{raw_path.name}.tmp")
            if temporary_path.exists():
                temporary_path.unlink()

            connection.execute(
                copy_query_to_parquet(
                    f"""
                    SELECT *
                    FROM ({combined_query}) combined_rows
                    ORDER BY ts_code
                    """,
                    temporary_path,
                )
            )
            os.replace(temporary_path, raw_path)
            raw_partition_metadata[partition_key] = {
                "path": str(raw_path),
                "previous_row_count": existing_row_count,
                "replaced_row_count": replaced_row_count,
                "inserted_row_count": len(repair_rows),
                "final_row_count": final_row_count,
                "requested_ts_codes": requested_ts_codes,
            }
            log.stdout(
                "repair_raw_partition_written",
                partition_key=partition_key,
                replaced_rows=replaced_row_count,
                inserted_rows=len(repair_rows),
                final_rows=final_row_count,
                path=raw_path,
            )

    return raw_partition_metadata


def _still_missing_trade_dates_by_code(
    *,
    requested_ts_codes: list[str],
    target_trade_dates: list[str],
    repair_rows: list[dict[str, Any]],
    source_date_to_partition_key: dict[str, str],
) -> dict[str, list[str]]:
    returned_partition_keys_by_code = {ts_code: set() for ts_code in requested_ts_codes}
    for repair_row in repair_rows:
        ts_code = str(repair_row.get("ts_code", "")).strip()
        source_date = str(repair_row.get("trade_date", "")).strip()
        partition_key = source_date_to_partition_key.get(source_date)
        if ts_code in returned_partition_keys_by_code and partition_key:
            returned_partition_keys_by_code[ts_code].add(partition_key)

    return {
        ts_code: [
            partition_key
            for partition_key in target_trade_dates
            if partition_key not in returned_partition_keys_by_code[ts_code]
        ]
        for ts_code in requested_ts_codes
    }


def _latest_target_materialization_data(
    context: dg.OpExecutionContext,
    *,
    asset_key: dg.AssetKey,
    partition_key: str,
) -> AssetCheckEvaluationTargetMaterializationData:
    records = context.instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=asset_key, asset_partitions=[partition_key]),
        limit=1,
    ).records
    if not records:
        raise RuntimeError(
            f"Missing materialization record for {asset_key.to_user_string()}[{partition_key}]."
        )

    latest_record = records[0]
    return AssetCheckEvaluationTargetMaterializationData(
        storage_id=latest_record.storage_id,
        run_id=latest_record.run_id,
        timestamp=latest_record.timestamp,
    )


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) + chr(34))}"'


def _clean_tushare_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except TypeError:
        return value
    return value


def _wait_for_next_request_slot(
    last_request_started_at: float | None,
    min_interval_seconds: float,
) -> float:
    now = time.monotonic()
    if last_request_started_at is None:
        return now

    elapsed = now - last_request_started_at
    remaining = min_interval_seconds - elapsed
    if remaining > 0:
        time.sleep(remaining)
    return time.monotonic()
