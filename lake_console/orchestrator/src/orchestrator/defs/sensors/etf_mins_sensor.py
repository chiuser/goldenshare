"""Stopped-by-default daily update sensors for ETF minute Raw and Silver."""

from __future__ import annotations

from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.etf_basic_readiness import (
    select_latest_etf_basic_snapshot_reference,
)
from orchestrator.defs.asset_guards.etf_mins_lake_readiness import (
    batch_etf_mins_raw_lake_readiness,
    batch_etf_mins_silver_lake_readiness,
    load_etf_mins_raw_materialization_evidence_batch,
)
from orchestrator.defs.asset_guards.etf_mins_prod_readiness import (
    etf_mins_prod_source_ready_for_trade_date,
)
from orchestrator.defs.assets.etf_mins import (
    RAW_ETF_MINS_ASSETS,
    revalidate_etf_mins_basic_reference,
)
from orchestrator.defs.jobs.etf_mins_update import (
    raw_etf_mins_update_job,
    silver_etf_mins_update_job,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_HISTORICAL_PROTECTION_CUTOFF,
    ETF_MINS_SENSOR_WINDOW_LIMIT,
    ETF_MINS_SOURCE_FREQS,
    build_etf_mins_raw_run_config,
    etf_sensor_window_is_open,
    normalize_etf_sensor_evaluated_at,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE

_RAW_ASSET_KEYS_BY_SOURCE_FREQ = {
    source_freq: asset.key
    for source_freq, asset in zip(
        ETF_MINS_SOURCE_FREQS,
        RAW_ETF_MINS_ASSETS,
        strict=True,
    )
}


def _cursor(
    *,
    evaluated_at: datetime,
    sensor_name: str,
    decision: SensorCursorDecision,
    target_date: str | None,
    reason_code: str,
    lineage_query_count: int = 0,
    raw_elapsed_ms: int | None = None,
    silver_elapsed_ms: int | None = None,
) -> str:
    selected = decision is SensorCursorDecision.REQUEST_RUNS
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_date,
        selected_count=1 if selected else 0,
        blocked_count=0 if selected else (1 if target_date else 0),
        sample_keys=(target_date,) if selected and target_date else (),
        details={
            "summary": f"ETF minute sensor decision: {reason_code}",
            "next_action": (
                "run the selected ETF minute partition"
                if selected
                else "wait for or repair the blocking condition"
            ),
            "sensor_name": sensor_name,
            "reason_code": reason_code,
            "window_limit": ETF_MINS_SENSOR_WINDOW_LIMIT,
            "lineage_query_count": lineage_query_count,
            "raw_elapsed_ms": raw_elapsed_ms,
            "silver_elapsed_ms": silver_elapsed_ms,
        },
    )


def _skip(
    *,
    evaluated_at: datetime,
    sensor_name: str,
    target_date: str | None,
    reason_code: str,
    message: str,
    lineage_query_count: int = 0,
    raw_elapsed_ms: int | None = None,
    silver_elapsed_ms: int | None = None,
) -> dg.SensorResult:
    return dg.SensorResult(
        skip_reason=message,
        cursor=_cursor(
            evaluated_at=evaluated_at,
            sensor_name=sensor_name,
            decision=SensorCursorDecision.SKIP,
            target_date=target_date,
            reason_code=reason_code,
            lineage_query_count=lineage_query_count,
            raw_elapsed_ms=raw_elapsed_ms,
            silver_elapsed_ms=silver_elapsed_ms,
        ),
    )


def _load_window_and_lineage(context, *, connection, evaluated_at):  # type: ignore[no-untyped-def]
    lake_root = context.resources.lake_root
    lake_root.ensure_available_for_run()
    expected_window = load_expected_trade_date_window(
        connection,
        silver_trade_calendar_path(lake_root.root()),
        evaluated_at=evaluated_at,
        min_trade_date=ETF_MINS_HISTORICAL_PROTECTION_CUTOFF.isoformat(),
        same_day_register_start=None,
        window_limit=ETF_MINS_SENSOR_WINDOW_LIMIT,
    )
    registered = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_etf_mins_trade_days.name))
    )
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered,
    )
    lineage = load_etf_mins_raw_materialization_evidence_batch(
        instance=context.instance,
        lake_root=lake_root.root(),
        asset_keys_by_source_freq=_RAW_ASSET_KEYS_BY_SOURCE_FREQ,
        partition_keys=expected_window.expected_trade_dates,
    )
    return expected_window, registered, gap_status, lineage


def evaluate_raw_etf_mins_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime | None = None,
) -> dg.SensorResult:
    sensor_name = "raw_etf_mins_update_job_sensor"
    now = normalize_etf_sensor_evaluated_at(
        evaluated_at or datetime.now(CN_A_SENSOR_TIMEZONE)
    )
    if not etf_sensor_window_is_open(now):
        return _skip(
            evaluated_at=now,
            sensor_name=sensor_name,
            target_date=None,
            reason_code="outside_operating_window",
            message="ETF 自动更新等待上海时间 21:00 运行窗口。",
        )
    try:
        with context.resources.duckdb.connect() as connection:
            expected_window, registered, gap_status, lineage = (
                _load_window_and_lineage(
                    context,
                    connection=connection,
                    evaluated_at=now,
                )
            )
            if not gap_status.ready:
                return _skip(
                    evaluated_at=now,
                    sensor_name=sensor_name,
                    target_date=gap_status.first_missing_registered_date,
                    reason_code="etf_mins_partition_not_registered",
                    message="ETF 分钟等待最早缺失的交易日分区注册。",
                    lineage_query_count=lineage.materialization_query_count,
                )
            raw_batch = batch_etf_mins_raw_lake_readiness(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
                lineage=lineage,
            )
        selection = select_first_not_ready_trade_date(
            expected_trade_dates=expected_window.expected_trade_dates,
            readiness=raw_batch,
        )
        target_date = selection.first_not_ready_trade_date
        if selection.selected_trade_date is None:
            if selection.blocked_reason == "materialized_check_failed":
                return _skip(
                    evaluated_at=now,
                    sensor_name=sensor_name,
                    target_date=target_date,
                    reason_code="etf_mins_existing_file_check_failed",
                    message="ETF 分钟 Raw 已有文件但检查失败，拒绝自动覆盖。",
                    lineage_query_count=lineage.materialization_query_count,
                    raw_elapsed_ms=raw_batch.elapsed_ms,
                )
            return _skip(
                evaluated_at=now,
                sensor_name=sensor_name,
                target_date=None,
                reason_code="all_ready",
                message="最近 10 个 ETF 分钟 Raw 交易日均已 ready。",
                lineage_query_count=lineage.materialization_query_count,
                raw_elapsed_ms=raw_batch.elapsed_ms,
            )
        target_date = selection.selected_trade_date
        basic_reference = select_latest_etf_basic_snapshot_reference(
            instance=context.instance,
            lake_root_path=context.resources.lake_root.root(),
            duckdb_resource=context.resources.duckdb,
            eligibility_as_of=now.date(),
            required_freshness_date=now.date(),
        )
        basic_reference, requestable_targets = revalidate_etf_mins_basic_reference(
            duckdb=context.resources.duckdb,
            lake_root=context.resources.lake_root.root(),
            basic_reference=basic_reference,
        )
        prod_status = etf_mins_prod_source_ready_for_trade_date(
            prod_postgres=context.resources.prod_postgres,
            trade_date=target_date,
            basic_reference=basic_reference,
            requestable_targets=requestable_targets,
            observed_at=now,
        )
        if not prod_status.ready or prod_status.coverage_reference is None:
            return _skip(
                evaluated_at=now,
                sensor_name=sensor_name,
                target_date=target_date,
                reason_code=prod_status.reason_code,
                message="Prod ETF 分钟五频代码覆盖尚未完整，本次不启动 Raw。",
                lineage_query_count=lineage.materialization_query_count,
                raw_elapsed_ms=raw_batch.elapsed_ms,
            )
        return dg.SensorResult(
            run_requests=[
                build_run_request(
                    run_key=build_asset_update_run_key(
                        subject="raw_etf_mins_update",
                        unit_id=target_date,
                    ),
                    partition_key=target_date,
                    run_config=build_etf_mins_raw_run_config(
                        partition_key=target_date,
                        basic_reference=basic_reference,
                        prod_coverage_reference=prod_status.coverage_reference,
                    ),
                )
            ],
            cursor=_cursor(
                evaluated_at=now,
                sensor_name=sensor_name,
                decision=SensorCursorDecision.REQUEST_RUNS,
                target_date=target_date,
                reason_code="request_run",
                lineage_query_count=lineage.materialization_query_count,
                raw_elapsed_ms=raw_batch.elapsed_ms,
            ),
        )
    except Exception as error:  # noqa: BLE001 - sensors always fail closed.
        return _skip(
            evaluated_at=now,
            sensor_name=sensor_name,
            target_date=None,
            reason_code=f"sensor_error_{type(error).__name__}",
            message="ETF 分钟 Raw sensor 执行失败，已 fail-closed。",
        )


def evaluate_silver_etf_mins_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime | None = None,
) -> dg.SensorResult:
    sensor_name = "silver_etf_mins_update_job_sensor"
    now = normalize_etf_sensor_evaluated_at(
        evaluated_at or datetime.now(CN_A_SENSOR_TIMEZONE)
    )
    if not etf_sensor_window_is_open(now):
        return _skip(
            evaluated_at=now,
            sensor_name=sensor_name,
            target_date=None,
            reason_code="outside_operating_window",
            message="ETF 自动更新等待上海时间 21:00 运行窗口。",
        )
    try:
        with context.resources.duckdb.connect() as connection:
            expected_window, registered, gap_status, lineage = (
                _load_window_and_lineage(
                    context,
                    connection=connection,
                    evaluated_at=now,
                )
            )
            if not gap_status.ready:
                return _skip(
                    evaluated_at=now,
                    sensor_name=sensor_name,
                    target_date=gap_status.first_missing_registered_date,
                    reason_code="etf_mins_partition_not_registered",
                    message="ETF 分钟 Silver 等待最早缺失的交易日分区注册。",
                    lineage_query_count=lineage.materialization_query_count,
                )
            raw_batch = batch_etf_mins_raw_lake_readiness(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
                lineage=lineage,
            )
        with context.resources.duckdb.connect() as connection:
            silver_batch = batch_etf_mins_silver_lake_readiness(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
                raw_lineage=lineage,
            )
        for trade_date in expected_window.expected_trade_dates:
            raw_status = raw_batch.status_for_trade_date(trade_date)
            if not raw_status.ready:
                return _skip(
                    evaluated_at=now,
                    sensor_name=sensor_name,
                    target_date=trade_date,
                    reason_code="etf_mins_raw_not_ready",
                    message="最早日期的 ETF 分钟 Raw 尚未 ready，Silver 不越过。",
                    lineage_query_count=lineage.materialization_query_count,
                    raw_elapsed_ms=raw_batch.elapsed_ms,
                    silver_elapsed_ms=silver_batch.elapsed_ms,
                )
            silver_status = silver_batch.status_for_trade_date(trade_date)
            if silver_status.ready:
                continue
            if silver_status.materialized and not silver_status.checks_passed:
                return _skip(
                    evaluated_at=now,
                    sensor_name=sensor_name,
                    target_date=trade_date,
                    reason_code="etf_mins_existing_file_check_failed",
                    message="ETF 分钟 Silver 已有文件但检查失败，拒绝自动覆盖。",
                    lineage_query_count=lineage.materialization_query_count,
                    raw_elapsed_ms=raw_batch.elapsed_ms,
                    silver_elapsed_ms=silver_batch.elapsed_ms,
                )
            return dg.SensorResult(
                run_requests=[
                    build_run_request(
                        run_key=build_asset_update_run_key(
                            subject="silver_etf_mins_update",
                            unit_id=trade_date,
                        ),
                        partition_key=trade_date,
                    )
                ],
                cursor=_cursor(
                    evaluated_at=now,
                    sensor_name=sensor_name,
                    decision=SensorCursorDecision.REQUEST_RUNS,
                    target_date=trade_date,
                    reason_code="request_run",
                    lineage_query_count=lineage.materialization_query_count,
                    raw_elapsed_ms=raw_batch.elapsed_ms,
                    silver_elapsed_ms=silver_batch.elapsed_ms,
                ),
            )
        return _skip(
            evaluated_at=now,
            sensor_name=sensor_name,
            target_date=None,
            reason_code="all_ready",
            message="最近 10 个 ETF 分钟 Silver 交易日均已 ready。",
            lineage_query_count=lineage.materialization_query_count,
            raw_elapsed_ms=raw_batch.elapsed_ms,
            silver_elapsed_ms=silver_batch.elapsed_ms,
        )
    except Exception as error:  # noqa: BLE001 - sensors always fail closed.
        return _skip(
            evaluated_at=now,
            sensor_name=sensor_name,
            target_date=None,
            reason_code=f"sensor_error_{type(error).__name__}",
            message="ETF 分钟 Silver sensor 执行失败，已 fail-closed。",
        )


@dg.sensor(
    job=raw_etf_mins_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb", "prod_postgres"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description=(
        "上海时间 21:00 后按最早 Raw 缺口、当天 Basic 和一次 Prod 五频覆盖"
        "触发 ETF 分钟 Raw。"
    ),
)
def raw_etf_mins_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_raw_etf_mins_sensor(context)


@dg.sensor(
    job=silver_etf_mins_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description=(
        "上海时间 21:00 后只读本地 Raw/Silver，按最早缺口触发 ETF 分钟 Silver。"
    ),
)
def silver_etf_mins_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_silver_etf_mins_sensor(context)


__all__ = [
    "evaluate_raw_etf_mins_sensor",
    "evaluate_silver_etf_mins_sensor",
    "raw_etf_mins_update_job_sensor",
    "silver_etf_mins_update_job_sensor",
]
