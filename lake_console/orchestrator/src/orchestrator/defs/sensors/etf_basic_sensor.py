"""Stopped-by-default update sensors for immutable ETF Basic snapshots."""

from __future__ import annotations

from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.etf_basic_readiness import (
    EtfBasicReadinessError,
    select_latest_etf_basic_raw_snapshot_reference,
    select_latest_etf_basic_snapshot_reference,
)
from orchestrator.defs.jobs.etf_basic_update import (
    raw_etf_basic_update_job,
    silver_etf_basic_update_job,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.etf_basic import (
    build_etf_basic_silver_run_config,
)
from orchestrator.defs.run_contracts.etf_mins import (
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


def _cursor(
    *,
    evaluated_at: datetime,
    sensor_name: str,
    decision: SensorCursorDecision,
    reason_code: str,
) -> str:
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=evaluated_at.date().isoformat(),
        selected_count=1 if decision is SensorCursorDecision.REQUEST_RUNS else 0,
        blocked_count=0 if decision is SensorCursorDecision.REQUEST_RUNS else 1,
        details={
            "summary": f"ETF Basic sensor decision: {reason_code}",
            "next_action": (
                "run the selected ETF Basic job"
                if decision is SensorCursorDecision.REQUEST_RUNS
                else "wait for or repair the blocking condition"
            ),
            "sensor_name": sensor_name,
            "reason_code": reason_code,
            "required_freshness_date": evaluated_at.date().isoformat(),
        },
    )


def _raw_refresh_allowed(error: EtfBasicReadinessError) -> bool:
    message = str(error)
    return (
        "etf_basic_latest_materialization_missing" in message
        or "etf_basic_raw_observed_at_stale" in message
    )


def _silver_refresh_allowed(error: EtfBasicReadinessError) -> bool:
    message = str(error)
    return any(
        reason in message
        for reason in (
            "etf_basic_latest_materialization_missing: silver_etf_basic",
            "etf_basic_silver_observed_at_stale",
            "etf_basic_latest_layers_not_aligned",
        )
    )


def evaluate_raw_etf_basic_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime | None = None,
) -> dg.SensorResult:
    now = normalize_etf_sensor_evaluated_at(
        evaluated_at or datetime.now(CN_A_SENSOR_TIMEZONE)
    )
    if not etf_sensor_window_is_open(now):
        return dg.SensorResult(
            skip_reason="ETF 自动更新等待上海时间 21:00 运行窗口。",
            cursor=_cursor(
                evaluated_at=now,
                sensor_name="raw_etf_basic_update_job_sensor",
                decision=SensorCursorDecision.SKIP,
                reason_code="outside_operating_window",
            ),
        )
    try:
        context.resources.lake_root.ensure_available_for_run()
        select_latest_etf_basic_raw_snapshot_reference(
            instance=context.instance,
            lake_root_path=context.resources.lake_root.root(),
            duckdb_resource=context.resources.duckdb,
            required_freshness_date=now.date(),
        )
    except EtfBasicReadinessError as error:
        if not _raw_refresh_allowed(error):
            return dg.SensorResult(
                skip_reason="ETF Basic Raw 最新版本或 checks 失败，拒绝自动覆盖。",
                cursor=_cursor(
                    evaluated_at=now,
                    sensor_name="raw_etf_basic_update_job_sensor",
                    decision=SensorCursorDecision.SKIP,
                    reason_code="etf_basic_checks_failed",
                ),
            )
        return dg.SensorResult(
            run_requests=[
                build_run_request(
                    run_key=build_asset_update_run_key(
                        subject="raw_etf_basic_update",
                        unit_id=now.date().isoformat(),
                    )
                )
            ],
            cursor=_cursor(
                evaluated_at=now,
                sensor_name="raw_etf_basic_update_job_sensor",
                decision=SensorCursorDecision.REQUEST_RUNS,
                reason_code="etf_basic_not_fresh",
            ),
        )
    return dg.SensorResult(
        skip_reason="ETF Basic Raw 当天最新版本已经 ready。",
        cursor=_cursor(
            evaluated_at=now,
            sensor_name="raw_etf_basic_update_job_sensor",
            decision=SensorCursorDecision.SKIP,
            reason_code="all_ready",
        ),
    )


def evaluate_silver_etf_basic_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime | None = None,
) -> dg.SensorResult:
    now = normalize_etf_sensor_evaluated_at(
        evaluated_at or datetime.now(CN_A_SENSOR_TIMEZONE)
    )
    if not etf_sensor_window_is_open(now):
        return dg.SensorResult(
            skip_reason="ETF 自动更新等待上海时间 21:00 运行窗口。",
            cursor=_cursor(
                evaluated_at=now,
                sensor_name="silver_etf_basic_update_job_sensor",
                decision=SensorCursorDecision.SKIP,
                reason_code="outside_operating_window",
            ),
        )
    context.resources.lake_root.ensure_available_for_run()
    try:
        raw_reference = select_latest_etf_basic_raw_snapshot_reference(
            instance=context.instance,
            lake_root_path=context.resources.lake_root.root(),
            duckdb_resource=context.resources.duckdb,
            required_freshness_date=now.date(),
        )
    except EtfBasicReadinessError:
        return dg.SensorResult(
            skip_reason="ETF Basic Silver 等待当天 Raw 及其 checks ready。",
            cursor=_cursor(
                evaluated_at=now,
                sensor_name="silver_etf_basic_update_job_sensor",
                decision=SensorCursorDecision.SKIP,
                reason_code="etf_basic_raw_not_ready",
            ),
        )
    try:
        select_latest_etf_basic_snapshot_reference(
            instance=context.instance,
            lake_root_path=context.resources.lake_root.root(),
            duckdb_resource=context.resources.duckdb,
            eligibility_as_of=now.date(),
            required_freshness_date=now.date(),
        )
    except EtfBasicReadinessError as error:
        if not _silver_refresh_allowed(error):
            return dg.SensorResult(
                skip_reason="ETF Basic Silver 最新版本或 checks 失败，拒绝自动覆盖。",
                cursor=_cursor(
                    evaluated_at=now,
                    sensor_name="silver_etf_basic_update_job_sensor",
                    decision=SensorCursorDecision.SKIP,
                    reason_code="etf_basic_checks_failed",
                ),
            )
        return dg.SensorResult(
            run_requests=[
                build_run_request(
                    run_key=build_asset_update_run_key(
                        subject="silver_etf_basic_update",
                        unit_id=(
                            f"{now.date().isoformat()}:"
                            f"{raw_reference.raw_snapshot_hash[:12]}"
                        ),
                    ),
                    run_config=build_etf_basic_silver_run_config(
                        raw_snapshot_reference=raw_reference
                    ),
                )
            ],
            cursor=_cursor(
                evaluated_at=now,
                sensor_name="silver_etf_basic_update_job_sensor",
                decision=SensorCursorDecision.REQUEST_RUNS,
                reason_code="silver_etf_basic_missing_or_stale",
            ),
        )
    return dg.SensorResult(
        skip_reason="ETF Basic Silver 当天最新版本已经 ready。",
        cursor=_cursor(
            evaluated_at=now,
            sensor_name="silver_etf_basic_update_job_sensor",
            decision=SensorCursorDecision.SKIP,
            reason_code="all_ready",
        ),
    )


@dg.sensor(
    job=raw_etf_basic_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.BASIC_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description=(
        "上海时间 21:00 后检查当天 ETF Basic Raw；缺失或过期时触发，"
        "失败版本不自动覆盖。"
    ),
)
def raw_etf_basic_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_raw_etf_basic_sensor(context)


@dg.sensor(
    job=silver_etf_basic_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.BASIC_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description=(
        "上海时间 21:00 后检查当天 ETF Basic；Raw ready 且 Silver 缺失时触发，"
        "失败版本不回退。"
    ),
)
def silver_etf_basic_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_silver_etf_basic_sensor(context)


__all__ = [
    "evaluate_raw_etf_basic_sensor",
    "evaluate_silver_etf_basic_sensor",
    "raw_etf_basic_update_job_sensor",
    "silver_etf_basic_update_job_sensor",
]
