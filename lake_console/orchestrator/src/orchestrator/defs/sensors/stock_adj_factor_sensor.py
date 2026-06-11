from __future__ import annotations

from datetime import datetime, time

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
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
    RAW_ADJ_FACTOR_ASSET_KEY,
    SILVER_ADJ_FACTOR_ASSET_KEY,
    AssetReadinessStatus,
    DatasetReadinessStatus,
    materialized_partition_keys,
    raw_tushare_adj_factor_ready_for_trade_date,
    status_payload,
    stock_basic_ready_without_freshness,
)


STOCK_ADJ_FACTOR_RUN_START = time(9, 30)


def _latest_registered_trade_date(
    registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> str | None:
    today = evaluated_at.date().isoformat()
    eligible_trade_days = tuple(
        trade_date for trade_date in registered_trade_days if trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _readiness_asset_payload(status: AssetReadinessStatus) -> dict[str, object]:
    return {
        "asset_key": status.asset_key,
        "partition_key": status.partition_key,
        "ready": status.ready,
        "materialized": status.materialized,
        "checks_passed": status.checks_passed,
        "freshness_passed": status.freshness_passed,
        "materialization_storage_id": status.materialization_storage_id,
        "materialization_date": status.materialization_date,
        "missing_check_names": list(status.missing_check_names),
        "failed_check_names": list(status.failed_check_names),
        "reason": status.reason,
    }


def _raw_sensor_cursor(
    *,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    reason: str,
    source_window_started: bool,
) -> str:
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if selected_trade_date
            else SensorCursorDecision.SKIP
        ),
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=0 if selected_trade_date else 1,
        sample_keys=(selected_trade_date or target_trade_date,)
        if selected_trade_date or target_trade_date
        else (),
        details={
            "registered_trade_day_count": registered_trade_day_count,
            "selected_trade_date": selected_trade_date,
            "reason": reason,
            "source_window_started": source_window_started,
        },
    )


def _silver_sensor_cursor(
    *,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    reason: str,
    source_window_started: bool,
    raw_status: AssetReadinessStatus | None = None,
    stock_basic_status: DatasetReadinessStatus | None = None,
) -> str:
    readiness_details: dict[str, object] = {}
    if raw_status is not None:
        readiness_details["raw_tushare_adj_factor"] = _readiness_asset_payload(
            raw_status
        )
    if stock_basic_status is not None:
        readiness_details["stock_basic"] = status_payload(stock_basic_status)

    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if selected_trade_date
            else SensorCursorDecision.SKIP
        ),
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=0 if selected_trade_date else 1,
        sample_keys=(selected_trade_date or target_trade_date,)
        if selected_trade_date or target_trade_date
        else (),
        details={
            "registered_trade_day_count": registered_trade_day_count,
            "selected_trade_date": selected_trade_date,
            "reason": reason,
            "source_window_started": source_window_started,
            "stock_basic_freshness_required": False,
            "readiness_details": readiness_details,
        },
    )


def _raw_run_request_for_trade_date(trade_date: str):
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="raw_adj_factor_update",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


def _silver_run_request_for_trade_date(trade_date: str):
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="silver_adj_factor_update",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


@dg.sensor(
    job_name="raw_adj_factor_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="复权因子 raw 分区缺失时，触发复权因子 raw 更新任务。",
)
def raw_adj_factor_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    source_window_started = evaluated_at.time() >= STOCK_ADJ_FACTOR_RUN_START
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_current_trade_days.name
            )
        )
    )
    target_trade_date = _latest_registered_trade_date(registered_trade_days, evaluated_at)

    if target_trade_date is None:
        reason = "没有注册股票当前交易日分区，无法触发复权因子 raw 更新。"
        cursor = _raw_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=None,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not source_window_started:
        reason = "复权因子日常更新窗口尚未到 09:30，暂不触发 raw 更新。"
        cursor = _raw_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    raw_materialized_keys = materialized_partition_keys(
        context.instance,
        (RAW_ADJ_FACTOR_ASSET_KEY,),
    )
    if target_trade_date in raw_materialized_keys:
        reason = "最新股票当前交易日的复权因子 raw 分区已经生成完成。"
        cursor = _raw_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    reason = "复权因子 raw 分区缺失，提交股票当前交易日 raw 更新。"
    cursor = _raw_sensor_cursor(
        evaluated_at=evaluated_at,
        registered_trade_day_count=len(registered_trade_days),
        target_trade_date=target_trade_date,
        selected_trade_date=target_trade_date,
        reason=reason,
        source_window_started=source_window_started,
    )
    return dg.SensorResult(
        run_requests=[_raw_run_request_for_trade_date(target_trade_date)],
        cursor=cursor,
    )


@dg.sensor(
    job_name="silver_adj_factor_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="复权因子 raw 和股票基础信息 ready 后，触发复权因子 silver-only 更新。",
)
def silver_adj_factor_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    source_window_started = evaluated_at.time() >= STOCK_ADJ_FACTOR_RUN_START
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_current_trade_days.name
            )
        )
    )
    target_trade_date = _latest_registered_trade_date(registered_trade_days, evaluated_at)

    if target_trade_date is None:
        reason = "没有注册股票当前交易日分区，无法触发复权因子 silver 更新。"
        cursor = _silver_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=None,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not source_window_started:
        reason = "复权因子日常更新窗口尚未到 09:30，暂不触发 silver 更新。"
        cursor = _silver_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    silver_materialized_keys = materialized_partition_keys(
        context.instance,
        (SILVER_ADJ_FACTOR_ASSET_KEY,),
    )
    if target_trade_date in silver_materialized_keys:
        reason = (
            "最新股票当前交易日的复权因子 silver 分区已经生成完成，"
            "不自动重跑已 materialized 分区。"
        )
        cursor = _silver_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    raw_status = raw_tushare_adj_factor_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if not raw_status.ready:
        reason = "复权因子 silver 前置 raw readiness 门禁未满足。"
        cursor = _silver_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            raw_status=raw_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    stock_basic_status = stock_basic_ready_without_freshness(context.instance)
    if not stock_basic_status.ready:
        reason = "股票基础信息尚未通过 materialization 和 blocking checks 门禁。"
        cursor = _silver_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            raw_status=raw_status,
            stock_basic_status=stock_basic_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    reason = "复权因子 silver 门禁已满足，提交股票当前交易日 silver 更新。"
    cursor = _silver_sensor_cursor(
        evaluated_at=evaluated_at,
        registered_trade_day_count=len(registered_trade_days),
        target_trade_date=target_trade_date,
        selected_trade_date=target_trade_date,
        reason=reason,
        source_window_started=source_window_started,
        raw_status=raw_status,
        stock_basic_status=stock_basic_status,
    )
    return dg.SensorResult(
        run_requests=[_silver_run_request_for_trade_date(target_trade_date)],
        cursor=cursor,
    )
