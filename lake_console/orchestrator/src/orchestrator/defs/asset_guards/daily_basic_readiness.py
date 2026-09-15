"""Bounded current-file and delivery-identity readiness for daily basic."""

from dataclasses import dataclass
from pathlib import Path

import dagster as dg
import duckdb
from dagster._core.event_api import PartitionKeyFilter

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    asset_check_record_evaluation,
    asset_check_record_succeeded,
)
from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_ASSET,
    DAILY_BASIC_CHECKS,
    DAILY_BASIC_WINDOW,
    DailyBasicValidationError,
)
from orchestrator.defs.daily_basic_raw_io import (
    audit_daily_basic_coverage,
    audit_daily_basic_file,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import raw_daily_basic_path, raw_stock_daily_path
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    raw_tushare_stock_daily_ready_for_trade_date,
)

DAILY_BASIC_READINESS_SPEC = AssetReadinessSpec(
    dg.AssetKey(DAILY_BASIC_ASSET), DAILY_BASIC_CHECKS
)


@dataclass(frozen=True)
class DailyBasicReadiness:
    ready: bool
    materialized: bool
    reason: str


def load_daily_basic_input_codes(
    instance, connection, lake_root: Path, trade_date: str
) -> tuple[str, ...]:
    if not raw_tushare_stock_daily_ready_for_trade_date(
        instance, trade_date=trade_date
    ).ready:
        raise DailyBasicValidationError("upstream_not_ready")
    path = raw_stock_daily_path(lake_root, trade_date)
    if not path.is_file():
        raise DailyBasicValidationError("upstream_file_missing")
    relation = read_parquet(path, hive_partitioning=False)
    try:
        count, invalid, values = connection.execute(
            f"SELECT count(*), count(*) FILTER (WHERE ts_code IS NULL OR trim(ts_code)='' OR ts_code!=trim(ts_code) OR trade_date IS NULL OR trade_date!=?), list(DISTINCT ts_code ORDER BY ts_code) FROM {relation}",
            [trade_date.replace("-", "")],
        ).fetchone()
    except duckdb.Error as error:
        raise DailyBasicValidationError("upstream_file_invalid") from error
    if not count or invalid:
        raise DailyBasicValidationError("upstream_invalid_keys")
    codes = tuple(values)
    if len(codes) != count:
        raise DailyBasicValidationError("upstream_duplicate_keys")
    return codes


def daily_basic_materializations(instance, dates):
    if not dates or len(dates) > DAILY_BASIC_WINDOW:
        raise DailyBasicValidationError("invalid_readiness_window")
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(DAILY_BASIC_ASSET), asset_partitions=list(dates)
        ),
        limit=DAILY_BASIC_WINDOW * 10,
    ).records
    latest = {}
    for record in records:
        latest.setdefault(record.partition_key, record)
    if len(records) == DAILY_BASIC_WINDOW * 10 and set(dates) - set(latest):
        raise DailyBasicValidationError("materialization_query_truncated")
    return latest


def delivery_metadata(record) -> dict:
    return {
        key.removeprefix("goldenshare/"): value.value
        for key, value in record.asset_materialization.metadata.items()
        if key.startswith("goldenshare/")
    }


def current_daily_basic_check_records(instance, trade_date):
    return instance.event_log_storage.get_latest_asset_check_execution_by_key(
        [
            dg.AssetCheckKey(DAILY_BASIC_READINESS_SPEC.asset_key, name)
            for name in DAILY_BASIC_READINESS_SPEC.blocking_check_names
        ],
        partition_filter=PartitionKeyFilter(key=trade_date),
    )


def batch_daily_basic_readiness(
    instance, connection, lake_root: Path, trade_dates
) -> dict[str, DailyBasicReadiness]:
    latest = daily_basic_materializations(instance, trade_dates)
    results = {}
    for day in trade_dates:
        record = latest.get(day)
        checks = current_daily_basic_check_records(instance, day)
        if record is None:
            results[day] = DailyBasicReadiness(
                False,
                False,
                "check_without_materialization"
                if any(checks.values())
                else "missing_materialization",
            )
            continue
        reason = "ready"
        for check in checks.values():
            evaluation = asset_check_record_evaluation(check)
            target = getattr(evaluation, "target_materialization_data", None)
            if (
                not asset_check_record_succeeded(check)
                or getattr(target, "storage_id", None) != record.storage_id
            ):
                reason = "check_failed_or_stale"
        if len(checks) != len(DAILY_BASIC_CHECKS):
            reason = "check_missing"
        if reason == "ready":
            path = raw_daily_basic_path(lake_root, day)
            audit = audit_daily_basic_file(connection, path, day)
            try:
                codes = load_daily_basic_input_codes(
                    instance, connection, lake_root, day
                )
                if audit_daily_basic_coverage(
                    path, audit, codes, delivery_metadata(record)
                ):
                    reason = "file_or_delivery_changed"
            except (DailyBasicValidationError, OSError):
                reason = "upstream_not_ready"
        results[day] = DailyBasicReadiness(reason == "ready", True, reason)
    return results
