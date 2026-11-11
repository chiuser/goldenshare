"""Factor-change period history: explicit inputs, fresh source, native delivery."""

import tempfile
import time
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
    assemble_history_period,
    durable_directory,
    file_version,
    group_history_sources,
    process_memory_budget,
    publish_period,
)
from orchestrator.defs.paths import (
    silver_adj_factor_path,
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from orchestrator.defs.run_contracts.stock_period import period_for
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


def execute_history_repair(context, config):
    """All source units and candidates are rebuilt in this real run's directory."""
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
    _validate_upstreams(context.instance, root, config)
    codes = load_factor_changed_codes(root, config.business_date)
    if (
        codes != config.stock_codes
        or gold_stock_daily_qfq_factor_repair_codes_hash(codes) != config.codes_hash
    ):
        raise ValueError("period_repair_codes_changed")
    context.instance.add_run_tags(
        context.run_id,
        period_run_tags(business_date=config.business_date, kind="factor_repair"),
    )
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

    completed, references, periods_by_freq = [], {}, {freq: [] for freq in FREQUENCIES}
    if codes:
        work = durable_directory(staging / "stock_period" / "runs" / context.run_id)
        captured_devices = devices(root, staging)
        with writer(staging), process_memory_budget(DEFAULT_POLICY):
            budget = StorageBudget(
                work, DEFAULT_POLICY, cancel=cancel, progress=progress
            )
            budget.guard = lambda: check_devices(root, staging, captured_devices)
            token = _BUDGET.set(budget)
            try:
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
                transport, sources = HttpPage(cancel=cancel, progress=progress), []
                for freq in FREQUENCIES:
                    for index, code in enumerate(codes):
                        progress(
                            {
                                "stage": "history_source",
                                "freq": freq,
                                "code": code,
                                "done": index,
                                "total": len(codes),
                            }
                        )
                        sources.extend(
                            capture_stock_history(
                                work=work / "source" / freq / code,
                                freq=freq,
                                code=code,
                                listed=set(codes),
                                aliases=aliases,
                                transport=transport,
                                cancel=cancel,
                                progress=progress,
                            )
                        )
                groups = group_history_sources(
                    sources,
                    work=work / "groups",
                    root=root,
                    execution_date=datetime.now(ZoneInfo("Asia/Shanghai"))
                    .date()
                    .isoformat(),
                    cancel=cancel,
                    progress=progress,
                )
                for freq in FREQUENCIES:
                    periods = sorted(
                        group["period"] for group in groups if group["freq"] == freq
                    )
                    periods_by_freq[freq] = periods
                    references[freq] = delivery_ref(
                        context.run_id,
                        freq,
                        "factor_repair",
                        config.business_date,
                        periods,
                    )
                    yield dg.AssetObservation(
                        asset_key=f"raw_tushare_stk_period_bar_adj_{freq}",
                        metadata={
                            WORK_KEY: dg.MetadataValue.json(
                                delivery_work(
                                    references[freq],
                                    kind="factor_repair",
                                    business_date=config.business_date,
                                    periods=periods,
                                    stock_codes=codes,
                                    codes_hash=config.codes_hash,
                                    upstream_completions=config.upstream_completions,
                                )
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
                    item = assemble_history_period(
                        group["sources"],
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
                for freq in FREQUENCIES:
                    yield dg.AssetObservation(
                        asset_key=f"raw_tushare_stk_period_bar_adj_{freq}",
                        metadata={
                            COMPLETION_KEY: dg.MetadataValue.json(
                                delivery_completion(
                                    references[freq],
                                    kind="factor_repair",
                                    business_date=config.business_date,
                                    periods=periods_by_freq[freq],
                                )
                            )
                        },
                    )
            finally:
                _BUDGET.reset(token)
    for freq in FREQUENCIES:
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
                "kind": "factor_repair",
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
            },
        )
