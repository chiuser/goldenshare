"""Daily 19:30 completed-week updates, primary sources only, one writer at a time."""

import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.jobs.stock_weekly import (
    raw_stk_period_bar_adj_week_update_job,
    raw_stk_period_bar_week_update_job,
)
from orchestrator.defs.partitions import cn_a_stock_week_ends
from orchestrator.defs.run_contracts.configs import (
    build_stock_weekly_update_job_run_config,
)
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    cursor_runtime_state,
)
from orchestrator.defs.run_contracts.cursors import (
    build_sensor_cursor,
    load_sensor_cursor,
    sensor_cursor_details,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    WeeklyBudget,
    weekly_asset_key,
    weekly_job_name,
)
from orchestrator.defs.source_readiness.stock_weekly import load_weekly_calendar
from orchestrator.defs.stock_weekly_update import (
    AUTOMATIC_WEEKLY_SOURCES,
    WEEKLY_UPDATE_POLICY,
    completed_week,
    local_weekly_time,
    next_weekly_period,
    weekly_manual_next_action,
    weekly_update_intent,
    weekly_window_open,
)
from orchestrator.defs.stock_weekly_update_state import (
    weekly_daily_intent_submitted,
    weekly_period_status,
    weekly_upstream_events_ready,
)

PENDING_WEEKLY_STATUSES = [
    dg.DagsterRunStatus.NOT_STARTED,
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
]


def evaluate_stock_weekly_update(context, now):
    policy = WEEKLY_UPDATE_POLICY
    now = local_weekly_time(now)
    runtime = cursor_runtime_state(
        sensor_cursor_details(load_sensor_cursor(context.cursor))
    )
    frontier = runtime.get("verified_through", policy.history_verified_through)
    examined = runtime.get("examined_through", frontier)

    def result(
        reason, summary, *, week=None, source=None, request=None, register=False
    ):
        action = (
            weekly_manual_next_action(source)
            if source
            else "查看周期交付和blocking checks；保留欠账，下一窗口继续。"
        )
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
        # Guard both automatic and manual primary jobs before any physical scan.
        for source in AUTOMATIC_WEEKLY_SOURCES:
            if context.instance.get_runs(
                filters=dg.RunsFilter(
                    job_name=weekly_job_name(source), statuses=PENDING_WEEKLY_STATUSES
                ),
                limit=1,
            ):
                return result(
                    "writer_pending",
                    "已有主源周线任务排队或运行；两主源保持串行。",
                    source=source,
                )
        root = context.resources.lake_root.root()
        # Bootstrap was reconciled once. Only the next uncompleted period is checked.
        week = next_weekly_period(examined)
        if not completed_week(now, week):
            return result("already_verified", "已结束周均已交付，等待下一个完成周期。")
        budget = WeeklyBudget()
        settings = DuckDBConnectionSettings(
            temp_directory=Path(tempfile.gettempdir()).resolve(),
            memory_limit=budget.duckdb_memory_limit,
            threads=budget.duckdb_threads,
        )
        with connect_configured_duckdb(
            settings, temp_policy="existing_no_spill"
        ) as connection:
            if examined != frontier:
                previous_days, _ = load_weekly_calendar(connection, root, examined)
                if previous_days:
                    return result(
                        "closed_week_changed",
                        "此前无交易周的日历口径发生变化，需要人工核验。",
                        week=examined,
                    )
            days, _ = load_weekly_calendar(connection, root, week)
        if not days:
            examined = week
            return result("no_trading_week", f"{week}整周休市，无需请求源。", week=week)
        deferred = []
        for source in AUTOMATIC_WEEKLY_SOURCES:
            status = weekly_period_status(context.instance, root, source, week)
            if status == "ready":
                continue
            if status != "missing":
                deferred.append((status, source))
                continue
            intent = weekly_update_intent(source, week, now.date().isoformat())
            key = build_asset_update_run_key(
                subject=weekly_asset_key(source), unit_id=intent["unit_id"]
            )
            if weekly_daily_intent_submitted(context.instance, source, key):
                deferred.append(("daily_intent_already_submitted", source))
                continue
            if not weekly_upstream_events_ready(context.instance, days):
                return result(
                    "weekly_upstream_not_ready",
                    f"{week}日线或身份blocking checks未满足；不提交源下载任务。",
                    week=week,
                    source=source,
                )
            request = build_run_request(
                run_key=build_asset_update_run_key(
                    subject=weekly_asset_key(source), unit_id=intent["unit_id"]
                ),
                job_name=weekly_job_name(source),
                partition_key=week,
                run_config=build_stock_weekly_update_job_run_config(
                    source, now.date().isoformat()
                ),
            )
            register = not context.instance.has_dynamic_partition(
                cn_a_stock_week_ends.name, week
            )
            return result(
                "request_run",
                f"提交{week}主源更新；完整周校验通过后才提升。",
                week=week,
                source=source,
                request=request,
                register=register,
            )
        if deferred:
            reason, source = deferred[0]
            return result(
                reason,
                f"{week}主源状态需要等待或处理：{reason}；保留欠账。原配置可显式续跑，源未就绪等待下一日19:30。",
                week=week,
                source=source,
            )
        frontier = examined = week
        return result(
            "period_verified",
            f"{week}两主源文件与checks均已验证；下次tick推进下个周。",
            week=week,
        )
    except (WeeklyCaptureError, ValueError, OSError):
        return result(
            "weekly_readiness_blocked",
            "周期日历、文件或交付证据无法安全核验；未查询备用源。",
        )


@dg.sensor(
    jobs=[raw_stk_period_bar_week_update_job, raw_stk_period_bar_adj_week_update_job],
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
