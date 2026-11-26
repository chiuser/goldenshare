"""Stock period history: explicit inputs and native delivery."""

import csv
import tempfile
import time
from ast import literal_eval
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.asset_guards.stock_period_delivery import (
    native_run_records,
    read_completions,
)
from orchestrator.defs.asset_guards.stock_period_silver_readiness import raw_check_names
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_period_raw import (
    _BUDGET,
    DEFAULT_POLICY,
    FIELDS,
    StorageBudget,
    assemble_history_maintenance_period,
    assemble_history_period,
    check_cancel,
    count_maintenance_rows,
    durable_directory,
    file_version,
    group_history_sources,
    process_memory_budget,
    publish_period,
    safe_path,
    target_path,
)
from orchestrator.defs.paths import (
    silver_adj_factor_path,
    silver_stock_basic_path,
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from orchestrator.defs.run_contracts.stock_period import (
    admitted_code,
    period_for,
    source_period,
)
from orchestrator.defs.run_contracts.stock_period_delivery import (
    BUSINESS_DATE_TAG,
    COMPLETION_KEY,
    FILE_DELIVERY_KEY,
    KIND_TAG,
    RAW_DAILY_JOBS,
    WORK_KEY,
    delivery_completion,
    delivery_ref,
    delivery_work,
    period_run_tags,
    raw_daily_run_intent,
)
from orchestrator.defs.run_contracts.stock_period_history_repair import (
    FREQUENCIES,
    JOB_NAME,
    OP_NAME,
    StockPeriodHistoryRepairConfig,
    build_history_repair_run_config,
    repair_upstream_batch_id,
)
from orchestrator.defs.stock_daily_qfq import (
    build_stock_daily_qfq_factor_changed_codes_sql,
    gold_stock_daily_qfq_factor_repair_codes_hash,
)


def load_factor_changed_codes(root, business_date):
    """Reuse the accepted factor producer and comparison; no repeated acceptance gate."""
    current = silver_adj_factor_path(root, business_date)
    calendar, lifecycle = (
        silver_trade_calendar_path(root),
        silver_stock_lifecycle_path(root),
    )
    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=Path(tempfile.gettempdir()).resolve()),
        temp_policy="existing_no_spill",
    ) as con:
        previous, is_open = con.execute(
            "SELECT max(trade_date) FILTER(WHERE trade_date<?),count(*) FILTER(WHERE trade_date=? AND is_open) "
            "FROM read_parquet(?,hive_partitioning=false) WHERE exchange='SSE' AND is_open AND trade_date<=?",
            [business_date, business_date, str(calendar), business_date],
        ).fetchone()
        if not is_open or previous is None:
            raise ValueError("period_repair_adjacent_trading_days_missing")
        prior = silver_adj_factor_path(root, previous.isoformat())
        references = [current, prior, lifecycle, calendar]
        versions = [file_version(p) for p in references]
        codes = sorted(
            row[0]
            for row in con.execute(
                build_stock_daily_qfq_factor_changed_codes_sql(
                    current_adj_factor_path=current,
                    previous_adj_factor_path=prior,
                    silver_stock_lifecycle_path=lifecycle,
                    trade_date=business_date,
                )
            ).fetchall()
            if row[1] == "factor_changed"
        )
        if versions != [file_version(p) for p in references]:
            raise ValueError("period_repair_factor_inputs_changed")
    return codes


def evaluate_history_repair_sensor(context, lake_root):
    run = context.dagster_run
    if run.job_name not in RAW_DAILY_JOBS:
        return dg.SkipReason("period_repair_unmonitored_job")
    try:
        freq, day = raw_daily_run_intent(run)
        other = "month" if freq == "week" else "week"
        others = context.instance.get_runs(
            filters=dg.RunsFilter(
                job_name=f"raw_stk_period_bar_adj_{other}_update_job",
                statuses=[dg.DagsterRunStatus.SUCCESS],
                tags={BUSINESS_DATE_TAG: day, KIND_TAG: "daily"},
            ),
            limit=1,
        )
        if not others:
            return dg.SkipReason("period_repair_waiting_other_frequency")
        other_freq, other_day = raw_daily_run_intent(others[0])
        if other_freq != other or other_day != day:
            raise ValueError("period_repair_daily_date_mismatch")
        runs = {freq: run, other: others[0]}
        refs = [
            delivery_ref(
                runs[f].run_id,
                f,
                "daily",
                day,
                [period_for(date.fromisoformat(day), f)],
            )
            for f in FREQUENCIES
        ]
        root = lake_root.root()
        read_completions(context.instance, refs, root=root)
        codes = load_factor_changed_codes(root, day)
        config = StockPeriodHistoryRepairConfig(
            business_date=day,
            stock_codes=codes,
            codes_hash=gold_stock_daily_qfq_factor_repair_codes_hash(codes),
            frequencies=FREQUENCIES,
            upstream_completions=refs,
        )
        from orchestrator.defs.run_contracts.requests import build_run_request
        from orchestrator.defs.run_contracts.run_keys import (
            build_upstream_triggered_run_key,
        )

        return build_run_request(
            run_key=build_upstream_triggered_run_key(
                consumer=JOB_NAME, upstream_batch_id=repair_upstream_batch_id(config)
            ),
            run_config=build_history_repair_run_config(config),
        )
    except (ValueError, KeyError, FileNotFoundError) as error:
        return dg.SkipReason(str(error))


def load_history_maintenance_scope(root, config):
    """Read only the requested identities and current source-refresh codes."""
    wanted = sorted(
        set(config.stock_codes) | {k["ts_code"] for k in config.remove_keys}
    )
    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=Path(tempfile.gettempdir()).resolve()),
        temp_policy="existing_no_spill",
    ) as con:
        identities = con.execute(
            "SELECT source_ts_code,latest_ts_code FROM read_parquet(?,hive_partitioning=false) "
            "WHERE confidence='confirmed' AND (list_contains(?,source_ts_code) OR list_contains(?,latest_ts_code))",
            [str(silver_stock_identity_map_path(root)), wanted, wanted],
        ).fetchall()
        aliases = dict(identities)
        aliases.update({latest: latest for _, latest in identities})
        if any(k["ts_code"] not in aliases for k in config.remove_keys):
            raise ValueError("period_maintenance_identity_unconfirmed")
        if config.stock_codes:
            listed = {
                r[0]
                for r in con.execute(
                    "SELECT ts_code FROM read_parquet(?,hive_partitioning=false) "
                    "WHERE list_contains(?,ts_code) AND curr_type='CNY' AND list_status='L'",
                    [str(silver_stock_basic_path(root)), config.stock_codes],
                ).fetchall()
            }
            for code in config.stock_codes:
                admitted_code(code, listed, aliases)
    return aliases


def _validate_upstreams(instance, root, config):
    origins = read_completions(instance, config.upstream_completions, root=root)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    if config.business_date > today:
        raise ValueError("period_repair_future_business_date")
    for freq, reference in zip(FREQUENCIES, config.upstream_completions, strict=True):
        origin = origins[reference["upstream_batch_id"]]
        period = period_for(date.fromisoformat(config.business_date), freq)
        item = origin["items"].get((freq, period))
        if item is None or item["asof"] < config.business_date:
            raise ValueError("period_repair_upstream_coverage_missing")
        completion = origin["completion"]
        if (
            completion["business_date"] == config.business_date
            and completion["kind"] == "daily"
        ):
            continue
        # Explicit original-day repair may use a later verified complete market delivery.
        from orchestrator.defs.source_readiness.stock_period import (
            check_period_rows,
            load_period_universe,
        )

        universe = load_period_universe(root, config.business_date, freq)
        with connect_configured_duckdb(
            DuckDBConnectionSettings(
                temp_directory=Path(tempfile.gettempdir()).resolve()
            ),
            temp_policy="existing_no_spill",
        ) as con:
            rows = con.execute(
                "SELECT ts_code,trade_date,end_date FROM read_parquet(?,hive_partitioning=false)",
                [item["target"]],
            ).fetchall()
        status = check_period_rows(
            rows,
            freq=freq,
            business_date=config.business_date,
            required_codes=universe["required"],
            optional_codes=universe["optional"],
            aliases=universe["aliases"],
            expected_dates=universe["expected_dates"],
            maximum_asof=today,
        )
        if not status["ready"]:
            raise ValueError("period_repair_upstream_coverage_missing")


def load_saved_week_pages(instance, staging, config, cancel):
    """Read a canceled run's complete, named week pages before preparing targets."""
    previous = instance.get_run_by_id(config.saved_source_run_id)
    if (
        previous is None
        or previous.job_name != JOB_NAME
        or previous.status != dg.DagsterRunStatus.CANCELED
    ):
        raise ValueError("period_saved_week_run_invalid")
    original = previous.run_config["ops"][OP_NAME]["config"]
    if (
        original.get("intent") != "factor_changed"
        or original.get("business_date") != config.business_date
        or original.get("stock_codes") != config.stock_codes
        or original.get("codes_hash") != config.codes_hash
        or original.get("frequencies") != FREQUENCIES
    ):
        raise ValueError("period_saved_week_run_scope_mismatch")
    root = safe_path(
        staging / "stock_period" / "runs" / previous.run_id / "source" / "week"
    )
    if {entry.name for entry in root.iterdir()} != set(config.stock_codes):
        raise ValueError("period_saved_week_stock_scope_mismatch")

    end_date = config.business_date.replace("-", "")
    last_week = period_for(date.fromisoformat(config.business_date), "week")
    code_index, date_index, end_index, freq_index = (
        FIELDS.index(name) for name in ("ts_code", "trade_date", "end_date", "freq")
    )
    periods = {}
    sources = []
    for code in config.stock_codes:
        check_cancel(cancel)
        folder = safe_path(root / code)
        page = safe_path(folder / "page-0.csv")
        if sorted(folder.glob("page-*.csv")) != [page] or not page.is_file():
            raise ValueError(f"period_saved_week_incomplete_page:{code}")
        before = file_version(page)
        seen = set()
        with page.open(newline="", encoding="utf-8") as handle:
            rows = csv.reader(handle)
            if tuple(next(rows, ())) != FIELDS:
                raise ValueError(f"period_saved_week_fields_invalid:{code}")
            for row in rows:
                if (
                    len(row) != len(FIELDS)
                    or row[code_index] != code
                    or row[freq_index] != "week"
                    or row[end_index] != end_date
                    or row[date_index] in seen
                ):
                    raise ValueError(f"period_saved_week_row_invalid:{code}")
                label = row[date_index]
                if label not in periods:
                    periods[label] = source_period(label, "week")
                if periods[label] > last_week:
                    raise ValueError(f"period_saved_week_future_period:{code}")
                seen.add(label)
        if not 0 < len(seen) < DEFAULT_POLICY.page_limit or file_version(page) != before:
            raise ValueError(f"period_saved_week_incomplete_page:{code}")
        sources.append(page)
    return sources


def saved_month_page_completions(instance, run_id):
    """Read just this run's source progress and identify terminal pages by stock."""
    completed, cursor, code = {}, None, None
    while True:
        page = instance.get_records_for_run(run_id, cursor=cursor, limit=1000)
        for record in page.records:
            message = record.event_log_entry.user_message
            if message.startswith("{'stage': 'history_source', 'freq': 'month',"):
                code = literal_eval(message)["code"]
            elif message.startswith("{'stage': 'source_page_complete', 'freq': 'month',"):
                event = literal_eval(message)
                count, rows = event["pages"], event["source_rows"]
                limit = DEFAULT_POLICY.page_limit
                if code is None or not 0 <= rows - (count - 1) * limit <= limit:
                    raise ValueError("period_saved_month_page_event_invalid")
                if rows and rows < count * limit:
                    completed[code] = count, rows
        if not page.has_more:
            return completed
        cursor = page.cursor


def validate_saved_month_pages(pages, code, expected_rows, latest_day, date_cache):
    """Check archived rows against the completed request before using them."""
    code_index, date_index, end_index, freq_index = (
        FIELDS.index(name) for name in ("ts_code", "trade_date", "end_date", "freq")
    )
    seen = set()
    limit = DEFAULT_POLICY.page_limit
    for index, page in enumerate(pages):
        before = file_version(page)
        previous_count = len(seen)
        with page.open(newline="", encoding="utf-8") as handle:
            rows = csv.reader(handle)
            if tuple(next(rows, ())) != FIELDS:
                raise ValueError(f"period_saved_month_fields_invalid:{code}")
            for row in rows:
                if (
                    len(row) != len(FIELDS)
                    or row[code_index] != code
                    or row[freq_index] != "month"
                    or row[date_index] in seen
                ):
                    raise ValueError(f"period_saved_month_row_invalid:{code}")
                label, asof = row[date_index], row[end_index]
                for value in (label, asof):
                    if value not in date_cache:
                        if len(value) != 8 or not value.isascii() or not value.isdigit():
                            raise ValueError(f"period_saved_month_date_invalid:{code}")
                        date_cache[value] = date.fromisoformat(value)
                if date_cache[asof] > latest_day:
                    raise ValueError(f"period_saved_month_future_source:{code}")
                seen.add(label)
        expected_page_rows = min(limit, expected_rows - index * limit)
        if len(seen) - previous_count != expected_page_rows or file_version(page) != before:
            raise ValueError(f"period_saved_month_page_rows_mismatch:{code}")


def load_saved_month_pages(instance, staging, config, cancel):
    """Bind archived pages to the original run and any interrupted month retries."""
    run_id = config.saved_source_run_id
    codes, visited, sources, date_cache = set(config.stock_codes), set(), {}, {}
    while True:
        check_cancel(cancel)
        previous = instance.get_run_by_id(run_id)
        if (
            run_id in visited
            or previous is None
            or previous.job_name != JOB_NAME
            or previous.status not in (dg.DagsterRunStatus.CANCELED, dg.DagsterRunStatus.FAILURE)
        ):
            raise ValueError("period_saved_month_run_invalid")
        visited.add(run_id)
        recorded = StockPeriodHistoryRepairConfig.model_validate(
            previous.run_config["ops"][OP_NAME]["config"]
        )
        if (
            recorded.business_date != config.business_date
            or recorded.stock_codes != config.stock_codes
            or recorded.codes_hash != config.codes_hash
        ):
            raise ValueError("period_saved_month_run_scope_mismatch")

        parent = recorded.saved_source_run_id
        if (
            recorded.intent == "factor_changed"
            and recorded.frequencies == FREQUENCIES
            and parent is None
            and previous.status == dg.DagsterRunStatus.CANCELED
        ):
            latest_day = date.fromisoformat(config.business_date)
        elif recorded.intent == "specified_history" and recorded.frequencies == ["month"] and parent:
            recorded.validate_intent()
            finished = instance.get_run_stats(run_id).end_time
            if finished is None:
                raise ValueError("period_saved_month_parent_end_missing")
            latest_day = datetime.fromtimestamp(finished, ZoneInfo("Asia/Shanghai")).date()
        else:
            raise ValueError("period_saved_month_run_scope_mismatch")

        completed = saved_month_page_completions(instance, run_id)
        if completed.keys() - codes:
            raise ValueError("period_saved_month_stock_scope_mismatch")
        root = safe_path(staging / "stock_period" / "runs" / run_id / "source" / "month")
        for code in sorted(completed.keys() - sources.keys()):
            check_cancel(cancel)
            count, rows = completed[code]
            folder = safe_path(root / code)
            pages = [
                safe_path(folder / f"page-{index * DEFAULT_POLICY.page_limit}.csv")
                for index in range(count)
            ]
            if set(folder.glob("page-*.csv")) != set(pages):
                raise ValueError(f"period_saved_month_pages_mismatch:{code}")
            validate_saved_month_pages(pages, code, rows, latest_day, date_cache)
            sources[code] = pages
        if parent is None:
            return sources
        run_id = parent


def execute_history_repair(context, config):
    """Build candidates in this run, optionally using explicitly saved source pages."""
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )

    from orchestrator.defs import paths
    from orchestrator.defs.bootstrap.stock_period_history import (
        check_devices,
        devices,
        roots,
        writer,
    )
    from orchestrator.defs.stock_period_source import HttpPage, capture_stock_history

    config.validate_intent()
    root_resource = context.resources.lake_root
    root_resource.ensure_available_for_run()
    root, staging = roots(root_resource.root(), Path(paths.DEFAULT_LAKE_STAGING_ROOT))
    frequencies = config.frequencies
    recover_month = bool(config.saved_source_run_id and frequencies == ["month"])
    kind = (
        "factor_repair" if config.intent == "factor_changed" else "history_maintenance"
    )
    if config.intent == "factor_changed":
        _validate_upstreams(context.instance, root, config)
        codes = load_factor_changed_codes(root, config.business_date)
        if (
            codes != config.stock_codes
            or gold_stock_daily_qfq_factor_repair_codes_hash(codes) != config.codes_hash
        ):
            raise ValueError("period_repair_codes_changed")
        aliases = None
    else:
        codes = config.stock_codes
        aliases = (
            {}
            if config.saved_source_run_id
            else load_history_maintenance_scope(root, config)
        )
    recovery_metadata = {}
    removal_metadata = (
        {"remove_keys": config.remove_keys, "remove_keys_hash": config.remove_keys_hash}
        if config.intent == "identity_maintenance"
        else {}
    )
    tags = period_run_tags(
        business_date=config.business_date,
        kind=kind,
        freq=frequencies[0] if len(frequencies) == 1 else None,
    )
    if config.saved_source_run_id:
        tags["goldenshare/stock_period_saved_source_run_id"] = config.saved_source_run_id
    context.instance.add_run_tags(context.run_id, tags)
    progress = lambda value: context.log.info(str(value))
    cancelled, last_checked = False, float("-inf")

    def cancel():
        nonlocal cancelled, last_checked
        if time.monotonic() - last_checked >= 2:
            last_checked = time.monotonic()
            run = context.instance.get_run_by_id(context.run_id)
            cancelled = run is not None and run.status in (
                dg.DagsterRunStatus.CANCELING,
                dg.DagsterRunStatus.CANCELED,
            )
        return cancelled

    completed, references, periods_by_freq = [], {}, {freq: [] for freq in frequencies}
    if codes or config.remove_keys:
        work = durable_directory(staging / "stock_period" / "runs" / context.run_id)
        captured_devices = devices(root, staging)
        with writer(staging), process_memory_budget(DEFAULT_POLICY):
            budget = StorageBudget(
                work, DEFAULT_POLICY, cancel=cancel, progress=progress
            )
            budget.guard = lambda: check_devices(root, staging, captured_devices)
            token = _BUDGET.set(budget)
            try:
                if aliases is None:
                    with connect_configured_duckdb(
                        DuckDBConnectionSettings(
                            temp_directory=Path(tempfile.gettempdir()).resolve()
                        ),
                        temp_policy="existing_no_spill",
                    ) as con:
                        identities = con.execute(
                            "SELECT source_ts_code,latest_ts_code FROM read_parquet(?,hive_partitioning=false) WHERE confidence='confirmed'",
                            [str(silver_stock_identity_map_path(root))],
                        ).fetchall()
                    aliases = dict(identities)
                    aliases.update({latest: latest for _, latest in identities})
                if config.saved_source_run_id and not recover_month:
                    sources = load_saved_week_pages(context.instance, staging, config, cancel)
                    progress({"stage": "history_saved_week_source", "stock_count": len(sources)})
                else:
                    saved = (
                        load_saved_month_pages(context.instance, staging, config, cancel)
                        if recover_month
                        else {}
                    )
                    pending = [code for code in codes if code not in saved]
                    if recover_month and pending:
                        aliases = load_history_maintenance_scope(
                            root, config.model_copy(update={"stock_codes": pending})
                        )
                    sources = [page for code in codes for page in saved.get(code, ())]
                    attempts = 0

                    def source_progress(event):
                        nonlocal attempts
                        if event["stage"] == "source_worker_started":
                            attempts += 1
                        progress(event)

                    if recover_month:
                        progress(
                            {
                                "stage": "history_saved_month_source",
                                "reused_stock_count": len(saved),
                                "pending_stock_count": len(pending),
                            }
                        )
                    transport = (
                        HttpPage(
                            cancel=cancel,
                            progress=source_progress if recover_month else progress,
                        )
                        if pending
                        else None
                    )
                    listed = set(pending)
                    for freq in frequencies:
                        for index, code in enumerate(pending):
                            progress(
                                {
                                    "stage": "history_source",
                                    "freq": freq,
                                    "code": code,
                                    "done": index,
                                    "total": len(pending),
                                }
                            )
                            sources.extend(
                                capture_stock_history(
                                    work=work / "source" / freq / code,
                                    freq=freq,
                                    code=code,
                                    listed=listed,
                                    aliases=aliases,
                                    transport=transport,
                                    cancel=cancel,
                                    progress=progress,
                                )
                            )
                    if recover_month:
                        recovery_metadata = {
                            "reused_stock_count": len(saved),
                            "fetched_stock_count": len(pending),
                            "source_page_count": len(sources),
                            "request_attempt_count": attempts,
                        }
                        progress({"stage": "history_month_source_complete", **recovery_metadata})
                groups = (
                    group_history_sources(
                        sources,
                        work=work / "groups",
                        root=root,
                        execution_date=datetime.now(ZoneInfo("Asia/Shanghai"))
                        .date()
                        .isoformat(),
                        **({"through_month": config.business_date[:7]} if recover_month else {}),
                        cancel=cancel,
                        progress=progress,
                    )
                    if sources
                    else []
                )
                grouped = {(g["freq"], g["period"]): g for g in groups}
                for key in config.remove_keys:
                    freq, period = (
                        key["freq"],
                        source_period(key["trade_date"], key["freq"]),
                    )
                    grouped.setdefault(
                        (freq, period), {"freq": freq, "period": period, "sources": []}
                    )
                groups = [grouped[k] for k in sorted(grouped)]
                missing = [
                    (g["freq"], g["period"])
                    for g in groups
                    if not target_path(root, g["freq"], g["period"]).is_file()
                ]
                if missing:
                    raise ValueError(f"period_history_market_files_missing:{missing}")
                for freq in frequencies:
                    periods = sorted(
                        group["period"] for group in groups if group["freq"] == freq
                    )
                    periods_by_freq[freq] = periods
                    if not periods:
                        continue
                    references[freq] = delivery_ref(
                        context.run_id,
                        freq,
                        kind,
                        config.business_date,
                        periods,
                    )
                    yield dg.AssetObservation(
                        asset_key=f"raw_tushare_stk_period_bar_adj_{freq}",
                        metadata={
                            WORK_KEY: dg.MetadataValue.json(
                                {
                                    **delivery_work(
                                        references[freq],
                                        kind=kind,
                                        business_date=config.business_date,
                                        periods=periods,
                                        stock_codes=codes,
                                        codes_hash=config.codes_hash,
                                        upstream_completions=config.upstream_completions,
                                    ),
                                    **removal_metadata,
                                    **recovery_metadata,
                                }
                            )
                        },
                    )
                for index, group in enumerate(groups):
                    freq, period = group["freq"], group["period"]
                    progress(
                        {
                            "stage": "history_period",
                            "freq": freq,
                            "period": period,
                            "done": index,
                            "total": len(groups),
                        }
                    )
                    assembler = (
                        assemble_history_period
                        if config.intent == "factor_changed"
                        else assemble_history_maintenance_period
                    )
                    extra = (
                        {}
                        if config.intent == "factor_changed"
                        else {
                            "remove_keys": [
                                key
                                for key in config.remove_keys
                                if key["freq"] == freq
                                and source_period(key["trade_date"], freq) == period
                            ]
                        }
                    )
                    item = assembler(
                        group["sources"],
                        **extra,
                        work=work / "candidates" / freq / period,
                        root=root,
                        freq=freq,
                        period=period,
                        cancel=cancel,
                        progress=progress,
                    )
                    item = publish_period(item, cancel=cancel)
                    completed.append(item)
                    yield dg.AssetMaterialization(
                        asset_key=f"raw_tushare_stk_period_bar_adj_{freq}",
                        partition=period,
                        metadata=build_materialization_metadata(
                            uri=item["target"],
                            row_count=item["rows"],
                            observed_columns=FIELDS,
                            extra_metadata={
                                FILE_DELIVERY_KEY: dg.MetadataValue.json(
                                    references[freq]
                                ),
                                "goldenshare/period_file_version": dg.MetadataValue.json(
                                    item["version"]
                                ),
                                "goldenshare/business_date": config.business_date,
                                "goldenshare/source_asof": item["source_asof"],
                                "goldenshare/rewritten": True,
                            },
                        ),
                    )
                if config.remove_keys and count_maintenance_rows(
                    root,
                    config.remove_keys,
                    work=work / "residual",
                    cancel=cancel,
                    progress=progress,
                ):
                    raise ValueError("period_maintenance_remove_keys_remaining")
                mats = {
                    (
                        r.asset_materialization.asset_key.to_user_string(),
                        r.asset_materialization.partition,
                    ): r
                    for r in native_run_records(
                        context.instance, [context.run_id], ["ASSET_MATERIALIZATION"]
                    )
                }
                for item in completed:
                    freq, period = item["freq"], item["period"]
                    if file_version(item["target"]) != item["version"]:
                        raise ValueError("period_repair_file_changed")
                    mat = mats[(f"raw_tushare_stk_period_bar_adj_{freq}", period)]
                    for name in raw_check_names(freq):
                        yield AssetCheckEvaluation(
                            asset_key=mat.asset_materialization.asset_key,
                            check_name=name,
                            partition=period,
                            passed=True,
                            blocking=True,
                            target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                                storage_id=mat.storage_id,
                                run_id=context.run_id,
                                timestamp=mat.event_log_entry.timestamp,
                            ),
                        )
                for freq in frequencies:
                    if not periods_by_freq[freq]:
                        continue
                    yield dg.AssetObservation(
                        asset_key=f"raw_tushare_stk_period_bar_adj_{freq}",
                        metadata={
                            COMPLETION_KEY: dg.MetadataValue.json(
                                delivery_completion(
                                    references[freq],
                                    kind=kind,
                                    business_date=config.business_date,
                                    periods=periods_by_freq[freq],
                                )
                            )
                        },
                    )
            finally:
                _BUDGET.reset(token)
    for freq in frequencies:
        items = [item for item in completed if item["freq"] == freq]
        from orchestrator.defs.run_contracts.stock_period import digest

        yield AssetCheckEvaluation(
            asset_key=dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}"),
            check_name=f"raw_tushare_stk_period_bar_adj_{freq}_history_repair_result_check",
            partition=period_for(date.fromisoformat(config.business_date), freq),
            passed=True,
            blocking=True,
            metadata={
                "version": "stock-period-result@1",
                "producer_run_id": context.run_id,
                "kind": kind,
                "business_date": config.business_date,
                "freq": freq,
                "stock_codes": codes,
                "codes_hash": config.codes_hash,
                "periods": periods_by_freq[freq],
                "periods_hash": digest(periods_by_freq[freq]),
                "file_count": len(items),
                "rewritten_file_count": len(items),
                "rewritten_row_count": sum(item["rows"] for item in items),
                "upstream_completions": config.upstream_completions,
                **removal_metadata,
            },
        )
