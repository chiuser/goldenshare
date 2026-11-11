"""Native whole-market current-period assets and their daily sensors."""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs.io.stock_period_raw import process_memory_budget
from orchestrator.defs.run_contracts.stock_period import DEFAULT_POLICY, period_for


def _period_inputs_ready(instance, business_date, days):
    from orchestrator.defs.sensors.readiness import (
        SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY,
        SILVER_SUSPEND_D_CHECKS,
        AssetReadinessSpec,
        asset_readiness_status,
        silver_stock_lifecycle_ready_for_trade_date,
    )

    lifecycle = silver_stock_lifecycle_ready_for_trade_date(instance, business_date)
    if not lifecycle.ready:
        raise ValueError("period_lifecycle_not_ready:" + lifecycle.reason)
    for day in days:
        suspension = asset_readiness_status(
            instance, AssetReadinessSpec(SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY, SILVER_SUSPEND_D_CHECKS),
            partition_key=day,
        )
        if not suspension.ready:
            raise ValueError("period_suspend_not_ready:" + suspension.reason)


def deliver_asset(context, config, lake_root, freq):
    """One full-market period per real run; no daily ledger or single-stock history."""
    import time

    import dagster as dg

    from orchestrator.defs.bootstrap.stock_period_history import (
        check_devices,
        devices,
        roots,
        writer,
    )
    from orchestrator.defs.io.stock_period_raw import (
        _BUDGET,
        StorageBudget,
        assemble_period,
        durable_directory,
        file_version,
        publish_period,
    )
    from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
    from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
    from orchestrator.defs.run_contracts.stock_period import FIELDS
    from orchestrator.defs.run_contracts.stock_period_delivery import (
        COMPLETION_KEY,
        FILE_DELIVERY_KEY,
        WORK_KEY,
        delivery_completion,
        delivery_ref,
        delivery_work,
        period_run_tags,
    )
    from orchestrator.defs.source_readiness.stock_period import (
        check_period_rows,
        load_period_universe,
        period_input_days,
    )
    from orchestrator.defs.stock_period_source import HttpPage, capture_current_period

    day = date.fromisoformat(config.automatic_intent_date)
    current_day = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    period = period_for(day, freq)
    if period != context.partition_key or day > current_day:
        raise ValueError("period_daily_partition_or_date_mismatch")
    context.instance.add_run_tags(context.run.run_id, period_run_tags(
        business_date=day.isoformat(), kind=config.intent, freq=freq))
    lake_root.ensure_available_for_run()
    root, staging = roots(lake_root.root(), Path(DEFAULT_LAKE_STAGING_ROOT))
    days = period_input_days(root, day.isoformat(), freq, closed_period=config.intent == "closed_period")
    if not days:
        raise ValueError("period_intent_not_trading_day")
    _period_inputs_ready(context.instance, day.isoformat(), days)
    universe = load_period_universe(root, day.isoformat(), freq, days=days)
    reference = delivery_ref(context.run.run_id, freq, config.intent, day.isoformat(), [period])
    work = durable_directory(staging / "stock_period" / "runs" / context.run.run_id)
    captured_devices = devices(root, staging)
    last_checked, cancelled = float("-inf"), False

    def cancel():
        nonlocal last_checked, cancelled
        if time.monotonic() - last_checked >= 2:
            last_checked = time.monotonic()
            run = context.instance.get_run_by_id(context.run.run_id)
            cancelled = run is not None and run.status in (dg.DagsterRunStatus.CANCELING, dg.DagsterRunStatus.CANCELED)
        return cancelled

    progress = lambda value: context.log.info(str(value))
    with writer(staging), process_memory_budget(DEFAULT_POLICY):
        budget = StorageBudget(work, DEFAULT_POLICY, cancel=cancel, progress=progress)
        budget.guard = lambda: check_devices(root, staging, captured_devices)
        token = _BUDGET.set(budget)
        try:
            yield dg.AssetObservation(asset_key=context.asset_key, metadata={WORK_KEY: dg.MetadataValue.json(
                delivery_work(reference, kind=config.intent, business_date=day.isoformat(), periods=[period],
                              stock_codes=universe["listed"]))})
            sources, rows = capture_current_period(
                work=work / "source", freq=freq, period=period, listed=universe["listed"],
                aliases=universe["aliases"], transport=HttpPage(cancel=cancel, progress=progress),
                cancel=cancel, progress=progress,
            )
            source_status = check_period_rows(
                rows, freq=freq, business_date=day.isoformat(), required_codes=universe["required"],
                optional_codes=universe["optional"], aliases=universe["aliases"],
                expected_dates=universe["expected_dates"] if config.intent == "closed_period" else None,
                maximum_asof=current_day.isoformat() if config.intent == "closed_period" else day.isoformat(),
            )
            if not source_status["ready"]:
                raise ValueError(source_status["reason"])
            if any(file_version(path)
                   != universe["reference_versions"][key] for key, path in universe["references"].items()):
                raise ValueError("period_reference_changed")
            item = assemble_period(sources, work=work / "assembly", root=root, freq=freq, period=period,
                                   cancel=cancel, progress=progress)
            item = publish_period(item, cancel=cancel)
            yield dg.MaterializeResult(metadata=build_materialization_metadata(
                uri=item["target"], row_count=item["rows"], observed_columns=FIELDS,
                extra_metadata={FILE_DELIVERY_KEY: dg.MetadataValue.json(reference),
                    "goldenshare/period_file_version": dg.MetadataValue.json(item["version"]),
                    "goldenshare/business_date": day.isoformat(), "goldenshare/source_asof": item["source_asof"],
                    "goldenshare/rewritten": True,
                    "goldenshare/period_source_readiness": dg.MetadataValue.json({**source_status,
                        "reference_versions": universe["reference_versions"]})},
            ))
            yield dg.AssetObservation(asset_key=context.asset_key, metadata={COMPLETION_KEY: dg.MetadataValue.json(
                delivery_completion(reference, kind=config.intent, business_date=day.isoformat(), periods=[period]))})
        finally:
            _BUDGET.reset(token)


def evaluate_daily_sensor(context, now, *, freq, staging_root=None):
    """Check this business day's required codes before submitting the existing job."""
    import tempfile
    import time

    import dagster as dg

    from orchestrator.defs.duckdb_connection import (
        DuckDBConnectionSettings,
        connect_configured_duckdb,
    )
    from orchestrator.defs.partitions import cn_a_stock_months, cn_a_stock_week_ends
    from orchestrator.defs.paths import silver_trade_calendar_path
    from orchestrator.defs.run_contracts.configs import build_stock_period_run_config
    from orchestrator.defs.run_contracts.cursor_payloads import build_cursor_details
    from orchestrator.defs.run_contracts.cursors import build_sensor_cursor
    from orchestrator.defs.run_contracts.requests import build_run_request
    from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
    from orchestrator.defs.run_contracts.stock_period import (
        STOCK_PERIOD_DAILY_START_TIME,
    )
    from orchestrator.defs.source_readiness.stock_period import (
        load_period_universe,
        probe_stock_period_source,
    )

    now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    if now.strftime("%H:%M") < STOCK_PERIOD_DAILY_START_TIME:
        return dg.SensorResult(skip_reason=dg.SkipReason("尚未到上海时间20:00。"))
    from orchestrator.defs.bootstrap.stock_period_history import roots
    from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT

    root, _ = roots(context.resources.lake_root.root(), Path(staging_root or DEFAULT_LAKE_STAGING_ROOT))
    if not root.is_dir():
        return dg.SensorResult(skip_reason=dg.SkipReason("period_lake_unavailable"))
    asset = f"raw_tushare_stk_period_bar_adj_{freq}"
    job = f"raw_stk_period_bar_adj_{freq}_update_job"
    business_date, period = now.date().isoformat(), period_for(now.date(), freq)
    run_key = build_asset_update_run_key(subject=asset, unit_id=business_date)
    if context.instance.get_runs(filters=dg.RunsFilter(job_name=job, tags={"dagster/run_key": run_key}), limit=1):
        return dg.SensorResult(skip_reason=dg.SkipReason("本频当天已经提交；失败时按原业务日期整批重跑。"))
    from orchestrator.defs.run_contracts.stock_period_delivery import (
        BUSINESS_DATE_TAG,
        KIND_TAG,
    )

    if context.instance.get_runs(filters=dg.RunsFilter(job_name=job,
            tags={BUSINESS_DATE_TAG: business_date, KIND_TAG: "daily"}), limit=1):
        return dg.SensorResult(skip_reason=dg.SkipReason("本频当天已有明确业务日期的运行，不重复提交。"))
    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=Path(tempfile.gettempdir()).resolve()), temp_policy="existing_no_spill",
    ) as con:
        opened = con.execute("SELECT count(*) FROM read_parquet(?,hive_partitioning=false) "
                             "WHERE exchange='SSE' AND is_open AND trade_date=?",
                             [str(silver_trade_calendar_path(root)), now.date()]).fetchone()[0]
    if not opened:
        return dg.SensorResult(skip_reason=dg.SkipReason("非交易日，不请求周/月源。"))
    deadline = time.monotonic() + DEFAULT_POLICY.timeout_seconds
    try:
        _period_inputs_ready(context.instance, business_date, [business_date])
        universe = load_period_universe(root, business_date, freq)
        status = probe_stock_period_source(freq=freq, business_date=business_date,
            required_codes=universe["required"], optional_codes=universe["optional"],
            aliases=universe["aliases"], deadline=deadline)
        status["reference_versions"] = universe["reference_versions"]
    except (ValueError, OSError) as error:
        status = {"ready": False, "reason": str(error) if str(error).startswith("period_") else "period_inputs_unavailable"}
    details = build_cursor_details(
        sensor_name=f"raw_stock_{'weekly' if freq == 'week' else 'monthly'}_update_job_sensor",
        job_name=job, asset_family="stock_period", partition_set="cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months",
        reason_code=status["reason"], blocked_component="none" if status["ready"] else "source_readiness",
        summary="当日非全日停牌股票的源数据齐备。" if status["ready"] else "源端或前置事实未齐，等待下一次检查。",
        next_action="等待本频Raw及原检查。" if status["ready"] else "后续tick重新核验当天。", evidence=status,
    )
    cursor = build_sensor_cursor(evaluated_at=now, decision="request_runs" if status["ready"] else "skip",
                                 target_date=business_date, selected_count=int(status["ready"]), details=details)
    if not status["ready"]:
        return dg.SensorResult(skip_reason=dg.SkipReason(status["reason"]), cursor=cursor)
    partitions = cn_a_stock_week_ends if freq == "week" else cn_a_stock_months
    return dg.SensorResult(run_requests=[build_run_request(run_key=run_key, job_name=job, partition_key=period,
        run_config=build_stock_period_run_config(freq, business_date))],
        dynamic_partitions_requests=[partitions.build_add_request([period])], cursor=cursor)
