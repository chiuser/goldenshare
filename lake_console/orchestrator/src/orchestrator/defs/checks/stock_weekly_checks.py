"""Checks only the current partition and its materialization; never read old proofs."""

from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.stock_weekly import (
    raw_tushare_stk_period_bar_adj_week,
    raw_tushare_stk_period_bar_week,
    raw_tushare_weekly,
)
from orchestrator.defs.bootstrap.stock_weekly_candidates import (
    partition_path,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_weekly_raw import (
    WEEK_SQL,
    load_relation,
    validate_relation,
)
from orchestrator.defs.partitions import cn_a_stock_week_ends
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    WeeklyBudget,
    normalize_week_key,
    weekly_check_names,
)
from orchestrator.defs.stock_period_checks import verify_period_materialization


def audit_weekly_file(source, week, root, *, kind="key_partition"):
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
            rows = audit_weekly_file(source, week, lake_root.root(), kind=kind)
            if kind == "delivery_reconciliation":
                records = context.instance.fetch_materializations(
                    dg.AssetRecordsFilter(asset_key=asset.key, asset_partitions=[week]),
                    limit=1,
                ).records
                verify_period_materialization(
                    records[0] if records else None,
                    week,
                    partition_path(lake_root.root(), source, week),
                    rows=rows,
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
