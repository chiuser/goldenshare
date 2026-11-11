"""Single-frequency retirement cleanup, with native complete-range reexecution."""

import tempfile
import time
from datetime import date
from pathlib import Path

import dagster as dg

from orchestrator.defs import paths
from orchestrator.defs.asset_guards.stock_period_delivery import (
    native_run_records,
    read_completion,
)
from orchestrator.defs.asset_guards.stock_period_retirement import (
    latest_retirement_result,
    parent_retirement_scope,
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
    assemble_retirement_period,
    count_retirement_rows,
    durable_directory,
    file_version,
    process_memory_budget,
    publish_period,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from orchestrator.defs.run_contracts.stock_period import digest, period_for
from orchestrator.defs.run_contracts.stock_period_delivery import (
    COMPLETION_KEY,
    FILE_DELIVERY_KEY,
    RAW_DAILY_JOBS,
    WORK_KEY,
    delivery_completion,
    delivery_ref,
    delivery_work,
    period_run_tags,
    raw_daily_run_intent,
)
from orchestrator.defs.run_contracts.stock_period_retirement_cleanup import (
    JOB_NAME,
    StockPeriodRetirementCleanupConfig,
    build_retirement_run_config,
    retirement_result_check_name,
)
from orchestrator.defs.stock_daily_qfq import (
    gold_stock_daily_qfq_factor_repair_codes_hash,
)


def load_confirmed_retirements(root):
    """Require D in both official facts and a confirmed CNY security identity."""
    references = [
        paths.raw_stock_basic_path(root),
        paths.silver_stock_lifecycle_path(root),
        paths.silver_stock_identity_map_path(root),
    ]
    versions = [file_version(path) for path in references]
    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=Path(tempfile.gettempdir()).resolve()),
        temp_policy="existing_no_spill",
    ) as con:
        rows = con.execute(
            """WITH identities AS MATERIALIZED (
            SELECT source_ts_code,latest_ts_code FROM read_parquet(?,hive_partitioning=false) WHERE confidence='confirmed'
        ), retired AS MATERIALIZED (
            SELECT DISTINCT i.latest_ts_code FROM read_parquet(?,hive_partitioning=false) b
            JOIN identities i ON i.source_ts_code=b.ts_code
            JOIN read_parquet(?,hive_partitioning=false) l ON l.ts_code=i.latest_ts_code
            WHERE b.list_status='D' AND l.list_status='D' AND l.is_cny_stock
        ) SELECT r.latest_ts_code,i.source_ts_code FROM retired r JOIN identities i USING(latest_ts_code)
          UNION SELECT latest_ts_code,latest_ts_code FROM retired ORDER BY 1,2""",
            [str(references[2]), str(references[0]), str(references[1])],
        ).fetchall()
    if versions != [file_version(path) for path in references]:
        raise ValueError("period_retirement_facts_changed")
    result = {}
    for canonical, physical in rows:
        result.setdefault(canonical, set()).add(physical)
    return result


def evaluate_retirement_sensor(context, lake_root):
    run = context.dagster_run
    if run.job_name not in RAW_DAILY_JOBS:
        return dg.SkipReason("period_retirement_unmonitored_job")
    try:
        freq, day = raw_daily_run_intent(run)
        period = period_for(date.fromisoformat(day), freq)
        reference = delivery_ref(run.run_id, freq, "daily", day, [period])
        root = lake_root.root()
        read_completion(context.instance, reference, root=root)
        retired = load_confirmed_retirements(root)
        cleared = latest_retirement_result(context.instance, freq)
        codes = sorted(set(retired) - cleared)
        config = StockPeriodRetirementCleanupConfig(
            business_date=day,
            freq=freq,
            stock_codes=codes,
            codes_hash=gold_stock_daily_qfq_factor_repair_codes_hash(codes),
            source_completion=reference,
        )
        from orchestrator.defs.run_contracts.requests import build_run_request
        from orchestrator.defs.run_contracts.run_keys import (
            build_upstream_triggered_run_key,
        )

        return build_run_request(
            run_key=build_upstream_triggered_run_key(
                consumer=JOB_NAME, upstream_batch_id=reference["upstream_batch_id"]
            ),
            run_config=build_retirement_run_config(config),
        )
    except (ValueError, KeyError, OSError) as error:
        return dg.SkipReason(str(error))


def execute_retirement_cleanup(context, config):
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )

    from orchestrator.defs.bootstrap.stock_period_history import (
        check_devices,
        devices,
        roots,
        writer,
    )

    config.validate_intent()
    resource = context.resources.lake_root
    resource.ensure_available_for_run()
    root, staging = roots(resource.root(), Path(paths.DEFAULT_LAKE_STAGING_ROOT))
    origin = read_completion(context.instance, config.source_completion, root=root)
    period = period_for(date.fromisoformat(config.business_date), config.freq)
    if (
        origin["completion"]["kind"] != "daily"
        or origin["asof"] != config.business_date
        or (config.freq, period) not in origin["items"]
    ):
        raise ValueError("period_retirement_upstream_intent_mismatch")
    codes = config.stock_codes
    confirmed = load_confirmed_retirements(root) if codes else {}
    if not set(codes) <= set(confirmed):
        raise ValueError("period_retirement_not_confirmed")
    cleared = latest_retirement_result(context.instance, config.freq)
    context.instance.add_run_tags(
        context.run_id,
        period_run_tags(
            business_date=config.business_date,
            kind="retirement_cleanup",
            freq=config.freq,
        ),
    )
    completed = []
    periods = []
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

    progress = lambda value: context.log.info(str(value))
    asset = dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{config.freq}")
    if codes:
        physical = sorted(set().union(*(confirmed[code] for code in codes)))
        work = durable_directory(staging / "stock_period" / "runs" / context.run_id)
        captured_devices = devices(root, staging)
        with writer(staging), process_memory_budget(DEFAULT_POLICY):
            budget = StorageBudget(
                work, DEFAULT_POLICY, cancel=cancel, progress=progress
            )
            budget.guard = lambda: check_devices(root, staging, captured_devices)
            token = _BUDGET.set(budget)
            try:
                counts = count_retirement_rows(
                    root,
                    config.freq,
                    physical,
                    work=work / "locate",
                    cancel=cancel,
                    progress=progress,
                )
                inherited = parent_retirement_scope(
                    context.instance, context.run, config
                )
                periods = sorted(
                    {period for period, rows in counts.items() if rows} | set(inherited)
                )
                reference = delivery_ref(
                    context.run_id,
                    config.freq,
                    "retirement_cleanup",
                    config.business_date,
                    periods,
                )
                if periods:
                    yield dg.AssetObservation(
                        asset_key=asset,
                        metadata={
                            WORK_KEY: dg.MetadataValue.json(
                                delivery_work(
                                    reference,
                                    kind="retirement_cleanup",
                                    business_date=config.business_date,
                                    periods=periods,
                                    stock_codes=codes,
                                    codes_hash=config.codes_hash,
                                    upstream_completions=[config.source_completion],
                                )
                            )
                        },
                    )
                for index, selected in enumerate(periods):
                    progress(
                        {
                            "stage": "retirement_period",
                            "freq": config.freq,
                            "period": selected,
                            "done": index,
                            "total": len(periods),
                        }
                    )
                    item = assemble_retirement_period(
                        root=root,
                        freq=config.freq,
                        period=selected,
                        codes=physical,
                        work=work / "candidates" / selected,
                        cancel=cancel,
                        progress=progress,
                    )
                    if item["rewritten"]:
                        item = publish_period(item, cancel=cancel)
                    completed.append(item)
                    yield dg.AssetMaterialization(
                        asset_key=asset,
                        partition=selected,
                        metadata=build_materialization_metadata(
                            uri=item["target"],
                            row_count=item["rows"],
                            observed_columns=FIELDS,
                            extra_metadata={
                                FILE_DELIVERY_KEY: dg.MetadataValue.json(reference),
                                "goldenshare/period_file_version": dg.MetadataValue.json(
                                    item["version"]
                                ),
                                "goldenshare/business_date": config.business_date,
                                "goldenshare/source_asof": item["source_asof"],
                                "goldenshare/rewritten": item["rewritten"],
                            },
                        ),
                    )
                remaining = count_retirement_rows(
                    root,
                    config.freq,
                    physical,
                    work=work / "final_counts",
                    cancel=cancel,
                    progress=progress,
                )
                if any(remaining.values()):
                    raise ValueError("period_retirement_rows_remain")
                if periods:
                    mats = {
                        r.asset_materialization.partition: r
                        for r in native_run_records(
                            context.instance,
                            [context.run_id],
                            ["ASSET_MATERIALIZATION"],
                        )
                        if r.asset_materialization.asset_key == asset
                    }
                    for item in completed:
                        if file_version(item["target"]) != item["version"]:
                            raise ValueError("period_retirement_file_changed")
                        mat = mats[item["period"]]
                        for name in raw_check_names(config.freq):
                            yield AssetCheckEvaluation(
                                asset_key=asset,
                                check_name=name,
                                partition=item["period"],
                                passed=True,
                                blocking=True,
                                target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                                    storage_id=mat.storage_id,
                                    run_id=context.run_id,
                                    timestamp=mat.event_log_entry.timestamp,
                                ),
                            )
                    yield dg.AssetObservation(
                        asset_key=asset,
                        metadata={
                            COMPLETION_KEY: dg.MetadataValue.json(
                                delivery_completion(
                                    reference,
                                    kind="retirement_cleanup",
                                    business_date=config.business_date,
                                    periods=periods,
                                )
                            )
                        },
                    )
            finally:
                _BUDGET.reset(token)
    cumulative = sorted(cleared | set(codes))
    yield AssetCheckEvaluation(
        asset_key=asset,
        check_name=retirement_result_check_name(config.freq),
        partition=period,
        passed=True,
        blocking=True,
        metadata={
            "version": "stock-period-result@1",
            "producer_run_id": context.run_id,
            "kind": "retirement_cleanup",
            "business_date": config.business_date,
            "freq": config.freq,
            "stock_codes": codes,
            "codes_hash": config.codes_hash,
            "periods": periods,
            "periods_hash": digest(periods),
            "file_count": len(periods),
            "rewritten_file_count": sum(item["rewritten"] for item in completed),
            "rewritten_row_count": sum(
                item["rows"] for item in completed if item["rewritten"]
            ),
            "upstream_completions": [config.source_completion],
            "cleared_codes": cumulative,
            "cleared_codes_hash": gold_stock_daily_qfq_factor_repair_codes_hash(
                cumulative
            ),
        },
    )
