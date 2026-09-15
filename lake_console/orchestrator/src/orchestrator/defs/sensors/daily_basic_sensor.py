"""Bounded raw daily-basic scheduling; source gaps wait for the next tick."""

from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    load_expected_trade_date_window,
)
from orchestrator.defs.asset_guards.daily_basic_readiness import (
    DAILY_BASIC_READINESS_SPEC,
    batch_daily_basic_readiness,
    load_daily_basic_input_codes,
)
from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_HISTORY_START,
    DAILY_BASIC_INTERVAL,
    DAILY_BASIC_JOB,
    DAILY_BASIC_PARTITIONS,
    DAILY_BASIC_UPDATE_START,
    DAILY_BASIC_WINDOW,
    DailyBasicValidationError,
)
from orchestrator.defs.jobs.daily_basic_update import raw_tushare_daily_basic_update_job
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.configs import (
    build_raw_daily_basic_update_job_run_config,
)
from orchestrator.defs.run_contracts.cursor_payloads import build_cursor_details
from orchestrator.defs.run_contracts.cursors import build_sensor_cursor
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE
from orchestrator.defs.source_readiness.daily_basic import (
    probe_daily_basic_for_trade_date,
)


def evaluate_daily_basic(context, now):
    def result(
        reason,
        summary,
        action,
        *,
        day=None,
        component="none",
        request=False,
        evidence=None,
    ):
        cursor = build_sensor_cursor(
            evaluated_at=now,
            decision="request_runs" if request else "skip",
            target_date=day,
            selected_count=int(request),
            blocked_count=int(component != "none"),
            details=build_cursor_details(
                sensor_name="raw_tushare_daily_basic_update_job_sensor",
                job_name=DAILY_BASIC_JOB,
                asset_family="daily_basic",
                partition_set=DAILY_BASIC_PARTITIONS,
                reason_code=reason,
                blocked_component=component,
                summary=summary,
                next_action=action,
                evidence=evidence,
            ),
        )
        requests = (
            [
                build_run_request(
                    run_key=build_asset_update_run_key(
                        subject="daily_basic", unit_id=day
                    ),
                    partition_key=day,
                    run_config=build_raw_daily_basic_update_job_run_config(day),
                )
            ]
            if request
            else []
        )
        return dg.SensorResult(
            run_requests=requests,
            cursor=cursor,
            skip_reason=None if request else dg.SkipReason(summary),
        )

    root = context.resources.lake_root.root()
    context.resources.lake_root.ensure_available_for_run()
    with context.resources.duckdb.connect() as connection:
        window = load_expected_trade_date_window(
            connection,
            silver_trade_calendar_path(root),
            evaluated_at=now,
            min_trade_date=DAILY_BASIC_HISTORY_START,
            window_limit=DAILY_BASIC_WINDOW,
        )
        dates = window.expected_trade_dates
        if not dates:
            return result(
                "empty_window", "当前没有应更新的交易日。", "等待交易日历更新。"
            )
        registered = set(
            context.instance.get_dynamic_partitions(DAILY_BASIC_PARTITIONS)
        )
        gap = next((day for day in dates if day not in registered), None)
        if gap:
            return result(
                "missing_registered_partition",
                f"{gap}尚未注册每日指标分区。",
                "等待分区注册或受控补注册。",
                day=gap,
                component=DAILY_BASIC_PARTITIONS,
            )
        try:
            statuses = batch_daily_basic_readiness(
                context.instance, connection, root, dates
            )
        except DailyBasicValidationError:
            return result(
                "readiness_query_incomplete",
                "最近窗口的交付记录不足以安全判断状态。",
                "人工核对窗口交付记录，不扩大事件历史扫描。",
                component=DAILY_BASIC_READINESS_SPEC.asset_key.to_user_string(),
            )
        day = next((day for day in dates if not statuses[day].ready), None)
        if day is None:
            return result(
                "all_ready", "最近交易日的每日指标已齐备。", "等待下个交易日。"
            )
        status = statuses[day]
        if status.reason != "missing_materialization":
            return result(
                status.reason,
                f"{day}已有文件或检查状态需要核对。",
                "查看检查和交付记录，人工修复后重跑；不自动覆盖。",
                day=day,
                component=DAILY_BASIC_READINESS_SPEC.asset_key.to_user_string(),
            )
        if (
            day == now.date().isoformat()
            and now.time().replace(tzinfo=None) < DAILY_BASIC_UPDATE_START
        ):
            return result(
                "before_update_window",
                f"{day}尚未到19:00更新时段。",
                "19:00后再次检查。",
                day=day,
            )
        runs = context.instance.get_runs(
            filters=dg.RunsFilter(
                job_name=DAILY_BASIC_JOB, tags={"dagster/partition": day}
            ),
            limit=1,
        )
        if runs:
            return result(
                "existing_run",
                f"{day}已提交过每日指标任务。",
                "查看该任务；失败时人工重跑，不自动换run key。",
                day=day,
                component=DAILY_BASIC_READINESS_SPEC.asset_key.to_user_string(),
            )
        try:
            codes = load_daily_basic_input_codes(
                context.instance, connection, root, day
            )
        except (DailyBasicValidationError, OSError):
            return result(
                "upstream_not_ready",
                f"{day}股票Raw日线尚未就绪。",
                "先完成同日股票Raw及其检查。",
                day=day,
                component="raw_tushare_stock_daily",
            )
    source = probe_daily_basic_for_trade_date(
        tushare=context.resources.tushare, trade_date=day, expected_codes=codes
    )
    if not source.ready:
        return result(
            source.reason,
            f"{day}源端每日指标尚未满足最低覆盖。",
            "15分钟后自动复查源端。",
            day=day,
            component="tushare_daily_basic_source",
            evidence={
                "missing_count": source.missing_count,
                "missing_samples": list(source.missing_samples),
            },
        )
    return result(
        "request_run",
        f"{day}上游及源端已就绪，提交每日指标更新。",
        "等待任务完成及两项检查。",
        day=day,
        request=True,
        evidence={
            "source_code_count": source.code_count,
            "required_code_count": len(codes),
        },
    )


@dg.sensor(
    job=raw_tushare_daily_basic_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=DAILY_BASIC_INTERVAL,
    required_resource_keys={"lake_root", "duckdb", "tushare"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="19:00后每15分钟观察最近10个交易日，股票Raw及源端覆盖就绪后一次提交一日每日指标。",
)
def raw_tushare_daily_basic_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_daily_basic(context, datetime.now(CN_A_SENSOR_TIMEZONE))
