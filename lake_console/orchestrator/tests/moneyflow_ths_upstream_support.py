"""Owned synthetic lifecycle/final-suspension inputs using verified producer schemas."""

from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs import paths
from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_connection
from orchestrator.defs.sensors import readiness

DEFAULT_CODES = ("000001.SZ", "600000.SH", "000002.SZ")


def _publish(instance, spec, partition=None, *, asof):
    instance.report_runless_asset_event(dg.AssetMaterialization(asset_key=spec.asset_key, partition=partition))
    record = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=spec.asset_key, asset_partitions=[partition] if partition else None), limit=1,
    ).records[0]
    # Explicit synthetic as-of date: logging clocks in sensor tests can be earlier.
    timestamp = datetime.fromisoformat(asof + "T20:00:00").replace(tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    instance.event_log_storage.store_event(record.event_log_entry._replace(timestamp=timestamp))
    record = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=spec.asset_key, asset_partitions=[partition] if partition else None), limit=1,
    ).records[0]
    for name in spec.blocking_check_names:
        evaluation = AssetCheckEvaluation(
            asset_key=spec.asset_key, partition=partition, check_name=name,
            passed=True, blocking=True,
            target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                storage_id=record.storage_id, run_id=record.run_id, timestamp=record.timestamp,
            ),
        )
        instance.report_dagster_event(
            dg.DagsterEvent(event_type_value="ASSET_CHECK_EVALUATION", job_name="isolated_moneyflow_upstream", event_specific_data=evaluation),
            run_id=f"upstream-{record.storage_id}",
        )


def seed_market(instance, lake, staging, days, *, codes=DEFAULT_CODES, suspended=()):
    # Schemas: stock_lifecycle/suspend_d producers and 2026-11-13 verified footers.
    # Codes are a test's declared input, not a production universe inferred from source.
    assert "/Volumes" not in str(lake) and "/Volumes" not in str(staging)
    lifecycle = paths.silver_stock_lifecycle_path(lake)
    lifecycle.parent.mkdir(parents=True, exist_ok=True)
    with moneyflow_candidate_connection(staging) as connection:
        connection.execute("CREATE TABLE life(ts_code VARCHAR,symbol VARCHAR,name VARCHAR,exchange VARCHAR,market VARCHAR,curr_type VARCHAR,is_cny_stock BOOLEAN,list_status VARCHAR,list_date DATE,delist_date DATE)")
        connection.execute(
            "INSERT INTO life SELECT code,substring(code,1,6),'人工样本','SSE','主板','CNY',true,'L',DATE '2010-01-01',NULL FROM unnest(?) t(code)",
            [list(codes)],
        )
        connection.execute("COPY life TO ? (FORMAT PARQUET)", [str(lifecycle)])
        connection.execute("CREATE TABLE susp(ts_code VARCHAR,trade_date DATE,suspend_timing VARCHAR,suspend_type VARCHAR)")
        for day in days:
            connection.execute("DELETE FROM susp")  # Owned temporary relation only.
            connection.execute("INSERT INTO susp SELECT code,CAST(? AS DATE),NULL,'S' FROM unnest(?) t(code)", [day, list(suspended)])
            target = paths.silver_stock_suspend_daily_path(lake, day)
            target.parent.mkdir(parents=True, exist_ok=True)
            connection.execute("COPY susp TO ? (FORMAT PARQUET)", [str(target)])
    _publish(instance, readiness.SILVER_STOCK_LIFECYCLE_READINESS_SPEC, asof=max(days))
    spec = readiness.AssetReadinessSpec(readiness.SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY, readiness.SILVER_SUSPEND_D_CHECKS)
    for day in days:
        _publish(instance, spec, day, asof=day)
