"""Retain Raw; clean confirmed retirements directly from one frequency's Silver."""

import tempfile
import time
from pathlib import Path

import dagster as dg

from orchestrator.defs import paths
from orchestrator.defs.asset_guards.stock_period_delivery import (
    native_run_records,
    read_completion,
    silver_run_completion_consumed,
)
from orchestrator.defs.asset_guards.stock_period_retirement import (
    latest_retirement_result,
    parent_retirement_scope,
    require_previous_retirement_complete,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_period_raw import (
    _BUDGET,
    DEFAULT_POLICY,
    StorageBudget,
    connection,
    durable_directory,
    file_version,
    process_memory_budget,
    publish_period,
)
from orchestrator.defs.io.stock_period_silver import (
    assemble_retirement_period,
    count_retirement_rows,
    run_directory,
    validate_roots,
)
from orchestrator.defs.run_contracts.stock_period import digest
from orchestrator.defs.run_contracts.stock_period_delivery import period_run_tags
from orchestrator.defs.run_contracts.stock_period_retirement_cleanup import (
    JOB_NAME,
    RESULT_KEY,
    RESULT_VERSION,
    WORK_KEY,
    WORK_VERSION,
    StockPeriodRetirementCleanupConfig,
    build_retirement_run_config,
)
from orchestrator.defs.run_contracts.stock_period_silver import asset_name, check_names
from orchestrator.defs.stock_daily_qfq import (
    gold_stock_daily_qfq_factor_repair_codes_hash as codes_hash,
)
from orchestrator.defs.stock_period_silver import (
    cancellation,
    check_cancel,
    load_references,
    materialization_metadata,
    resolve_period_sources,
    validate_projection,
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


def retirement_source(instance, run, reference, root, *, freq, day, origin=None):
    """Require the exact normal Silver SUCCESS and its original daily Raw consumption."""
    if (
        run is None
        or run.job_name != asset_name(freq) + "_update_job"
        or run.status != dg.DagsterRunStatus.SUCCESS
    ):
        raise ValueError("period_retirement_silver_success_required")
    config = run.run_config.get("ops", {}).get(asset_name(freq), {}).get("config", {})
    if config.get("intent") != "update" or config.get("source_completion") != reference:
        raise ValueError("period_retirement_silver_intent_mismatch")
    origin = origin or read_completion(instance, reference, root=root)
    if (
        origin["completion"]["kind"] != "daily"
        or origin["asof"] != day
        or reference["freq"] != freq
    ):
        raise ValueError("period_retirement_upstream_intent_mismatch")
    minimum = "2014-01-03" if freq == "week" else "2014-01"
    periods = sorted(p for f, p in origin["items"] if f == freq and p >= minimum)
    silver_run_completion_consumed(
        instance, run, reference, periods, root=root, business_date=day
    )
    return origin


def evaluate_retirement_sensor(context, lake_root):
    run = context.dagster_run
    jobs = {asset_name(freq) + "_update_job": freq for freq in ("week", "month")}
    if run.job_name not in jobs:
        return dg.SkipReason("period_retirement_unmonitored_job")
    try:
        freq = jobs[run.job_name]
        source = run.run_config["ops"][asset_name(freq)]["config"]
        if source.get("intent") != "update":
            raise ValueError("period_retirement_silver_intent_mismatch")
        reference = source["source_completion"]
        root = lake_root.root()
        origin = read_completion(context.instance, reference, root=root)
        day = origin["asof"]
        retirement_source(
            context.instance, run, reference, root, freq=freq, day=day, origin=origin
        )
        codes = sorted(
            set(load_confirmed_retirements(root))
            - latest_retirement_result(context.instance, freq)
        )
        config = StockPeriodRetirementCleanupConfig(
            business_date=day,
            freq=freq,
            stock_codes=codes,
            codes_hash=codes_hash(codes),
            source_completion=reference,
            source_silver_run_id=run.run_id,
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

    from orchestrator.defs.bootstrap.stock_period_history import check_devices, devices

    config.validate_intent()
    context.instance.add_run_tags(
        context.run_id,
        period_run_tags(
            business_date=config.business_date,
            kind="retirement_cleanup",
            freq=config.freq,
        ),
    )
    require_previous_retirement_complete(context.instance, context.run, config)
    resource = context.resources.lake_root
    resource.ensure_available_for_run()
    root, staging = validate_roots(
        resource.root(), Path(paths.DEFAULT_LAKE_STAGING_ROOT)
    )
    origin = retirement_source(
        context.instance,
        context.instance.get_run_by_id(config.source_silver_run_id),
        config.source_completion,
        root,
        freq=config.freq,
        day=config.business_date,
    )
    references = {
        "stock_basic": paths.raw_stock_basic_path(root),
        "lifecycle": paths.silver_stock_lifecycle_path(root),
        "identity": paths.silver_stock_identity_map_path(root),
    }
    versions = {key: file_version(path) for key, path in references.items()}
    codes = config.stock_codes
    confirmed = load_confirmed_retirements(root) if codes else {}
    if not set(codes) <= set(confirmed):
        raise ValueError("period_retirement_not_confirmed")
    cleared = latest_retirement_result(context.instance, config.freq)
    completed, periods = [], []
    scope = {
        **config.model_dump(),
        "version": WORK_VERSION,
        "producer_run_id": context.run_id,
        "reference_versions": versions,
    }
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

    def assert_inputs(unit=None):
        if any(file_version(path) != versions[key] for key, path in references.items()):
            raise ValueError("period_retirement_facts_changed")
        if unit and file_version(unit["source"]) != unit["source_version"]:
            raise ValueError("silver_source_changed")

    progress = lambda value: context.log.info(str(value))
    asset = dg.AssetKey(asset_name(config.freq))
    identity = {
        "intent": "update",
        "run_id": context.run_id,
        "asof": config.business_date,
        "lower": "2014-01-01",
        "reference_versions": {k: versions[k] for k in ("lifecycle", "identity")},
    }
    if codes:
        physical = sorted(set().union(*(confirmed[code] for code in codes)))
        work = durable_directory(run_directory(staging, context.run_id))
        captured_devices = devices(root, staging)
        with process_memory_budget(DEFAULT_POLICY):
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
                periods = sorted(
                    {p for p, rows in counts.items() if rows}
                    | set(
                        parent_retirement_scope(context.instance, context.run, config)
                    )
                )
                scope.update(periods=periods, periods_hash=digest(periods))
                assert_inputs()
                yield dg.AssetObservation(
                    asset_key=asset, metadata={WORK_KEY: dg.MetadataValue.json(scope)}
                )
                units, _ = resolve_period_sources(
                    root,
                    config.freq,
                    config.source_completion,
                    periods,
                    context.instance,
                    cancel=cancel,
                    origin=origin,
                )
                with connection(work) as con, cancellation(con, cancel) as requested:
                    load_references(
                        con, {k: str(references[k]) for k in ("lifecycle", "identity")}
                    )
                    for unit in units:
                        check_cancel(requested)
                        assert_inputs(unit)
                        progress(
                            {
                                "stage": "silver_retirement_period",
                                "freq": config.freq,
                                "period": unit["period"],
                                "done": len(completed),
                                "total": len(units),
                            }
                        )
                        item = assemble_retirement_period(
                            con,
                            unit,
                            physical,
                            work=work / "candidates" / unit["period"],
                            cancel=requested,
                            progress=progress,
                        )
                        file_scope = {
                            **{
                                k: v
                                for k, v in scope.items()
                                if k not in ("periods", "periods_hash")
                            },
                            **unit,
                            "target_preimage": item["target_preimage"],
                            "rows_before": item["rows_before"],
                            "expected_removed_rows": item["removed_rows"],
                        }
                        yield dg.AssetObservation(
                            asset_key=asset,
                            metadata={WORK_KEY: dg.MetadataValue.json(file_scope)},
                        )
                        assert_inputs(unit)
                        if item["rewritten"]:
                            item = publish_period(item, cancel=requested)
                            validate_projection(
                                con, item["target"], config.freq, item["period"]
                            )
                        completed.append(item)
                        yield dg.AssetMaterialization(
                            asset_key=asset,
                            partition=item["period"],
                            metadata=materialization_metadata(item, identity),
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
                mats = {
                    r.asset_materialization.partition: r
                    for r in native_run_records(
                        context.instance, [context.run_id], ["ASSET_MATERIALIZATION"]
                    )
                    if r.asset_materialization.asset_key == asset
                }
                for item in completed:
                    check_cancel(cancel)
                    assert_inputs(item)
                    if file_version(item["target"]) != item["version"]:
                        raise ValueError("period_retirement_file_changed")
                    mat = mats[item["period"]]
                    for name in check_names(config.freq):
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
            finally:
                _BUDGET.reset(token)
    assert_inputs()
    check_cancel(cancel)
    cumulative = sorted(cleared | set(codes))
    scope.update(
        version=RESULT_VERSION,
        periods=periods,
        periods_hash=digest(periods),
        file_count=len(periods),
        rewritten_file_count=sum(item["rewritten"] for item in completed),
        removed_row_count=sum(item["removed_rows"] for item in completed),
        cleared_codes=cumulative,
        cleared_codes_hash=codes_hash(cumulative),
    )
    yield dg.AssetObservation(
        asset_key=asset, metadata={RESULT_KEY: dg.MetadataValue.json(scope)}
    )
