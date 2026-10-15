"""Daily 19:30 completed-week updates, primary sources only, one writer at a time."""

from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.jobs.stock_weekly import (
    raw_stk_period_bar_adj_week_update_job,
)
from orchestrator.defs.partitions import cn_a_stock_week_ends
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    cursor_runtime_state,
)
from orchestrator.defs.run_contracts.cursors import (
    build_sensor_cursor,
    load_sensor_cursor,
    sensor_cursor_details,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_job_name,
)
from orchestrator.defs.stock_weekly_adj_feed import evaluate_adjusted_feed
from orchestrator.defs.stock_weekly_update import (
    WEEKLY_UPDATE_POLICY,
    completed_week,
    local_weekly_time,
    weekly_manual_next_action,
    weekly_window_open,
)

PENDING_WEEKLY_STATUSES = [
    dg.DagsterRunStatus.NOT_STARTED,
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
]


def evaluate_stock_weekly_update(context, now, *, delivery_reader=None):
    policy = WEEKLY_UPDATE_POLICY
    now = local_weekly_time(now)
    runtime = cursor_runtime_state(
        sensor_cursor_details(load_sensor_cursor(context.cursor))
    )
    frontier = runtime.get("verified_through", policy.history_verified_through)
    examined = runtime.get("examined_through", frontier)
    adjusted = None

    def result(
        reason, summary, *, week=None, source=None, request=None, register=False
    ):
        action = (
            weekly_manual_next_action(source)
            if source
            else "查看周期交付和blocking checks；保留欠账，下一窗口继续。"
        )
        if adjusted is not None:
            action = f"{action} 复权交接：{adjusted.summary}"
        details = build_cursor_details(
            sensor_name="raw_stock_weekly_update_job_sensor",
            job_name=weekly_job_name(source) if source else None,
            asset_family="stock_weekly",
            partition_set=cn_a_stock_week_ends.name,
            reason_code=reason,
            blocked_component=source.value if source else "none",
            summary=summary,
            next_action=action,
            runtime_state={
                **runtime,
                "verified_through": frontier,
                "examined_through": examined,
                "policy_version": policy.version,
            },
            evidence={
                "daily_intent_date": now.date().isoformat(),
                "source": source.value if source else None,
            },
        )
        return dg.SensorResult(
            run_requests=[request] if request else [],
            dynamic_partitions_requests=[cn_a_stock_week_ends.build_add_request([week])]
            if register
            else [],
            skip_reason=None if request else dg.SkipReason(summary),
            cursor=build_sensor_cursor(
                evaluated_at=now,
                decision="request_runs" if request else "skip",
                target_date=week,
                selected_count=int(request is not None),
                details=details,
            ),
        )

    if not weekly_window_open(now):
        return result(
            "before_daily_start", "尚未到上海时间19:30；未读取Lake、数据库或源。"
        )
    try:
        if (
            runtime.get("policy_version", policy.version) != policy.version
            or frontier < policy.history_verified_through
            or not completed_week(now, frontier)
            or examined < frontier
            or not completed_week(now, examined)
        ):
            return result(
                "invalid_frontier", "周期frontier不符合当前已验收基线，需要人工核验。"
            )
        source = StockWeeklySource.PRIMARY_ADJUSTED
        if context.instance.get_runs(
            filters=dg.RunsFilter(
                job_name=weekly_job_name(source), statuses=PENDING_WEEKLY_STATUSES
            ),
            limit=1,
        ):
            return result(
                "writer_pending",
                "已有复权周线任务排队或运行；等待同批完成。",
                source=source,
            )
        adjusted = evaluate_adjusted_feed(context, runtime, reader=delivery_reader)
        return result(
            adjusted.reason,
            adjusted.summary,
            week=adjusted.week,
            source=source,
            request=adjusted.request,
            register=adjusted.register,
        )
    except (WeeklyCaptureError, ValueError, OSError):
        return result(
            "weekly_readiness_blocked", "复权交付证据无法安全核验，保留原批和水位。"
        )


@dg.sensor(
    jobs=[raw_stk_period_bar_adj_week_update_job],
    minimum_interval_seconds=WEEKLY_UPDATE_POLICY.tick_min_seconds,
    default_status=dg.DefaultSensorStatus.STOPPED,
    required_resource_keys={"lake_root"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def raw_stock_weekly_update_job_sensor(context: dg.SensorEvaluationContext):
    return evaluate_stock_weekly_update(
        context, datetime.now(ZoneInfo(WEEKLY_UPDATE_POLICY.timezone))
    )
