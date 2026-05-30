from datetime import datetime

import dagster as dg

from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.index_daily_raw_file_readiness import (
    IndexDailyRawFileReadiness,
    check_index_daily_raw_files_for_trade_date,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    CN_A_SENSOR_TIMEZONE,
    silver_index_daily_ready_for_trade_date,
)


MAX_STATUS_SAMPLE_COUNT = 20


def _asset_status_payload(status: AssetReadinessStatus) -> dict[str, object]:
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


def _latest_registered_trade_date(
    registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> str | None:
    today = evaluated_at.date().isoformat()
    eligible_trade_days = tuple(
        trade_date for trade_date in registered_trade_days if trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _cursor_payload(
    *,
    evaluated_at: datetime,
    target_trade_date: str | None,
    registered_trade_day_count: int,
    registered_code_count: int,
    raw_ready_code_count: int,
    missing_raw_file_count: int,
    missing_raw_trade_date_count: int,
    selected_trade_date: str | None,
    silver_status: AssetReadinessStatus | None,
    missing_raw_file_samples: tuple[str, ...],
    missing_raw_trade_date_samples: tuple[str, ...],
    raw_scan_error_code: str | None = None,
    raw_scan_error: str | None = None,
) -> str:
    decision = (
        SensorCursorDecision.REQUEST_RUNS
        if selected_trade_date
        else SensorCursorDecision.SKIP
    )
    blocked_count = missing_raw_file_count + missing_raw_trade_date_count
    if raw_scan_error:
        blocked_count = max(blocked_count, registered_code_count)
    sample_keys = (
        missing_raw_file_samples
        or missing_raw_trade_date_samples
        or ((selected_trade_date,) if selected_trade_date else ())
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=blocked_count,
        sample_keys=sample_keys,
        details={
            "registered_trade_day_count": registered_trade_day_count,
            "registered_code_count": registered_code_count,
            "raw_ready_code_count": raw_ready_code_count,
            "missing_raw_file_count": missing_raw_file_count,
            "missing_raw_trade_date_count": missing_raw_trade_date_count,
            "selected_trade_date": selected_trade_date,
            "silver_status": _asset_status_payload(silver_status)
            if silver_status
            else None,
            "missing_raw_file_samples": list(missing_raw_file_samples),
            "missing_raw_trade_date_samples": list(missing_raw_trade_date_samples),
            "raw_scan_error_code": raw_scan_error_code,
            "raw_scan_error": raw_scan_error,
        },
    )


def _raw_file_readiness_cursor_fields(
    raw_status: IndexDailyRawFileReadiness | None,
) -> dict[str, object]:
    if raw_status is None:
        return {
            "raw_ready_code_count": 0,
            "missing_raw_file_count": 0,
            "missing_raw_trade_date_count": 0,
            "missing_raw_file_samples": (),
            "missing_raw_trade_date_samples": (),
            "raw_scan_error_code": None,
            "raw_scan_error": None,
        }
    return {
        "raw_ready_code_count": raw_status.ready_code_count,
        "missing_raw_file_count": raw_status.missing_file_count,
        "missing_raw_trade_date_count": raw_status.missing_trade_date_count,
        "missing_raw_file_samples": raw_status.missing_file_codes[:MAX_STATUS_SAMPLE_COUNT],
        "missing_raw_trade_date_samples": raw_status.missing_trade_date_codes[
            :MAX_STATUS_SAMPLE_COUNT
        ],
        "raw_scan_error_code": raw_status.scan_error_code,
        "raw_scan_error": raw_status.scan_error,
    }


@dg.sensor(
    job_name="silver_index_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="指数日线 raw-by-code 文件包含目标交易日数据后，触发 silver 分区生成任务。",
)
def silver_index_daily_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    registered_trade_days = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_trade_days.name))
    )
    registered_index_codes = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name))
    )

    if not registered_trade_days:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=0,
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            silver_status=None,
            **_raw_file_readiness_cursor_fields(None),
        )
        return dg.SensorResult(
            skip_reason="没有注册指数交易日分区，无法触发指数日线 silver 生成。",
            cursor=cursor,
        )

    if not registered_index_codes:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=0,
            selected_trade_date=None,
            silver_status=None,
            **_raw_file_readiness_cursor_fields(None),
        )
        return dg.SensorResult(
            skip_reason="没有注册指数代码分区，无法触发指数日线 silver 生成。",
            cursor=cursor,
        )

    target_trade_date = _latest_registered_trade_date(registered_trade_days, evaluated_at)
    if target_trade_date is None:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            silver_status=None,
            **_raw_file_readiness_cursor_fields(None),
        )
        return dg.SensorResult(
            skip_reason="没有符合当前日期窗口的指数交易日分区。",
            cursor=cursor,
        )

    silver_status = silver_index_daily_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if silver_status.ready:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            silver_status=silver_status,
            **_raw_file_readiness_cursor_fields(None),
        )
        return dg.SensorResult(
            skip_reason="最新指数交易日的 silver_index_daily 分区已经生成完成并通过 blocking checks。",
            cursor=cursor,
        )

    if silver_status.materialized:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            silver_status=silver_status,
            **_raw_file_readiness_cursor_fields(None),
        )
        return dg.SensorResult(
            skip_reason=(
                "最新指数交易日的 silver_index_daily 已生成但 blocking checks 未全绿，"
                "暂不自动重跑，请先人工处理失败检查。"
            ),
            cursor=cursor,
        )

    raw_status = check_index_daily_raw_files_for_trade_date(
        lake_root_path=context.resources.lake_root.root(),
        duckdb=context.resources.duckdb,
        registered_index_codes=registered_index_codes,
        trade_date=target_trade_date,
    )
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        target_trade_date=target_trade_date,
        registered_trade_day_count=len(registered_trade_days),
        registered_code_count=len(registered_index_codes),
        selected_trade_date=target_trade_date if raw_status.ready else None,
        silver_status=silver_status,
        **_raw_file_readiness_cursor_fields(raw_status),
    )

    if not raw_status.ready:
        if raw_status.scan_error:
            context.log.warning(
                "index_daily_raw_file_readiness_scan_failed trade_date=%s "
                "error_code=%s error=%s",
                target_trade_date,
                raw_status.scan_error_code,
                raw_status.scan_error,
            )
            skip_reason = "指数日线 raw 文件扫描失败，暂不生成 silver。"
        elif raw_status.missing_file_count:
            skip_reason = "指数日线 raw-by-code 文件仍有缺失代码，暂不生成 silver。"
        else:
            skip_reason = "指数日线 raw-by-code 文件仍有代码缺少目标交易日数据，暂不生成 silver。"
        return dg.SensorResult(
            skip_reason=skip_reason,
            cursor=cursor,
        )

    return dg.SensorResult(
        run_requests=[
            build_run_request(
                partition_key=target_trade_date,
                run_key=f"silver_index_daily:{target_trade_date}",
            )
        ],
        cursor=cursor,
    )
