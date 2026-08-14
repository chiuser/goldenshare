"""Fail-closed daily sensors for major-index nine-turn assets."""

from __future__ import annotations

from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.major_index_nineturn import (
    batch_gold_major_index_nineturn_readiness,
)
from orchestrator.defs.jobs.major_index_nineturn_update import (
    gold_major_index_daily_nineturn_update_job,
    gold_major_index_mins_nineturn_update_job,
)
from orchestrator.defs.partitions import (
    cn_a_index_trade_days,
    cn_major_index_mins_trade_days,
)
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursor_payloads import build_cursor_details
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_GOLD_ASSET_KEYS,
    MAJOR_INDEX_MINS_GOLD_CHECKS,
    MAJOR_INDEX_MINS_HISTORY_START_DATE,
)
from orchestrator.defs.run_contracts.major_index_nineturn import (
    MAJOR_INDEX_NINETURN_DAILY_JOB_NAME,
    MAJOR_INDEX_NINETURN_DAILY_SENSOR_NAME,
    MAJOR_INDEX_NINETURN_MINUTE_FREQS,
    MAJOR_INDEX_NINETURN_MINUTE_JOB_NAME,
    MAJOR_INDEX_NINETURN_MINUTE_SENSOR_NAME,
    MAJOR_INDEX_NINETURN_SENSOR_WINDOW_DAILY,
    MAJOR_INDEX_NINETURN_SENSOR_WINDOW_MINUTE,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    AssetReadinessSpec,
    gold_market_major_indices_daily_ready_for_trade_date,
    partition_dataset_readiness_status_from_latest_checks,
)

_MINUTE_UPSTREAM_SPECS = tuple(
    AssetReadinessSpec(dg.AssetKey(asset_key), (check_name,))
    for asset_key, check_name in zip(
        MAJOR_INDEX_MINS_GOLD_ASSET_KEYS[1:],
        MAJOR_INDEX_MINS_GOLD_CHECKS[1:],
        strict=True,
    )
)


def _cursor(
    *,
    sensor_name: str,
    job_name: str,
    partition_set: str,
    evaluated_at: datetime,
    target_date: str | None,
    reason_code: str,
    request_run: bool,
) -> str:
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if request_run
            else SensorCursorDecision.SKIP
        ),
        target_date=target_date,
        selected_count=1 if request_run else 0,
        blocked_count=0 if request_run or target_date is None else 1,
        sample_keys=(target_date,) if target_date else (),
        details=build_cursor_details(
            sensor_name=sensor_name,
            job_name=job_name,
            asset_family="major_index_nineturn",
            partition_set=partition_set,
            reason_code=reason_code,
            blocked_component="none" if request_run else reason_code,
            summary=f"major-index nine-turn sensor: {reason_code}",
            next_action=(
                "run one partition" if request_run else "wait for the gate to clear"
            ),
            evidence={
                "minute_frequencies": list(MAJOR_INDEX_NINETURN_MINUTE_FREQS),
                "max_run_requests_per_tick": 1,
            },
        ),
    )


def _evaluate(context: dg.SensorEvaluationContext, *, minute: bool) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    sensor_name = (
        MAJOR_INDEX_NINETURN_MINUTE_SENSOR_NAME
        if minute
        else MAJOR_INDEX_NINETURN_DAILY_SENSOR_NAME
    )
    job_name = (
        MAJOR_INDEX_NINETURN_MINUTE_JOB_NAME
        if minute
        else MAJOR_INDEX_NINETURN_DAILY_JOB_NAME
    )
    partitions_def = cn_major_index_mins_trade_days if minute else cn_a_index_trade_days
    window_limit = (
        MAJOR_INDEX_NINETURN_SENSOR_WINDOW_MINUTE
        if minute
        else MAJOR_INDEX_NINETURN_SENSOR_WINDOW_DAILY
    )
    try:
        context.resources.lake_root.ensure_available_for_run()
        with context.resources.duckdb.connect() as connection:
            window = load_expected_trade_date_window(
                connection,
                silver_trade_calendar_path(context.resources.lake_root.root()),
                evaluated_at=evaluated_at,
                min_trade_date=MAJOR_INDEX_MINS_HISTORY_START_DATE if minute else None,
                same_day_register_start=None,
                window_limit=window_limit,
            )
            registered = tuple(
                sorted(context.instance.get_dynamic_partitions(partitions_def.name))
            )
            gap = build_registered_gap_status(
                expected_trade_dates=window.expected_trade_dates,
                registered_trade_dates=registered,
            )
            if not gap.ready:
                target = gap.first_missing_registered_date
                return dg.SensorResult(
                    skip_reason="等待主要指数九转交易日分区注册。",
                    cursor=_cursor(
                        sensor_name=sensor_name,
                        job_name=job_name,
                        partition_set=partitions_def.name,
                        evaluated_at=evaluated_at,
                        target_date=target,
                        reason_code="missing_registered_partition",
                        request_run=False,
                    ),
                )
            target_batch = batch_gold_major_index_nineturn_readiness(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=window.expected_trade_dates,
                minute=minute,
            )
        selection = select_first_not_ready_trade_date(
            expected_trade_dates=window.expected_trade_dates,
            readiness=target_batch,
        )
        target = selection.first_not_ready_trade_date
        if selection.selected_trade_date is None:
            reason = (
                "target_integrity_failed"
                if selection.blocked_reason == "materialized_check_failed"
                else "all_ready"
            )
            return dg.SensorResult(
                skip_reason=(
                    "目标九转文件存在但完整性失败，拒绝自动覆盖。"
                    if reason == "target_integrity_failed"
                    else "最近窗口的主要指数九转均已 ready。"
                ),
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    partition_set=partitions_def.name,
                    evaluated_at=evaluated_at,
                    target_date=target,
                    reason_code=reason,
                    request_run=False,
                ),
            )
        target = selection.selected_trade_date
        upstream = (
            partition_dataset_readiness_status_from_latest_checks(
                context.instance,
                _MINUTE_UPSTREAM_SPECS,
                partition_key=target,
            )
            if minute
            else gold_market_major_indices_daily_ready_for_trade_date(
                context.instance, target
            )
        )
        if not upstream.ready:
            return dg.SensorResult(
                skip_reason="同分区主要指数 Gold 上游或 blocking check 尚未就绪。",
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    partition_set=partitions_def.name,
                    evaluated_at=evaluated_at,
                    target_date=target,
                    reason_code="upstream_not_ready",
                    request_run=False,
                ),
            )
        previous = next(
            (value for value in reversed(registered) if value < target), None
        )
        if previous is not None:
            with context.resources.duckdb.connect() as connection:
                previous_batch = batch_gold_major_index_nineturn_readiness(
                    connection=connection,
                    lake_root=context.resources.lake_root.root(),
                    expected_trade_dates=(previous,),
                    minute=minute,
                )
            if not previous_batch.status_for_trade_date(previous).ready:
                return dg.SensorResult(
                    skip_reason="前一主要指数九转分区未就绪，拒绝断链计算。",
                    cursor=_cursor(
                        sensor_name=sensor_name,
                        job_name=job_name,
                        partition_set=partitions_def.name,
                        evaluated_at=evaluated_at,
                        target_date=target,
                        reason_code="previous_partition_not_ready",
                        request_run=False,
                    ),
                )
        return dg.SensorResult(
            run_requests=[
                build_run_request(
                    run_key=build_asset_update_run_key(
                        subject=job_name.removesuffix("_job"), unit_id=target
                    ),
                    partition_key=target,
                )
            ],
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                partition_set=partitions_def.name,
                evaluated_at=evaluated_at,
                target_date=target,
                reason_code="request_run",
                request_run=True,
            ),
        )
    except Exception as error:  # noqa: BLE001 - sensors fail closed.
        return dg.SensorResult(
            skip_reason="主要指数九转 sensor 异常，已 fail-closed。",
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                partition_set=partitions_def.name,
                evaluated_at=evaluated_at,
                target_date=None,
                reason_code=f"sensor_error_{type(error).__name__}",
                request_run=False,
            ),
        )


@dg.sensor(
    name=MAJOR_INDEX_NINETURN_DAILY_SENSOR_NAME,
    job=gold_major_index_daily_nineturn_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def gold_major_index_daily_nineturn_update_job_sensor(
    context: dg.SensorEvaluationContext,
):
    return _evaluate(context, minute=False)


@dg.sensor(
    name=MAJOR_INDEX_NINETURN_MINUTE_SENSOR_NAME,
    job=gold_major_index_mins_nineturn_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def gold_major_index_mins_nineturn_update_job_sensor(
    context: dg.SensorEvaluationContext,
):
    return _evaluate(context, minute=True)


__all__ = [
    "gold_major_index_daily_nineturn_update_job_sensor",
    "gold_major_index_mins_nineturn_update_job_sensor",
]
