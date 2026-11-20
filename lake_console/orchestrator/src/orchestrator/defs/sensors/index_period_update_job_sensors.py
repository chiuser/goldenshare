"""指数周月线的四个停止态sensor；只编排既有job，不写行情。"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import dagster as dg
from dagster._core.storage.tags import RUN_KEY_TAG

from orchestrator.defs.io.index_period_writer import load_index_period_calendar
from orchestrator.defs.jobs.index_period_update import (
    raw_index_monthly_update_job,
    raw_index_weekly_update_job,
    silver_index_monthly_update_job,
    silver_index_weekly_update_job,
)
from orchestrator.defs.partitions import cn_a_index_months, cn_a_index_week_ends
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    limit_cursor_samples,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
    sensor_cursor_details,
)
from orchestrator.defs.run_contracts.index_period import (
    INDEX_MONTHLY,
    INDEX_PERIOD_START_HOUR,
    INDEX_PERIOD_TICK_SECONDS,
    INDEX_PERIOD_TIMEZONE,
    INDEX_WEEKLY,
    IndexPeriodSilverConfig,
    build_index_period_silver_run_config,
    index_period_bounds,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import (
    build_asset_update_run_key,
    build_upstream_triggered_run_key,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.index_period_daily_readiness import (
    index_period_daily_readiness,
    index_period_native_delivery,
)
from orchestrator.source_readiness.tushare.index_period import (
    index_period_source_published,
)

_ACTIVE_STATUSES = [
    dg.DagsterRunStatus.NOT_STARTED, dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING, dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
]


def _calendar_targets(context, now, period, layer):
    today = now.date()
    month_start, month_end = index_period_bounds(INDEX_MONTHLY, today.strftime("%Y-%m"))
    previous_start, previous_end = index_period_bounds(
        INDEX_MONTHLY, (month_start - timedelta(days=1)).strftime("%Y-%m")
    )
    week_start, week_end = index_period_bounds(INDEX_WEEKLY, today.isoformat())
    start, end = (
        (week_start, week_end) if period == INDEX_WEEKLY
        else (previous_start, today) if layer == "raw" else (month_start, month_end)
    )
    with context.resources.duckdb.connect() as connection:
        load_index_period_calendar(connection, context.resources.lake_root.root(), start, end)
        rows = connection.execute("SELECT trade_date,is_open FROM index_period_calendar ORDER BY trade_date").fetchall()
    if len(rows) != (end - start).days + 1:
        return None, "calendar_incomplete", None
    opens = [day for day, is_open in rows if is_open]
    if today not in opens:
        return None, "market_closed", None
    week = [day for day in opens if week_start <= day <= week_end]
    month = [day for day in opens if month_start <= day <= month_end]
    if layer == "raw":
        if period == INDEX_WEEKLY:
            return (week[-1].isoformat(), "ready", week[-1]) if today == week[-1] else (None, "not_period_release_day", None)
        previous = [day for day in opens if previous_start <= day <= previous_end]
        return (previous_start.strftime("%Y-%m"), "ready", previous[-1]) if today == month[0] and previous else (None, "not_period_release_day", None)
    return (week[-1].isoformat() if period == INDEX_WEEKLY else month_start.strftime("%Y-%m")), "ready", None


def _result(context, now, period, layer, *, key=None, reason, summary, request=None,
            missing=(), after=None, component="none"):
    asset = period.raw_asset if layer == "raw" else period.silver_asset
    details = build_cursor_details(
        sensor_name=asset + "_update_job_sensor", job_name=asset + "_update_job",
        asset_family=period.dataset_id, partition_set=period.partition_set,
        reason_code=reason, blocked_component=component, summary=summary,
        next_action="等待本次运行完成。" if request else "上游就绪后等待下一次检查；失败由人工在原job重跑原分区。",
        frontier={"partition_key": key, "trade_date": now.date().isoformat()},
        evidence={"missing_code_count": len(missing), "missing_codes": limit_cursor_samples(missing)},
        runtime_state={"raw_after_storage_id": after} if after is not None else None,
    )
    partitions = cn_a_index_week_ends if period == INDEX_WEEKLY else cn_a_index_months
    additions = (
        [partitions.build_add_request([key])]
        if request and not context.instance.has_dynamic_partition(period.partition_set, key) else []
    )
    context.log.info(summary)
    return dg.SensorResult(
        run_requests=[request] if request else [],
        skip_reason=None if request else dg.SkipReason(summary),
        cursor=build_sensor_cursor(
            evaluated_at=now,
            decision=SensorCursorDecision.REQUEST_RUNS if request else SensorCursorDecision.SKIP,
            target_date=key, selected_count=int(request is not None),
            blocked_count=int(request is None and component != "none"), sample_keys=limit_cursor_samples(missing), details=details,
        ),
        dynamic_partitions_requests=additions,
    )


def _existing_attempt(instance, job, run_key):
    runs = instance.get_runs(filters=dg.RunsFilter(job_name=job, tags={RUN_KEY_TAG: run_key}), limit=1)
    return runs[0] if runs else None


def _raw_candidate(instance, period, after):
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=dg.AssetKey(period.raw_asset), after_storage_id=after),
        limit=1, ascending=after is not None,
    ).records
    return records[0] if records else None


def evaluate_index_period_sensor(context, now, *, period, layer):
    now = now.astimezone(ZoneInfo(INDEX_PERIOD_TIMEZONE))
    state = sensor_cursor_details(load_sensor_cursor(context.cursor)).get("runtime_state", {})
    after = state.get("raw_after_storage_id")
    result = lambda **kwargs: _result(context, now, period, layer, after=after, **kwargs)
    if now.hour < INDEX_PERIOD_START_HOUR:
        return result(reason="outside_window", summary="上海时间19:00至零点前检查指数周月线。")
    context.resources.lake_root.ensure_available_for_run()
    asset = period.raw_asset if layer == "raw" else period.silver_asset
    job = asset + "_update_job"
    if context.instance.get_runs(filters=dg.RunsFilter(job_name=job, statuses=_ACTIVE_STATUSES), limit=1):
        return result(reason="job_active", summary=f"{job}已有排队或运行任务，等待完成。", component=job)
    for base in ("silver_trade_calendar",) + (("silver_index_basic",) if layer == "silver" else ()):
        _, ready = index_period_native_delivery(context.instance, base)
        if not ready:
            return result(reason="foundation_not_ready", summary=f"等待{base}及其已有检查通过。", component=base)
    key, reason, period_end = _calendar_targets(context, now, period, layer)
    if key is None:
        return result(reason=reason, summary="当前不是所选频率发布日、休市或交易日历未完整覆盖。",
                      component="silver_trade_calendar" if reason == "calendar_incomplete" else "none")
    if layer == "raw":
        run_key = build_asset_update_run_key(subject=job, unit_id=key)
        if _existing_attempt(context.instance, job, run_key):
            return result(key=key, reason="attempt_exists", summary=f"{key}原始行情已提交；失败需人工重跑。")
        _, delivered = index_period_native_delivery(context.instance, asset, key)
        if delivered:
            return result(key=key, reason="already_ready", summary=f"{key}原始行情已完成。")
        if not index_period_source_published(period, period_end):
            return result(key=key, reason="source_not_published", summary=f"等待{key}正式指数行情发布。", component=period.dataset_id)
        return result(key=key, reason="raw_requested", summary=f"提交{key}主要指数原始行情更新。",
                      request=build_run_request(run_key=run_key, partition_key=key))

    today = now.date().isoformat()
    run_key = build_asset_update_run_key(subject=job, unit_id=f"{key}:{today}")
    current, delivered = index_period_native_delivery(context.instance, asset, key)
    completed = delivered and current.asset_materialization.metadata["goldenshare/trade_date"].value == today
    attempt = None if completed else _existing_attempt(context.instance, job, run_key)
    reason, missing = "daily_already_handled", ()
    if not completed and attempt is None:
        reason, missing = index_period_daily_readiness(
            context.instance, context.resources.duckdb, context.resources.lake_root.root(), today,
        )
        if reason == "ready":
            return result(key=key, reason="daily_requested", summary=f"提交{key}指数行情日更，截至{today}。",
                request=build_run_request(run_key=run_key, partition_key=key,
                    run_config=build_index_period_silver_run_config(period, IndexPeriodSilverConfig(mode="daily", trade_date=today))))

    candidate = _raw_candidate(context.instance, period, after)
    if candidate is None:
        if attempt is not None and attempt.status in (dg.DagsterRunStatus.FAILURE, dg.DagsterRunStatus.CANCELED):
            return result(key=key, reason="daily_attempt_failed", component=job,
                          summary=f"{key}截至{today}的日更失败或已取消，请人工在原job重跑原分区。")
        if reason == "daily_already_handled":
            return result(key=key, reason=reason, summary=(
                f"{key}截至{today}的行情已完成，等待新的正式Raw批次。" if completed
                else f"{key}截至{today}的日更已提交过；若失败，请人工在原job重跑。"
            ))
        summary = {
            "daily_materialization_missing": f"等待{today}DG指数日线成功物化。",
            "daily_run_not_success": f"等待{today}DG指数日线生产运行成功结束。",
            "daily_checks_not_ready": f"等待{today}DG指数日线的四种关联检查通过。",
            "daily_file_missing": f"{today}DG指数日线文件缺失，先补齐上游。",
            "daily_codes_missing": f"{today}DG指数日线缺少{len(missing)}个目标代码，样本{limit_cursor_samples(missing)}。",
        }[reason]
        return result(key=key, reason=reason, missing=missing, component="silver_index_daily",
                      summary=summary)
    metadata = candidate.asset_materialization.metadata
    original_key = candidate.partition_key
    if metadata.get("goldenshare/source_method") and metadata["goldenshare/source_method"].value == "index_period_bootstrap":
        after = candidate.storage_id
        return result(key=original_key, reason="bootstrap_origin", summary="已定位初始化完成位置，不重放历史初始化。")
    producer = context.instance.get_run_by_id(candidate.run_id)
    if producer is None or not producer.is_finished:
        return result(key=original_key, reason="raw_run_pending", summary="等待正式Raw生产运行成功结束。", component=period.raw_asset)
    if producer.status != dg.DagsterRunStatus.SUCCESS:
        after = candidate.storage_id
        return result(key=original_key, reason="raw_run_failed", summary="正式Raw生产运行失败，等待人工重跑。", component=period.raw_asset)
    latest, ready = index_period_native_delivery(context.instance, period.raw_asset, original_key)
    if latest.storage_id != candidate.storage_id:
        after = candidate.storage_id
        return result(key=original_key, reason="raw_superseded", summary="该周期已有更新的Raw批次，下一次检查处理新批次。")
    if not ready:
        return result(key=original_key, reason="raw_checks_not_ready", summary="等待正式Raw与本次物化关联的检查通过。", component=period.raw_asset)
    if original_key == key and not completed:
        failed = attempt is not None and attempt.status in (
            dg.DagsterRunStatus.FAILURE, dg.DagsterRunStatus.CANCELED,
        )
        return result(key=key, reason="daily_attempt_failed" if failed else reason,
            missing=missing, component=job if attempt is not None else "silver_index_daily",
            summary=(f"{key}截至{today}的日更失败或已取消，请人工在原job重跑原分区。" if failed
                     else f"等待{today}DG指数日线及当期日更成功后，再提交{key}正式覆盖。"))
    run_key = build_upstream_triggered_run_key(consumer=job, upstream_batch_id=metadata["goldenshare/upstream_batch_id"].value)
    previous = _existing_attempt(context.instance, job, run_key)
    if previous:
        after = candidate.storage_id
        return result(key=original_key, reason="period_attempt_exists", summary="该Raw批次已提交过覆盖；失败需人工在原分区重跑。")
    return result(key=original_key, reason="period_requested", summary=f"提交正式Raw对原周期{original_key}的覆盖。",
        request=build_run_request(run_key=run_key, partition_key=original_key,
            run_config=build_index_period_silver_run_config(period, IndexPeriodSilverConfig(mode="period"))))


def _sensor(job, layer, description):
    return dg.sensor(
        job=job, minimum_interval_seconds=INDEX_PERIOD_TICK_SECONDS,
        default_status=dg.DefaultSensorStatus.STOPPED,
        required_resource_keys={"lake_root", "duckdb"}, description=description,
        tags=build_sensor_tags(sensor_domain=SensorDomain.INDEX_TOPIC,
            target_layer=SensorTargetLayer.RAW if layer == "raw" else SensorTargetLayer.SILVER,
            role=SensorRole.ASSET_UPDATE),
    )


@_sensor(raw_index_weekly_update_job, "raw", "当周行情发布后，触发主要指数周线原始行情更新。")
def raw_index_weekly_update_job_sensor(context: dg.SensorEvaluationContext):
    return evaluate_index_period_sensor(context, datetime.now(ZoneInfo(INDEX_PERIOD_TIMEZONE)), period=INDEX_WEEKLY, layer="raw")


@_sensor(raw_index_monthly_update_job, "raw", "上月行情发布后，触发主要指数月线原始行情更新。")
def raw_index_monthly_update_job_sensor(context: dg.SensorEvaluationContext):
    return evaluate_index_period_sensor(context, datetime.now(ZoneInfo(INDEX_PERIOD_TIMEZONE)), period=INDEX_MONTHLY, layer="raw")


@_sensor(silver_index_weekly_update_job, "silver", "DG指数日线成功后更新当前周，并覆盖新到的期末周线。")
def silver_index_weekly_update_job_sensor(context: dg.SensorEvaluationContext):
    return evaluate_index_period_sensor(context, datetime.now(ZoneInfo(INDEX_PERIOD_TIMEZONE)), period=INDEX_WEEKLY, layer="silver")


@_sensor(silver_index_monthly_update_job, "silver", "DG指数日线成功后更新当前月，并覆盖新到的期末月线。")
def silver_index_monthly_update_job_sensor(context: dg.SensorEvaluationContext):
    return evaluate_index_period_sensor(context, datetime.now(ZoneInfo(INDEX_PERIOD_TIMEZONE)), period=INDEX_MONTHLY, layer="silver")
