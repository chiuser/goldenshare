from datetime import date
from pathlib import Path
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
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_index_trade_days
from orchestrator.defs.paths import (
    raw_index_daily_path,
    raw_index_daily_staging_dir,
    silver_index_daily_active_pool_path,
    silver_index_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource, TushareResource
from orchestrator.defs.tushare_api_io import (
    TUSHARE_INDEX_DAILY_PAGE_LIMIT,
    fetch_tushare_index_daily_to_raw_partitions,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger


RAW_INDEX_DAILY_ASSET_KEY = dg.AssetKey("raw_tushare_index_daily")
SILVER_INDEX_DAILY_ASSET_KEY = dg.AssetKey("silver_index_daily")


class IndexDailyHistoryBackfillConfig(dg.Config):
    start_date: str
    end_date: str
    dry_run: bool = True
    force: bool = False


@dg.op(required_resource_keys={"lake_root", "duckdb", "tushare"})
def materialize_index_daily_history_backfill(
    context: dg.OpExecutionContext,
    config: IndexDailyHistoryBackfillConfig,
) -> dict[str, Any]:
    lake_root: LakeRootResource = context.resources.lake_root
    duckdb: DuckDBResource = context.resources.duckdb
    tushare: TushareResource = context.resources.tushare
    lake_root.ensure_available_for_run()

    start_date = _parse_iso_date(config.start_date, field_name="start_date")
    end_date = _parse_iso_date(config.end_date, field_name="end_date")
    if start_date > end_date:
        raise ValueError("index_daily history backfill requires start_date <= end_date.")

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

    _ensure_dynamic_partitions_registered(context, target_trade_dates)
    active_index_entries = _load_active_index_entries(
        lake_root_path=lake_root_path,
        duckdb=duckdb,
    )
    existing_file_summary = _existing_index_daily_files(lake_root_path, target_trade_dates)
    target_paths = {
        partition_key: raw_index_daily_path(lake_root_path, partition_key)
        for partition_key in target_trade_dates
    }
    plan_metadata = {
        "start_date": config.start_date,
        "end_date": config.end_date,
        "dry_run": config.dry_run,
        "force": config.force,
        "target_trade_dates": target_trade_dates,
        "target_partition_count": len(target_trade_dates),
        "active_pool_count": len(active_index_entries),
        "estimated_request_count": len(active_index_entries),
        "estimated_page_count": len(active_index_entries),
        "limit": TUSHARE_INDEX_DAILY_PAGE_LIMIT,
        "target_paths": {
            partition_key: str(target_paths[partition_key])
            for partition_key in target_trade_dates
        },
        "existing_file_summary": existing_file_summary,
    }

    if config.dry_run:
        context.add_output_metadata(plan_metadata)
        context.log.info("index_daily history backfill dry run completed; no lake files written.")
        return {
            **plan_metadata,
            "raw_metadata": {},
            "silver_partition_metadata": {},
            "materialized": False,
        }

    existing_paths = [
        *existing_file_summary["raw_existing_paths"],
        *existing_file_summary["silver_existing_paths"],
    ]
    if existing_paths and not config.force:
        raise RuntimeError(
            "index_daily history backfill found existing target files. "
            "Set force=true to replace them atomically. Existing files: "
            f"{existing_paths[:20]}"
        )

    log = DgStdoutLogger("index_daily")
    raw_metadata = fetch_tushare_index_daily_to_raw_partitions(
        tushare=tushare,
        duckdb=duckdb,
        active_index_entries=active_index_entries,
        partition_keys=target_trade_dates,
        fields=INDEX_DAILY_RAW_COLUMNS,
        column_types=INDEX_DAILY_RAW_COLUMN_TYPES,
        target_paths=target_paths,
        staging_dir=raw_index_daily_staging_dir(lake_root_path, context.run_id),
        limit=TUSHARE_INDEX_DAILY_PAGE_LIMIT,
        log=log,
    )
    silver_partition_metadata = materialize_silver_index_daily_partitions(
        lake_root_path=lake_root_path,
        duckdb=duckdb,
        partition_keys=target_trade_dates,
        log=log,
    )

    for partition_key in target_trade_dates:
        context.log_event(
            dg.AssetMaterialization(
                asset_key=RAW_INDEX_DAILY_ASSET_KEY,
                partition=partition_key,
                metadata={
                    "layer": "raw",
                    "source_api": "index_daily",
                    "source_method": raw_metadata["source_method"],
                    "path": str(target_paths[partition_key]),
                    "row_count": raw_metadata["partition_row_counts"][partition_key],
                    "columns": list(INDEX_DAILY_RAW_COLUMNS),
                    "limit": raw_metadata["limit"],
                    "active_pool_count": raw_metadata["active_pool_count"],
                    "page_count": raw_metadata["page_count"],
                    "request_count": raw_metadata["request_count"],
                    "written_page_file_count": raw_metadata["written_page_file_count"],
                    "target_trade_dates": target_trade_dates,
                    "history_backfill_run_id": context.run_id,
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
                    "history_backfill_run_id": context.run_id,
                },
            )
        )

    output_metadata = {
        **plan_metadata,
        "raw_metadata": raw_metadata,
        "silver_partition_metadata": silver_partition_metadata,
        "materialized": True,
    }
    context.add_output_metadata(output_metadata)
    return output_metadata


@dg.op(required_resource_keys={"lake_root", "duckdb"})
def evaluate_index_daily_history_backfill_checks(
    context: dg.OpExecutionContext,
    backfill_summary: dict[str, Any],
) -> None:
    if not backfill_summary.get("materialized"):
        context.log.info("index_daily history backfill dry run skipped asset check evaluations.")
        return

    lake_root: LakeRootResource = context.resources.lake_root
    duckdb: DuckDBResource = context.resources.duckdb
    failed_blocking_checks: list[str] = []
    target_trade_dates = tuple(str(value) for value in backfill_summary["target_trade_dates"])

    for partition_key in target_trade_dates:
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
            "index_daily history backfill blocking checks failed: "
            f"{failed_blocking_checks}"
        )


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


def _ensure_dynamic_partitions_registered(
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
            "index_daily history backfill target trade dates are not registered in "
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


def _existing_index_daily_files(
    lake_root_path: Path,
    target_trade_dates: list[str],
) -> dict[str, Any]:
    raw_existing_paths = []
    silver_existing_paths = []
    raw_missing_paths = []
    silver_missing_paths = []
    for partition_key in target_trade_dates:
        raw_path = raw_index_daily_path(lake_root_path, partition_key)
        silver_path = silver_index_daily_path(lake_root_path, partition_key)
        if raw_path.exists():
            raw_existing_paths.append(str(raw_path))
        else:
            raw_missing_paths.append(str(raw_path))
        if silver_path.exists():
            silver_existing_paths.append(str(silver_path))
        else:
            silver_missing_paths.append(str(silver_path))

    return {
        "raw_existing_count": len(raw_existing_paths),
        "silver_existing_count": len(silver_existing_paths),
        "raw_missing_count": len(raw_missing_paths),
        "silver_missing_count": len(silver_missing_paths),
        "raw_existing_paths": raw_existing_paths,
        "silver_existing_paths": silver_existing_paths,
        "raw_missing_sample_paths": raw_missing_paths[:20],
        "silver_missing_sample_paths": silver_missing_paths[:20],
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
