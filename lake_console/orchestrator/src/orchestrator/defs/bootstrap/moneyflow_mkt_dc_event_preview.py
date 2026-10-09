"""Read-only single-dataset history event preview, bound to frozen P3 proofs."""

from pathlib import Path
from time import monotonic

import dagster as dg

from orchestrator.defs.asset_guards.moneyflow_mkt_dc_readiness import (
    latest_market_check_evaluations,
)
from orchestrator.defs.bootstrap.moneyflow_history_candidates import (
    _identity,
    _receipt_scope,
    _validate_receipt,
)
from orchestrator.defs.bootstrap.moneyflow_history_promote import (
    _check_path,
    _frozen,
    _promotion_contract,
    _promotion_state,
    _receipt_files,
    _target,
    _unit_paths,
    _validate_roots,
)
from orchestrator.defs.checks.moneyflow import audit_market_moneyflow_standardization
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_directory,
)
from orchestrator.defs.partitions import cn_a_moneyflow_mkt_dc_trade_days
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_DUCKDB_MEMORY_LIMIT,
    MONEYFLOW_DUCKDB_THREADS,
    MONEYFLOW_EVENT_DATE_BATCH,
    MONEYFLOW_EVENT_RECORD_LIMIT,
    MONEYFLOW_HISTORY_MAX_DATE_FACTS,
    MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS,
    MONEYFLOW_MKT_DC_RAW_CHECK,
    MONEYFLOW_MKT_DC_SILVER_CHECK,
    MONEYFLOW_RECENT_CHECK_DAYS,
    MoneyflowContractError,
    assert_moneyflow_memory_budget,
)


def preview_market_moneyflow_history(
    *,
    instance,
    staging_root: Path,
    lake_root: Path,
    operation_id: str,
    cutoff: str,
    expected_cohort_hash: str,
):
    """No instance construction, locks, event publication or control-file updates."""
    _validate_roots(lake_root, staging_root)
    scoped = moneyflow_candidate_directory(
        staging_root, operation_id, cutoff, dataset="moneyflow_mkt_dc"
    )
    root = scoped.parents[1]
    controls = {
        p: candidate_file_hash(p)
        for p in (root / "cohort.json", root / "progress.json")
    }
    manifest, units, closed, plans = _frozen(root, cutoff)
    if manifest["cohort_hash"] != expected_cohort_hash:
        raise MoneyflowContractError("history_cohort_changed")
    contract = _promotion_contract(manifest, closed, lake_root)
    plan = next(p for p in plans if p.dataset == "moneyflow_mkt_dc")
    dates = tuple(f.trade_date for f in plan.date_counts)
    if not dates or len(dates) > MONEYFLOW_HISTORY_MAX_DATE_FACTS:
        raise MoneyflowContractError("history_event_dates")
    facts = {}
    hashed_bytes = unit_count = 0
    for (unit_plan, unit_id), entry in zip(units, closed, strict=True):
        if unit_plan.dataset != "moneyflow_mkt_dc":
            continue
        started = monotonic()
        for path in _unit_paths(root, plan, unit_id):
            _check_path(path)
        _, checkpoint, promotion, state = _promotion_state(
            root, plan, unit_id, entry, contract
        )
        controls[checkpoint] = candidate_file_hash(checkpoint)
        if (
            controls[checkpoint] != entry["checkpoint_sha256"]
            or state["stage"] != "complete"
        ):
            raise MoneyflowContractError("history_event_unit_not_closed")
        controls[promotion] = candidate_file_hash(promotion)
        receipt, files = _receipt_files(root, plan, unit_id)
        _validate_receipt(receipt, _receipt_scope(plan, unit_id, _identity(plan)))
        if receipt["stage"] != "verified":
            raise MoneyflowContractError("history_event_unit_not_verified")
        for day, layer, _, digest in files:
            path = _target(lake_root, plan, day, layer)
            size = path.stat().st_size if path.is_file() else 0
            item = state["files"][f"{day}/{layer}"]
            if size != item["size"] or candidate_file_hash(path) != digest:
                raise MoneyflowContractError("history_formal_changed")
            facts[(day, layer)] = digest
            hashed_bytes += size
            if monotonic() - started > MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS:
                raise MoneyflowContractError("history_event_unit_timeout")
            assert_moneyflow_memory_budget()
        unit_count += 1
    recent = dates[-MONEYFLOW_RECENT_CHECK_DAYS:]
    with connect_configured_duckdb(
        DuckDBConnectionSettings(
            temp_directory=Path("/private/tmp"),
            memory_limit=MONEYFLOW_DUCKDB_MEMORY_LIMIT,
            threads=MONEYFLOW_DUCKDB_THREADS,
        ),
        temp_policy="existing_no_spill",
    ) as connection:
        for day in recent:
            started = monotonic()
            audit_market_moneyflow_standardization(
                connection,
                _target(lake_root, plan, day, "raw"),
                _target(lake_root, plan, day, "silver"),
                day,
            )
            if monotonic() - started > MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS:
                raise MoneyflowContractError("history_event_unit_timeout")
            assert_moneyflow_memory_budget()
    registered = instance.get_dynamic_partitions(cn_a_moneyflow_mkt_dc_trade_days.name)
    if len(registered) > MONEYFLOW_HISTORY_MAX_DATE_FACTS:
        raise MoneyflowContractError("partition_limit")
    counts = {}
    metadata_queries = 1
    for layer, check_name in (
        ("raw", MONEYFLOW_MKT_DC_RAW_CHECK),
        ("silver", MONEYFLOW_MKT_DC_SILVER_CHECK),
    ):
        key = dg.AssetKey(
            "raw_tushare_moneyflow_mkt_dc"
            if layer == "raw"
            else "silver_moneyflow_mkt_dc"
        )
        latest = {}
        for offset in range(0, len(dates), MONEYFLOW_EVENT_DATE_BATCH):
            batch = dates[offset : offset + MONEYFLOW_EVENT_DATE_BATCH]
            records = instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=key, asset_partitions=list(batch)),
                limit=MONEYFLOW_EVENT_RECORD_LIMIT,
            ).records
            metadata_queries += 1
            found = {}
            for record in records:
                if record.partition_key in batch:
                    found.setdefault(record.partition_key, record)
            if len(records) >= MONEYFLOW_EVENT_RECORD_LIMIT and set(found) != set(
                batch
            ):
                raise MoneyflowContractError("history_event_record_limit")
            latest.update(found)
        for day, record in latest.items():
            digest = record.asset_materialization.metadata.get(
                "goldenshare/file_sha256"
            )
            if digest is None or digest.value != facts[(day, layer)]:
                raise MoneyflowContractError("history_event_existing_revision")
            if layer == "silver":
                upstream = record.asset_materialization.metadata.get(
                    "goldenshare/raw_sha256"
                )
                if upstream is None or upstream.value != facts[(day, "raw")]:
                    raise MoneyflowContractError(
                        "history_event_existing_upstream_revision"
                    )
        checks = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(key, check_name), limit=MONEYFLOW_EVENT_RECORD_LIMIT
        )
        metadata_queries += 1
        latest_checks = latest_market_check_evaluations(checks, recent)
        if len(checks) >= MONEYFLOW_EVENT_RECORD_LIMIT and not set(recent).issubset(
            latest_checks
        ):
            raise MoneyflowContractError("history_event_record_limit")
        reused_checks = 0
        for day, record in latest_checks.items():
            mat = latest.get(day)
            event = record.event.dagster_event if record.event else None
            evaluation = event.event_specific_data if event else None
            target = getattr(evaluation, "target_materialization_data", None)
            if not (
                mat
                and record.status.value == "SUCCEEDED"
                and getattr(evaluation, "passed", False)
                and getattr(evaluation, "blocking", False)
                and getattr(target, "storage_id", None) == mat.storage_id
                and getattr(target, "run_id", None) == mat.event_log_entry.run_id
                and getattr(target, "timestamp", None) == mat.timestamp
            ):
                raise MoneyflowContractError("history_event_check_failed_or_stale")
            reused_checks += 1
        counts[layer] = {
            "materializations_to_add": len(dates) - len(latest),
            "materializations_reusable": len(latest),
            "recent_checks_to_add": len(recent) - reused_checks,
            "recent_checks_reusable": reused_checks,
        }
    for path, digest in controls.items():
        if candidate_file_hash(path) != digest:
            raise MoneyflowContractError("history_event_controls_changed")
    return {
        "stage": "read_only_preview",
        "dataset": "moneyflow_mkt_dc",
        "cohort_hash": manifest["cohort_hash"],
        "cutoff": cutoff,
        "history_dates": len(dates),
        "history_rows": plan.row_count,
        "verified_units": unit_count,
        "verified_files": len(facts),
        "hashed_bytes": hashed_bytes,
        "recent_check_dates": list(recent),
        "partitions_to_add": len(set(dates) - set(registered)),
        "layers": counts,
        "metadata_queries": metadata_queries,
        "control_files_unchanged": len(controls),
        "formal_writes": 0,
    }
