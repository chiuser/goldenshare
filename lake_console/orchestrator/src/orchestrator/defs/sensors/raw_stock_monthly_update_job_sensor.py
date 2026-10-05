"""Daily 19:30 completed-month updates, primary sources only, one writer at a time."""

import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.jobs.stock_monthly import (
    raw_stk_period_bar_adj_month_update_job,
    raw_stk_period_bar_month_update_job,
)
from orchestrator.defs.partitions import cn_a_stock_months
from orchestrator.defs.run_contracts.configs import (
    build_stock_monthly_update_job_run_config,
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
from orchestrator.defs.run_contracts.stock_monthly import (
    MONTHLY_UPDATE_POLICY,
    MonthlyBootstrapIOPolicy,
    StockMonthlySource,
    monthly_asset_key,
    monthly_job_name,
)
from orchestrator.defs.source_readiness.stock_monthly import load_monthly_calendar
from orchestrator.defs.stock_monthly_update import (
    completed_month,
    local_monthly_time,
    monthly_update_intent,
    monthly_window_open,
    next_month,
)
from orchestrator.defs.stock_monthly_update_state import (
    monthly_daily_intent_submitted,
    monthly_period_status,
    monthly_upstream_bindings,
)

PENDING_MONTHLY_STATUSES = [
    dg.DagsterRunStatus.NOT_STARTED,
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
]


def evaluate_stock_monthly_update(context, now):
    policy = MONTHLY_UPDATE_POLICY
    now = local_monthly_time(now)
    runtime = cursor_runtime_state(
        sensor_cursor_details(load_sensor_cursor(context.cursor))
    )
    frontier = runtime.get("verified_through", policy.history_verified_through)
    examined = runtime.get("examined_through", frontier)

    def result(
        reason, summary, *, month=None, source=None, request=None, register=False
    ):
        action = (
            "查看本月源状态和冻结证明；等待下日19:30或显式手动续跑。备用源不自动使用。"
            if source
            else "查看周期交付和blocking checks；保留欠账，下一窗口继续。"
        )
        details = build_cursor_details(
            sensor_name="raw_stock_monthly_update_job_sensor",
            job_name=monthly_job_name(source) if source else None,
            asset_family="stock_monthly",
            partition_set=cn_a_stock_months.name,
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
            dynamic_partitions_requests=[cn_a_stock_months.build_add_request([month])]
            if register
            else [],
            skip_reason=None if request else dg.SkipReason(summary),
            cursor=build_sensor_cursor(
                evaluated_at=now,
                decision="request_runs" if request else "skip",
                target_date=month,
                selected_count=int(request is not None),
                details=details,
            ),
        )

    if not monthly_window_open(now):
        return result(
            "before_daily_start", "尚未到上海时间19:30；未读取Lake、数据库或源。"
        )
    try:
        if (
            runtime.get("policy_version", policy.version) != policy.version
            or frontier < policy.history_verified_through
            or not completed_month(now, frontier)
            or examined < frontier
            or not completed_month(now, examined)
        ):
            return result(
                "invalid_frontier", "周期frontier不符合当前已验收基线，需要人工核验。"
            )
        # Guard both automatic and manual primary jobs before any physical scan.
        for source in tuple(StockMonthlySource):
            if context.instance.get_runs(
                filters=dg.RunsFilter(
                    job_name=monthly_job_name(source), statuses=PENDING_MONTHLY_STATUSES
                ),
                limit=1,
            ):
                return result(
                    "writer_pending",
                    "已有主源月线任务排队或运行；两主源保持串行。",
                    source=source,
                )
        root = context.resources.lake_root.root()
        # A cursor is a bookmark, never completion evidence.
        for source in tuple(StockMonthlySource):
            status = monthly_period_status(context.instance, root, source, frontier)
            if status != "ready":
                return result(
                    "baseline_not_ready",
                    f"{frontier}交付基线需要核验：{status}。",
                    month=frontier,
                    source=source,
                )
        month = next_month(examined)
        if not completed_month(now, month):
            return result("already_verified", "已结束月均已交付，等待下一个完成周期。")
        budget = MonthlyBootstrapIOPolicy()
        settings = DuckDBConnectionSettings(
            temp_directory=Path(tempfile.gettempdir()).resolve(),
            memory_limit=f"{budget.duckdb_memory_mb}MB",
            threads=budget.duckdb_threads,
        )
        with connect_configured_duckdb(
            settings, temp_policy="existing_no_spill"
        ) as connection:
            if examined != frontier:
                previous_days, _ = load_monthly_calendar(connection, root, examined)
                if previous_days:
                    return result(
                        "closed_month_changed",
                        "此前无交易月的日历口径发生变化，需要人工核验。",
                        month=examined,
                    )
            days, _ = load_monthly_calendar(connection, root, month)
        if not days:
            examined = month
            return result(
                "no_trading_month", f"{month}整月休市，无需请求源。", month=month
            )
        deferred = []
        for source in tuple(StockMonthlySource):
            status = monthly_period_status(context.instance, root, source, month)
            if status == "ready":
                continue
            if status != "missing":
                deferred.append((status, source))
                continue
            intent = monthly_update_intent(source, month, now.date().isoformat())
            key = build_asset_update_run_key(
                subject=monthly_asset_key(source), unit_id=intent["unit_id"]
            )
            if monthly_daily_intent_submitted(context.instance, source, key):
                deferred.append(("daily_intent_already_submitted", source))
                continue
            if not monthly_upstream_bindings(context.instance, days):
                return result(
                    "monthly_upstream_not_ready",
                    f"{month}日线或身份blocking checks未满足；不提交源下载任务。",
                    month=month,
                    source=source,
                )
            request = build_run_request(
                run_key=build_asset_update_run_key(
                    subject=monthly_asset_key(source), unit_id=intent["unit_id"]
                ),
                job_name=monthly_job_name(source),
                partition_key=month,
                run_config=build_stock_monthly_update_job_run_config(
                    source, now.date().isoformat()
                ),
            )
            register = not context.instance.has_dynamic_partition(
                cn_a_stock_months.name, month
            )
            return result(
                "request_run",
                f"提交{month}主源更新；完整月校验通过后才提升。",
                month=month,
                source=source,
                request=request,
                register=register,
            )
        if deferred:
            reason, source = deferred[0]
            return result(
                reason,
                f"{month}主源状态需要等待或处理：{reason}；保留欠账。原配置可显式续跑，源未就绪等待下一日19:30。",
                month=month,
                source=source,
            )
        frontier = examined = month
        return result(
            "period_verified",
            f"{month}两主源文件与checks均已验证；下次tick推进下个月。",
            month=month,
        )
    except (ValueError, OSError, KeyError):
        return result(
            "monthly_readiness_blocked",
            "周期日历、文件或交付证据无法安全核验；未查询备用源。",
        )


@dg.sensor(
    jobs=[raw_stk_period_bar_month_update_job, raw_stk_period_bar_adj_month_update_job],
    minimum_interval_seconds=MONTHLY_UPDATE_POLICY.tick_min_seconds,
    default_status=dg.DefaultSensorStatus.STOPPED,
    required_resource_keys={"lake_root"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def raw_stock_monthly_update_job_sensor(context: dg.SensorEvaluationContext):
    return evaluate_stock_monthly_update(
        context, datetime.now(ZoneInfo(MONTHLY_UPDATE_POLICY.timezone))
    )
