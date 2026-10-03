"""Checks read physical files and independent delivery evidence; never fetch source."""

import json
from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.stock_weekly import (
    raw_tushare_stk_period_bar_adj_week,
    raw_tushare_stk_period_bar_week,
    raw_tushare_weekly,
)
from orchestrator.defs.bootstrap.stock_weekly_candidates import (
    fingerprint,
    partition_path,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    check_capture_path,
)
from orchestrator.defs.bootstrap.stock_weekly_promote import read_audit
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_weekly_raw import (
    WEEK_SQL,
    load_relation,
    relation_hashes,
    validate_relation,
)
from orchestrator.defs.partitions import cn_a_stock_week_ends
from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    WeeklyBudget,
    normalize_week_key,
    weekly_check_names,
)


def audit_weekly_file(source, week, root, *, delivery=None, kind="key_partition"):
    normalize_week_key(week)
    path = partition_path(root, source, week)
    budget = WeeklyBudget()
    # Checks are read-only, including spill: use existing temporary storage and no spill.
    import tempfile

    settings = DuckDBConnectionSettings(
        temp_directory=Path(tempfile.gettempdir()).resolve(),
        memory_limit=budget.duckdb_memory_limit,
        threads=budget.duckdb_threads,
        max_temp_directory_size=budget.duckdb_max_temp,
    )
    with connect_configured_duckdb(settings, temp_policy="existing_no_spill") as con:
        load_relation(con, "weekly_checked", [path], source)
        if kind == "file_contract":
            return con.execute("SELECT count(*) FROM weekly_checked").fetchone()[0]
        count = validate_relation(con, "weekly_checked", source, budget, unique=True)
        if con.execute(
            f"SELECT count(*) FROM weekly_checked WHERE {WEEK_SQL}<>?", [week]
        ).fetchone()[0]:
            raise WeeklyCaptureError("formal_week_mismatch")
        hashes = relation_hashes(con, "weekly_checked", source, budget)
        if delivery is not None:
            audit_path = Path(delivery["audit_path"])
            check_capture_path(audit_path)
            allowed = (
                Path(DEFAULT_LAKE_STAGING_ROOT),
                Path("/private/tmp"),
                Path(tempfile.gettempdir()).resolve(),
            )
            if not any(audit_path.is_relative_to(p) for p in allowed):
                raise WeeklyCaptureError("delivery_path_forbidden")
            audit = read_audit(audit_path)
            if (
                audit["audit_hash"] != delivery["audit_hash"]
                or audit["source"] != source.value
                or audit["target_root"] != str(root)
            ):
                raise WeeklyCaptureError("delivery_identity_mismatch")
            matches = [f for f in audit["files"] if f["week"] == week]
            if (
                len(matches) != 1
                or matches[0]["target"] != str(path)
                or fingerprint(path) != matches[0]["sha256"]
            ):
                raise WeeklyCaptureError("delivery_target_mismatch")
            if hashes != {
                week: {
                    "rows": matches[0]["rows"],
                    "logical_hash": matches[0]["logical_hash"],
                }
            }:
                raise WeeklyCaptureError("delivery_hash_mismatch")
            if len(audit["source_evidence"]) > budget.max_phase_files:
                raise WeeklyCaptureError("delivery_evidence_budget_exceeded")
            control_count = 0
            receipts = 0
            for item in audit["source_evidence"]:
                reference = Path(item["path"])
                if fingerprint(reference) != item["sha256"]:
                    raise WeeklyCaptureError("delivery_evidence_changed")
                if reference.name == "receipt.json":
                    if reference.stat().st_size > 1024 * 1024:
                        raise WeeklyCaptureError("delivery_receipt_budget_exceeded")
                    receipt = json.loads(reference.read_text())
                    if (
                        receipt["status"] not in ("captured", "success_empty")
                        or receipt["schema_hash"] != audit["schema_hash"]
                    ):
                        raise WeeklyCaptureError("delivery_receipt_invalid")
                    control_count += receipt["source_rows"]
                    receipts += 1
            if (
                not receipts
                or control_count != audit["stats"]["source_rows"]
                or count != matches[0]["rows"]
            ):
                raise WeeklyCaptureError("delivery_control_count_mismatch")
    return count


def _build_check(asset, source, name, kind):
    @dg.asset_check(
        asset=asset, name=name, partitions_def=cn_a_stock_week_ends, blocking=True
    )
    def check(
        context: dg.AssetCheckExecutionContext, lake_root: LakeRootResource
    ) -> dg.AssetCheckResult:
        reason = "ok"
        try:
            week = context.partition_key
            delivery = None
            if kind == "delivery_reconciliation":
                records = context.instance.fetch_materializations(
                    dg.AssetRecordsFilter(asset_key=asset.key, asset_partitions=[week]),
                    limit=1,
                ).records
                if not records:
                    raise WeeklyCaptureError("delivery_materialization_missing")
                value = records[0].asset_materialization.metadata.get(
                    "goldenshare/weekly_delivery"
                )
                delivery = getattr(value, "value", None)
                if not delivery:
                    raise WeeklyCaptureError("delivery_evidence_missing")
            rows = audit_weekly_file(
                source, week, lake_root.root(), delivery=delivery, kind=kind
            )
            return dg.AssetCheckResult(
                passed=True,
                metadata=build_check_metadata(
                    check_scope=CheckScope.RECONCILIATION
                    if kind == "delivery_reconciliation"
                    else CheckScope.SCHEMA
                    if kind == "file_contract"
                    else CheckScope.PARTITION_ALIGNMENT,
                    checked_row_count=rows,
                    extra_metadata={
                        "goldenshare/week_end": week,
                        "goldenshare/reason_code": reason,
                    },
                ),
            )
        except Exception as error:  # noqa: BLE001 -- Emit a bounded check failure without source/secret text.
            reason = (
                str(error)
                if isinstance(error, WeeklyCaptureError)
                else "formal_file_invalid"
            )
        return dg.AssetCheckResult(
            passed=False,
            severity=dg.AssetCheckSeverity.ERROR,
            metadata=build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                extra_metadata={"goldenshare/reason_code": reason},
            ),
        )

    return check


(
    raw_tushare_stk_period_bar_week_file_contract_check,
    raw_tushare_stk_period_bar_week_key_partition_check,
    raw_tushare_stk_period_bar_week_delivery_reconciliation_check,
) = tuple(
    _build_check(
        raw_tushare_stk_period_bar_week, StockWeeklySource.PRIMARY_UNADJUSTED, n, k
    )
    for n, k in zip(
        weekly_check_names(StockWeeklySource.PRIMARY_UNADJUSTED),
        ("file_contract", "key_partition", "delivery_reconciliation"),
        strict=True,
    )
)
(
    raw_tushare_stk_period_bar_adj_week_file_contract_check,
    raw_tushare_stk_period_bar_adj_week_key_partition_check,
    raw_tushare_stk_period_bar_adj_week_delivery_reconciliation_check,
) = tuple(
    _build_check(
        raw_tushare_stk_period_bar_adj_week, StockWeeklySource.PRIMARY_ADJUSTED, n, k
    )
    for n, k in zip(
        weekly_check_names(StockWeeklySource.PRIMARY_ADJUSTED),
        ("file_contract", "key_partition", "delivery_reconciliation"),
        strict=True,
    )
)
(
    raw_tushare_weekly_file_contract_check,
    raw_tushare_weekly_key_partition_check,
    raw_tushare_weekly_delivery_reconciliation_check,
) = tuple(
    _build_check(raw_tushare_weekly, StockWeeklySource.ALTERNATE_WEEKLY, n, k)
    for n, k in zip(
        weekly_check_names(StockWeeklySource.ALTERNATE_WEEKLY),
        ("file_contract", "key_partition", "delivery_reconciliation"),
        strict=True,
    )
)
