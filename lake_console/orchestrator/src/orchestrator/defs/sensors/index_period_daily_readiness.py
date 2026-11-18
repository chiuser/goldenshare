"""主要指数周期更新的原生交付读取；不执行上游检查或请求源。"""

import dagster as dg
from dagster._core.event_api import PartitionKeyFilter
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.catalog import get_lake_asset_catalog_entry
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import silver_index_daily_path
from orchestrator.defs.run_contracts.index_period import (
    INDEX_MONTHLY,
    INDEX_WEEKLY,
    index_period_codes,
)
from orchestrator.defs.sensors.readiness import (
    SILVER_INDEX_DAILY_BLOCKING_CHECKS,
    AssetReadinessSpec,
)

INDEX_PERIOD_READINESS_SPECS = tuple(
    AssetReadinessSpec(dg.AssetKey(asset), get_lake_asset_catalog_entry(asset).blocking_check_names)
    for asset in (
        "silver_trade_calendar", "silver_index_basic",
        *(asset for period in (INDEX_WEEKLY, INDEX_MONTHLY) for asset in (period.raw_asset, period.silver_asset)),
    )
)
_SPECS_BY_ASSET = {spec.asset_key.to_user_string(): spec for spec in INDEX_PERIOD_READINESS_SPECS}


def _check_matches(evaluation, materialization):
    target = evaluation.target_materialization_data
    return bool(
        evaluation.passed
        and evaluation.blocking
        and evaluation.asset_key == materialization.asset_key
        and evaluation.partition in (None, materialization.partition_key)
        and target is not None
        and target.storage_id == materialization.storage_id
        and target.run_id == materialization.run_id
    )


def latest_index_period_materialization(instance, asset, partition_key=None):
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset),
            asset_partitions=[partition_key] if partition_key is not None else None,
        ),
        limit=1,
    ).records
    return records[0] if records else None


def index_period_native_delivery(instance, asset, partition_key=None):
    """返回同一次读取的物化与检查结论，不再查询第二遍物化。"""
    record = latest_index_period_materialization(instance, asset, partition_key)
    if record is None:
        return None, False
    names = _SPECS_BY_ASSET[asset].blocking_check_names
    keys = tuple(dg.AssetCheckKey(dg.AssetKey(asset), name) for name in names)
    kwargs = (
        {"partition_filter": PartitionKeyFilter(key=partition_key)}
        if partition_key is not None else {}
    )
    checks = instance.event_log_storage.get_latest_asset_check_execution_by_key(keys, **kwargs)
    return record, all(
        key in checks
        and checks[key].status == AssetCheckExecutionRecordStatus.SUCCEEDED
        and checks[key].evaluation is not None
        and checks[key].evaluation.check_name == key.name
        and _check_matches(checks[key].evaluation, record)
        for key in keys
    )


def index_period_daily_readiness(instance, duckdb, root, trade_date):
    """当前生产job一次产出一份日线和四种检查，最多读取四条检查结果。"""
    materialization = latest_index_period_materialization(instance, "silver_index_daily", trade_date)
    if materialization is None:
        return "daily_materialization_missing", ()
    run = instance.get_run_by_id(materialization.run_id)
    if run is None or run.status != dg.DagsterRunStatus.SUCCESS:
        return "daily_run_not_success", ()
    records = instance.get_records_for_run(
        materialization.run_id,
        of_type=dg.DagsterEventType.ASSET_CHECK_EVALUATION,
        limit=len(SILVER_INDEX_DAILY_BLOCKING_CHECKS),
        ascending=False,
    ).records
    checks = {}
    for record in records:
        evaluation = record.event_log_entry.dagster_event.event_specific_data
        checks.setdefault(evaluation.check_name, evaluation)
    if not all(
        name in checks and _check_matches(checks[name], materialization)
        for name in SILVER_INDEX_DAILY_BLOCKING_CHECKS
    ):
        return "daily_checks_not_ready", ()
    path = silver_index_daily_path(root, trade_date)
    if not path.is_file():
        return "daily_file_missing", ()
    codes = index_period_codes()
    with duckdb.connect() as connection:
        present = {
            row[0] for row in connection.execute(
                f"SELECT DISTINCT ts_code FROM {read_parquet(path)} WHERE ts_code IN (SELECT unnest(?::VARCHAR[])) AND trade_date=?::DATE",
                [list(codes), trade_date],
            ).fetchall()
        }
    missing = tuple(code for code in codes if code not in present)
    return ("daily_codes_missing", missing) if missing else ("ready", ())
