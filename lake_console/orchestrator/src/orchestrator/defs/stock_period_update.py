"""Daily period backlog, adjacent factor notifications and direct asset execution."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs.io.stock_period_raw import (
    atomic_json,
    check_cancel,
    connection,
    execute,
    read_json,
    safe_path,
)
from orchestrator.defs.run_contracts.stock_period import (
    DEFAULT_POLICY,
    VERSION,
    digest,
    execution_id,
    next_period,
    period_date,
    period_for,
)


def daily_periods(*, today, freq, completed_through, last_refresh=None):
    """One request per outstanding period, then current; no per-day price replay."""
    current = period_for(today, freq)
    if completed_through is None:
        raise ValueError("period_baseline_watermark_missing")
    output = []
    period = next_period(completed_through, freq)
    while period < current:
        output.append(period)
        period = next_period(period, freq)
    if last_refresh != today.isoformat():
        output.append(current)
    return list(dict.fromkeys(output))


class CalendarDays(list):
    def __init__(self, rows):
        normalized = [
            (day.isoformat() if isinstance(day, date) else str(day), opened)
            for day, opened in rows
        ]
        super().__init__(day for day, opened in normalized if opened == 1)
        self.covered = {day for day, _ in normalized}


def calendar_days(root, work, policy=DEFAULT_POLICY):
    from orchestrator.defs.paths import silver_trade_calendar_path

    with connection(work, policy) as con:
        return CalendarDays(
            con.execute(
                "SELECT cal_date,is_open FROM read_parquet(?) WHERE exchange='SSE' ORDER BY cal_date",
                [str(safe_path(silver_trade_calendar_path(root)))],
            ).fetchall()
        )


def period_bounds(period, freq):
    text = period_date(period, freq)
    end = date(int(text[:4]), int(text[4:6]), int(text[6:]))
    return (end - timedelta(days=4) if freq == "week" else end.replace(day=1)), end


def no_trading_period(period, freq, days):
    first, last = period_bounds(period, freq)
    if any(first.isoformat() <= d <= last.isoformat() for d in days):
        return False
    required = {
        (first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)
    }
    if not required.issubset(getattr(days, "covered", set())):
        raise ValueError("period_calendar_coverage_missing")
    return True


def source_final(period, freq, asof, today, days):
    if not asof:
        return False
    first, last = period_bounds(period, freq)
    observed = asof[:4] + "-" + asof[4:6] + "-" + asof[6:]
    required = {
        (first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)
    }
    if not required.issubset(getattr(days, "covered", set())):
        return False
    final = close_day(period, freq, days)
    return today.isoformat() >= final and observed >= final


def factor_changes(
    root,
    work,
    days,
    after,
    through,
    listed,
    policy=DEFAULT_POLICY,
    cancel=lambda: False,
    progress=lambda _: None,
):
    """Each unconsumed adjacent trading-day pair once; never compare complete price history."""
    from orchestrator.defs.paths import silver_adj_factor_path
    from orchestrator.defs.stock_daily_qfq import (
        build_stock_daily_qfq_factor_changed_codes_sql,
    )

    if after is None:
        raise ValueError("period_factor_watermark_missing")
    selected = [day for day in days if after < day <= through]
    changed = set()
    with connection(work, policy) as con:
        for day in selected:
            previous = days[days.index(day) - 1] if days.index(day) > 0 else None
            if previous is None:
                continue
            current_path = safe_path(silver_adj_factor_path(root, day))
            prior_path = safe_path(silver_adj_factor_path(root, previous))
            if not current_path.is_file() or not prior_path.is_file():
                raise ValueError("period_adjacent_factor_missing")
            changed.update(
                r[0]
                for r in execute(
                    con,
                    build_stock_daily_qfq_factor_changed_codes_sql(
                        current_adj_factor_path=current_path,
                        previous_adj_factor_path=prior_path,
                    ),
                    policy=policy,
                    cancel=cancel,
                    progress=progress,
                    stage="adjacent_factor_changes",
                ).fetchall()
            )
    return sorted(changed & set(listed))


def close_day(period, freq, days):
    anchor = period_date(period, freq)
    boundary = date(int(anchor[:4]), int(anchor[4:6]), int(anchor[6:]))
    first, _ = period_bounds(period, freq)
    candidates = [d for d in days if first.isoformat() <= d <= boundary.isoformat()]
    if not candidates:
        raise ValueError("period_calendar_no_trading_day")
    return candidates[-1]


def daily_state(staging):
    path = Path(staging) / "stock_period" / "daily.json"
    return read_json(path) if path.exists() else None


def bootstrap_watermarks(today, days):
    # First baseline has no older debt; current periods are deliberately left open.
    result = {
        "factor_through": today.isoformat(),
        "last_refresh": {},
        "completed_through": {},
    }
    for freq in ("week", "month"):
        current = period_for(today, freq)
        if source_final(
            current, freq, today.strftime("%Y%m%d"), today, days
        ) or no_trading_period(current, freq, days):
            result["completed_through"][freq] = current
        else:
            day = date.fromisoformat(current if freq == "week" else current + "-01")
            prior = day - timedelta(days=7 if freq == "week" else 1)
            result["completed_through"][freq] = period_for(prior, freq)
    return result


def confirmed_retirements(root, work, removed, aliases):
    if not removed:
        return []
    from orchestrator.defs.paths import raw_stock_basic_path

    source_codes = sorted(
        set(removed) | {old for old, new in aliases.items() if new in removed}
    )
    with connection(work) as con:
        rows = con.execute(
            "SELECT ts_code FROM read_parquet(?) WHERE list_status='D' AND list_contains(?,ts_code)",
            [str(safe_path(raw_stock_basic_path(root))), source_codes],
        ).fetchall()
    return sorted({aliases.get(r[0], r[0]) for r in rows} & set(removed))


def _daily_work(
    staging, *, root, today, freq, listed, aliases, days, policy, cancel, progress
):
    state = daily_state(staging)
    pending = daily_periods(
        today=today,
        freq=freq,
        completed_through=state["completed_through"][freq],
        last_refresh=state["last_refresh"].get(freq),
    )
    holidays = [p for p in pending if no_trading_period(p, freq, days)]
    requested = [p for p in pending if p not in holidays]
    baseline = read_json(Path(staging) / "stock_period/baseline.json")
    if (
        not pending
        and state["factor_through"] >= today.isoformat()
        and set(baseline["listed"]) == set(listed)
    ):
        return None
    changed = set(
        factor_changes(
            root,
            Path(staging) / "stock_period/factors",
            days,
            state["factor_through"],
            today.isoformat(),
            listed,
            policy,
            cancel,
            progress,
        )
    )
    changed.update(set(listed) - set(baseline["listed"]))
    retired = confirmed_retirements(
        root,
        Path(staging) / "stock_period/scope",
        {
            c
            for c in baseline["listed"]
            if c not in listed and aliases.get(c, c) not in listed
        },
        aliases,
    )
    superseded = sorted(
        c for c in baseline["listed"] if c not in listed and aliases.get(c, c) in listed
    )
    if not (requested or changed or retired or superseded or holidays):
        return None
    intent = {
        "version": VERSION,
        "mode": "upsert" if requested else "history",
        "frequencies": ["week", "month"]
        if changed or retired or superseded
        else [freq],
        "codes": sorted(changed),
        "retired_codes": retired,
        "superseded_codes": superseded,
        "periods": {freq: requested},
        "asof": today.isoformat(),
        "request_id": digest(
            {"kind": "period_daily", "frequency": freq, "date": today.isoformat()}
        ),
        "period_cutoffs": {
            freq: {
                p: min(today.isoformat(), close_day(p, freq, days)).replace("-", "")
                for p in requested
            }
        },
    }
    return {
        "intent": intent,
        "listed": sorted(listed),
        "aliases": aliases,
        "confirmed_retired": retired,
        "frequency": freq,
        "pending": pending,
        "holidays": holidays,
        "consumed": False,
        "policy": policy.payload(),
    }


def _consume_daily_files(staging, work, result, days):
    path = Path(staging) / "stock_period/daily.json"
    state = daily_state(staging)
    intent, freq = work["intent"], work["frequency"]
    today = date.fromisoformat(intent["asof"])
    observations = result.get("unit_asofs", {}).get(freq, {})
    current = period_for(today, freq)
    if (
        observations.get(current)
        and observations[current] >= intent["asof"].replace("-", "")
        and state["last_refresh"].get(freq, "") <= intent["asof"]
    ):
        state["last_refresh"][freq] = intent["asof"]
        state.setdefault("last_source_asof", {})[freq] = observations[current]
    frontier = state["completed_through"][freq]
    for period in work["pending"]:
        if period != next_period(frontier, freq):
            break
        if period in work["holidays"] or source_final(
            period, freq, observations.get(period), today, days
        ):
            frontier = period
        else:
            break
    state["completed_through"][freq] = frontier
    state["factor_through"] = max(state["factor_through"], intent["asof"])
    work["consumed"] = True
    state.setdefault("pending_work", {})[execution_id(intent["request_id"])] = work
    baseline_path = Path(staging) / "stock_period/baseline.json"
    baseline = read_json(baseline_path)
    baseline["listed"] = work["listed"]
    atomic_json(baseline_path, baseline)
    atomic_json(path, state)


def _execute_daily_locked(
    *,
    root,
    staging,
    today,
    freq,
    listed,
    aliases,
    transport=None,
    policy=DEFAULT_POLICY,
    cancel=lambda: False,
    progress=lambda _: None,
    events=None,
):
    """Resume frozen file/event work before planning a new date or reading factors."""
    from orchestrator.defs.bootstrap.stock_period_history import (
        replay_events,
        run_period,
    )
    from orchestrator.defs.run_contracts.stock_period import StockPeriodPolicy

    state = daily_state(staging)
    if state is None:
        raise ValueError("period_daily_handoff_required")
    results = []
    days = None

    def perform(work):
        nonlocal days
        check_cancel(cancel)
        intent = work["intent"]
        work_policy = StockPeriodPolicy(**work["policy"])
        calendar_only = not (
            any(intent.get("periods", {}).values())
            or intent.get("codes")
            or intent.get("retired_codes")
            or intent.get("superseded_codes")
        )
        if calendar_only:
            days = days or calendar_days(
                root,
                Path(staging) / "stock_period/calendar",
                work_policy,
            )
            _consume_daily_files(staging, work, {"unit_asofs": {}}, days)
            latest = daily_state(staging)
            latest.get("pending_work", {}).pop(execution_id(intent["request_id"]), None)
            atomic_json(Path(staging) / "stock_period/daily.json", latest)
            return
        result = run_period(
            root=root,
            staging=staging,
            intent=intent,
            listed=set(work["listed"]),
            aliases=work["aliases"],
            confirmed_retired=work["confirmed_retired"],
            transport=transport,
            policy=work_policy,
            cancel=cancel,
            progress=progress,
        )
        if not work["consumed"]:
            days = days or calendar_days(
                root, Path(staging) / "stock_period/calendar", work_policy
            )
            _consume_daily_files(staging, work, result, days)
        if events is not None:
            result = replay_events(
                Path(result["path"]),
                root=root,
                staging=staging,
                events=events,
                cancel=cancel,
            )
            if result["events_complete"]:
                latest = daily_state(staging)
                latest.get("pending_work", {}).pop(result["run_id"], None)
                atomic_json(Path(staging) / "stock_period/daily.json", latest)
        results.append(result)

    for work in list(state.get("pending_work", {}).values()):
        perform(work)
    days = days or calendar_days(root, Path(staging) / "stock_period/calendar", policy)
    if today.isoformat() not in days:
        if results:
            return results
        raise ValueError("period_not_trading_day")
    work = _daily_work(
        staging,
        root=root,
        today=today,
        freq=freq,
        listed=listed,
        aliases=aliases,
        days=days,
        policy=policy,
        cancel=cancel,
        progress=progress,
    )
    if work is not None:
        latest = daily_state(staging)
        run_id = execution_id(work["intent"]["request_id"])
        if run_id not in latest.get("pending_work", {}):
            latest.setdefault("pending_work", {})[run_id] = work
            atomic_json(Path(staging) / "stock_period/daily.json", latest)
            perform(work)
    return results


def execute_daily(**kwargs):
    from orchestrator.defs.bootstrap.stock_period_history import roots, writer

    roots(kwargs["root"], kwargs["staging"])
    with writer(kwargs["staging"]):
        return _execute_daily_locked(**kwargs)


def report_file_events(instance, item, *, write=True, context=None):
    """Report only validated immutable file versions; retry missing events without recompute."""
    import dagster as dg
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )

    from orchestrator.defs.io.stock_period_raw import file_version
    from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
    from orchestrator.defs.run_contracts.stock_monthly import (
        StockMonthlySource,
        monthly_check_names,
    )
    from orchestrator.defs.run_contracts.stock_period import FIELDS
    from orchestrator.defs.run_contracts.stock_weekly import (
        StockWeeklySource,
        weekly_check_names,
    )

    if file_version(item["target"]) != item["version"]:
        raise ValueError("period_event_file_changed")
    from orchestrator.defs.io.stock_period_raw import audit_file

    evidence = audit_file(Path(item["target"]).parents[4], item["freq"], item["period"])
    if evidence["rows"] != item["rows"] or evidence["sha256"] != item["sha256"]:
        raise ValueError("period_event_receipt_mismatch")
    freq = item["freq"]
    asset = dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}")
    names = (
        weekly_check_names(StockWeeklySource.PRIMARY_ADJUSTED)
        if freq == "week"
        else monthly_check_names(StockMonthlySource.PRIMARY_ADJUSTED)
    )
    partition = item["period"]
    partset = "cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months"
    if write:
        instance.add_dynamic_partitions(partset, [partition])
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[partition]), limit=1
    ).records
    record = records[0] if records else None
    fingerprint = (
        getattr(
            record.asset_materialization.metadata.get(
                "goldenshare/period_file_version"
            ),
            "value",
            None,
        )
        if record
        else None
    )
    if fingerprint != item["version"]:
        if not write:
            return False
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=asset,
                partition=partition,
                metadata=build_materialization_metadata(
                    uri=item["target"],
                    row_count=item["rows"],
                    observed_columns=FIELDS,
                    extra_metadata={
                        "goldenshare/period_file_version": dg.MetadataValue.json(
                            item["version"]
                        )
                    },
                ),
            )
        )
        record = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[partition]),
            limit=1,
        ).records[0]
    from dagster._core.event_api import PartitionKeyFilter
    from dagster._core.storage.asset_check_execution_record import (
        COMPLETED_ASSET_CHECK_EXECUTION_RECORD_STATUSES,
    )

    for name in names:
        history = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(asset, name),
            limit=1,
            status=COMPLETED_ASSET_CHECK_EXECUTION_RECORD_STATUSES,
            partition_filter=PartitionKeyFilter(key=partition),
        )
        evaluation = history[0].evaluation if history else None
        matched = (
            evaluation is not None
            and evaluation.partition == partition
            and evaluation.passed
            and evaluation.blocking
            and evaluation.target_materialization_data is not None
            and evaluation.target_materialization_data.storage_id == record.storage_id
        )
        if matched:
            continue
        if not write:
            return False
        if context is None:
            raise ValueError("period_event_real_run_required")
        from dagster._core.events import DagsterEvent, DagsterEventType

        op_context = getattr(context, "op_execution_context", context)
        instance.report_dagster_event(
            DagsterEvent(
                event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
                job_name=op_context.job_name,
                step_key=op_context.get_step_execution_context().step.key,
                event_specific_data=AssetCheckEvaluation(
                    asset_key=asset,
                    check_name=name,
                    partition=partition,
                    passed=True,
                    blocking=True,
                    target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                        storage_id=record.storage_id,
                        run_id=record.event_log_entry.run_id,
                        timestamp=record.event_log_entry.timestamp,
                    ),
                ),
            ),
            run_id=op_context.run_id,
        )
    return True


def deliver_asset(context, config, lake_root, freq):
    import dagster as dg

    from orchestrator.defs.bootstrap.stock_period_history import load_scope, run_period
    from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
    from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
    from orchestrator.defs.run_contracts.stock_period import FIELDS

    root = lake_root.root()
    staging = Path(DEFAULT_LAKE_STAGING_ROOT)
    lake_root.ensure_available_for_run()
    listed, aliases = load_scope(root, staging / "stock_period" / "scope")

    import time

    checked_at, cancelled = float("-inf"), False

    def cancel():
        nonlocal checked_at, cancelled
        if time.monotonic() - checked_at >= 2:
            checked_at = time.monotonic()
            run = context.instance.get_run_by_id(context.run.run_id)
            cancelled = run is not None and run.status in (
                dg.DagsterRunStatus.CANCELING,
                dg.DagsterRunStatus.CANCELED,
            )
        return cancelled

    def events(item):
        return report_file_events(
            context.instance,
            item,
            write=(item["freq"], item["period"]) != (freq, context.partition_key),
            context=context,
        )

    progress = lambda p: context.log.info(str(p))
    if config.intent == "history":
        results = [
            run_period(
                root=root,
                staging=staging,
                listed=listed,
                aliases=aliases,
                intent={
                    "version": VERSION,
                    "mode": "history",
                    "frequencies": ["week", "month"],
                    "codes": sorted(set(config.stock_codes)),
                    "request_id": config.request_id,
                },
                cancel=cancel,
                progress=progress,
                events=events,
            )
        ]
    else:
        today = (
            date.fromisoformat(config.automatic_intent_date)
            if config.automatic_intent_date
            else datetime.now(ZoneInfo("Asia/Shanghai")).date()
        )
        results = execute_daily(
            root=root,
            staging=staging,
            today=today,
            freq=freq,
            listed=listed,
            aliases=aliases,
            cancel=cancel,
            progress=progress,
            events=events,
        )
    items = [
        i
        for result in results
        for i in result["files"]
        if (i["freq"], i["period"]) == (freq, context.partition_key)
    ]
    if not items:
        if config.intent == "history":
            raise ValueError("period_asset_anchor_not_written")
        from orchestrator.defs.io.stock_period_raw import audit_file, target_path

        items = [
            {
                "target": str(target_path(root, freq, context.partition_key)),
                **audit_file(root, freq, context.partition_key),
            }
        ]
    item = items[-1]
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=item["target"],
            row_count=item["rows"],
            observed_columns=FIELDS,
            extra_metadata={
                "goldenshare/period_file_version": dg.MetadataValue.json(
                    item["version"]
                )
            },
        )
    )


def evaluate_daily_sensor(context, now, *, freq, staging_root=None):
    import dagster as dg

    from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
    from orchestrator.defs.run_contracts.configs import build_stock_period_run_config
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

    staging = Path(staging_root or DEFAULT_LAKE_STAGING_ROOT)
    now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    if (now.hour, now.minute) < (19, 30):
        return dg.SensorResult(skip_reason=dg.SkipReason("尚未到上海时间19:30。"))
    asset = f"raw_tushare_stk_period_bar_adj_{freq}"
    job = f"raw_stk_period_bar_adj_{freq}_update_job"
    statuses = [
        dg.DagsterRunStatus.NOT_STARTED,
        dg.DagsterRunStatus.QUEUED,
        dg.DagsterRunStatus.STARTING,
        dg.DagsterRunStatus.STARTED,
        dg.DagsterRunStatus.CANCELING,
    ]
    for other in ("week", "month"):
        if context.instance.get_runs(
            filters=dg.RunsFilter(
                job_name=f"raw_stk_period_bar_adj_{other}_update_job", statuses=statuses
            ),
            limit=1,
        ):
            return dg.SensorResult(
                skip_reason=dg.SkipReason("周/月Raw已有写者，保留原水位等待。")
            )
    baseline = staging / "stock_period" / "baseline.json"
    state = daily_state(staging)
    if (
        not baseline.exists()
        or read_json(baseline).get("status") != "ready"
        or state is None
    ):
        return dg.SensorResult(
            skip_reason=dg.SkipReason(
                "新源bootstrap尚未交接，保留旧cursor，不提交任务。"
            )
        )
    import tempfile

    from orchestrator.defs.duckdb_connection import (
        DuckDBConnectionSettings,
        connect_configured_duckdb,
    )
    from orchestrator.defs.paths import silver_trade_calendar_path

    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=Path(tempfile.gettempdir()).resolve()),
        temp_policy="existing_no_spill",
    ) as con:
        open_today = con.execute(
            "SELECT count(*) FROM read_parquet(?) WHERE exchange='SSE' AND is_open=1 AND cal_date=?",
            [
                str(silver_trade_calendar_path(context.resources.lake_root.root())),
                now.date(),
            ],
        ).fetchone()[0]
    if not open_today:
        return dg.SensorResult(skip_reason=dg.SkipReason("非交易日，不请求周/月源。"))
    pending = daily_periods(
        today=now.date(),
        freq=freq,
        completed_through=state["completed_through"][freq],
        last_refresh=state["last_refresh"].get(freq),
    )
    if not pending and not state.get("pending_work"):
        return dg.SensorResult(
            skip_reason=dg.SkipReason("当天已刷新；周期完成水位保持独立。")
        )
    # One asset run processes deduplicated backlog before current. Anchor is always the current partition.
    anchor = period_for(now.date(), freq)
    partname = "cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months"
    from orchestrator.defs.partitions import cn_a_stock_months, cn_a_stock_week_ends

    partitions = cn_a_stock_week_ends if freq == "week" else cn_a_stock_months
    request = build_run_request(
        run_key=build_asset_update_run_key(
            subject=asset, unit_id=now.date().isoformat()
        ),
        job_name=job,
        partition_key=anchor,
        run_config=build_stock_period_run_config(freq, now.date().isoformat()),
    )
    old = cursor_runtime_state(
        sensor_cursor_details(load_sensor_cursor(context.cursor))
    )
    details = build_cursor_details(
        sensor_name=f"raw_stock_{'weekly' if freq == 'week' else 'monthly'}_update_job_sensor",
        job_name=job,
        asset_family="stock_period",
        partition_set=partname,
        reason_code="direct_source_request",
        blocked_component="none",
        summary="先补欠账，再更新当前周期。",
        next_action="等待源交付及文件检查。",
        runtime_state={
            **old,
            "source_policy": VERSION,
            "direct_completed_through": state["completed_through"][freq],
        },
        evidence={
            "pending_periods": pending,
            "daily_intent_date": now.date().isoformat(),
        },
    )
    return dg.SensorResult(
        run_requests=[request],
        dynamic_partitions_requests=[partitions.build_add_request([anchor])],
        cursor=build_sensor_cursor(
            evaluated_at=now,
            decision="request_runs",
            target_date=anchor,
            selected_count=1,
            details=details,
        ),
    )


def handoff_bootstrap(
    *,
    root,
    staging,
    run,
    events,
    transport=None,
    listed=None,
    aliases=None,
    through=None,
    now=None,
    cancel=lambda: False,
    progress=lambda _: None,
):
    """One frozen catch-up intent for the actual capture interval, then ready."""
    from orchestrator.defs.bootstrap.stock_period_history import (
        load_scope,
        replay_events,
        roots,
        run_period,
        writer,
    )
    from orchestrator.defs.run_contracts.stock_period import (
        StockPeriodPolicy,
        verify_execution,
    )

    root, staging = roots(root, staging)
    with writer(staging):
        run = safe_path(run)
        parent = read_json(run / "manifest.json")
        verify_execution(parent, run.name)
        if parent["identity"]["intent"]["mode"] != "bootstrap" or parent["identity"][
            "root"
        ] != str(root):
            raise ValueError("period_handoff_parent_invalid")
        baseline_path = staging / "stock_period/baseline.json"
        baseline = read_json(baseline_path)
        statepath = staging / "stock_period/daily.json"
        prior = read_json(statepath) if statepath.exists() else {}
        if baseline.get("run_id") != run.name:
            raise ValueError("period_handoff_baseline_changed")
        if (
            baseline.get("status") == "ready"
            and prior.get("baseline_run_id") == run.name
        ):
            return prior
        if parent["phase"] != "events_complete":
            raise ValueError("period_handoff_events_incomplete")
        policy = StockPeriodPolicy(**parent["identity"]["policy"])
        days = calendar_days(root, staging / "stock_period/calendar", policy)
        now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
        now = now.astimezone(ZoneInfo("Asia/Shanghai"))
        released = [
            d
            for d in days
            if d < now.date().isoformat()
            or (d == now.date().isoformat() and (now.hour, now.minute) >= (19, 30))
        ]
        if not released:
            raise ValueError("period_handoff_calendar_missing")
        cutoff = through.isoformat() if through else released[-1]
        if cutoff not in released:
            raise ValueError("period_handoff_cutoff_not_released")
        if "handoff" not in parent:
            started = datetime.fromisoformat(parent["started_at"]).astimezone(
                ZoneInfo("Asia/Shanghai")
            )
            started_days = [
                d
                for d in days
                if d < started.date().isoformat()
                or (
                    d == started.date().isoformat()
                    and (started.hour, started.minute) >= (19, 30)
                )
            ]
            if not started_days or cutoff < started_days[-1]:
                raise ValueError("period_handoff_calendar_missing")
            begin = started_days[-1]
            if listed is None:
                listed, aliases = load_scope(
                    root, staging / "stock_period/scope", policy
                )
            aliases = aliases or {}
            original = set(parent["identity"]["listed"])
            changed = set(
                factor_changes(
                    root,
                    staging / "stock_period/factors",
                    days,
                    begin,
                    cutoff,
                    listed,
                    policy,
                    cancel,
                    progress,
                )
            ) | (set(listed) - original)
            retired = confirmed_retirements(
                root,
                staging / "stock_period/scope",
                {
                    c
                    for c in original
                    if c not in listed and aliases.get(c, c) not in listed
                },
                aliases,
            )
            superseded = sorted(
                c for c in original if c not in listed and aliases.get(c, c) in listed
            )
            unexplained = original - set(listed) - set(retired) - set(superseded)
            if unexplained:
                raise ValueError("period_handoff_scope_difference_unconfirmed")
            periods = {
                f: sorted(
                    {
                        period_for(date.fromisoformat(d), f)
                        for d in days
                        if begin <= d <= cutoff
                    }
                )
                for f in ("week", "month")
            }
            intent = {
                "version": VERSION,
                "mode": "upsert",
                "frequencies": ["week", "month"],
                "codes": sorted(changed),
                "retired_codes": retired,
                "superseded_codes": superseded,
                "periods": periods,
                "asof": cutoff,
                "bootstrap_parent": run.name,
                "request_id": digest(
                    {"kind": "period_handoff", "parent": run.name, "cutoff": cutoff}
                ),
                "period_cutoffs": {
                    f: {
                        p: min(cutoff, close_day(p, f, days)).replace("-", "")
                        for p in periods[f]
                    }
                    for f in periods
                },
            }
            parent["handoff"] = {
                "intent": intent,
                "listed": sorted(listed),
                "aliases": aliases,
                "confirmed_retired": retired,
                "begin": begin,
                "cutoff": cutoff,
            }
            atomic_json(run / "manifest.json", parent)
        work = parent["handoff"]
        cutoff = work["cutoff"]
        result = run_period(
            root=root,
            staging=staging,
            intent=work["intent"],
            listed=set(work["listed"]),
            aliases=work["aliases"],
            confirmed_retired=work["confirmed_retired"],
            transport=transport,
            policy=policy,
            cancel=cancel,
            progress=progress,
        )
        result = replay_events(
            Path(result["path"]),
            root=root,
            staging=staging,
            events=events,
            cancel=cancel,
        )
        if not result["events_complete"]:
            raise ValueError("period_handoff_events_incomplete")
        # The child verifies published current/ended periods and all scope/factor work.
        state = bootstrap_watermarks(date.fromisoformat(cutoff), days)
        state.update(
            baseline_run_id=run.name,
            handoff_cutoff=cutoff,
            last_refresh={f: cutoff for f in ("week", "month")},
        )
        if prior.get("baseline_run_id") == run.name:
            state["factor_through"] = max(
                state["factor_through"], prior.get("factor_through", "")
            )
            for f in ("week", "month"):
                state["completed_through"][f] = max(
                    state["completed_through"][f],
                    prior.get("completed_through", {}).get(f, ""),
                )
                state["last_refresh"][f] = max(
                    cutoff, prior.get("last_refresh", {}).get(f, "")
                )
            state["pending_work"] = prior.get("pending_work", {})
        atomic_json(statepath, state)
        baseline = read_json(baseline_path)
        baseline.update(status="ready", listed=work["listed"], handoff_cutoff=cutoff)
        atomic_json(baseline_path, baseline)
        parent["handoff_complete"] = True
        atomic_json(run / "manifest.json", parent)
        return state
