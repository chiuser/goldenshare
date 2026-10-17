"""Three blocking checks share one current-partition validation, not old receipts."""

import dagster as dg

from orchestrator.defs.assets.stock_monthly import silver_stock_monthly
from orchestrator.defs.assets.stock_weekly import silver_stock_weekly
from orchestrator.defs.partitions import cn_a_stock_months, cn_a_stock_week_ends
from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.run_contracts.stock_period_silver import (
    VERSION,
    check_names,
    period_start,
    target_path,
)
from orchestrator.defs.stock_period_checks import verify_period_materialization
from orchestrator.defs.stock_period_silver import current_validation


def evaluate(context, lake, staging, freq, kind):
    asset = dg.AssetKey(
        "silver_stock_weekly" if freq == "week" else "silver_stock_monthly"
    )
    period = context.partition_key
    records = context.instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[period]), limit=1
    ).records
    record = records[0] if records else None
    verify_period_materialization(record, period, target_path(lake, freq, period))
    metadata = record.asset_materialization.metadata
    if (
        record.asset_materialization.asset_key != asset
        or getattr(metadata.get("goldenshare/silver_rule"), "value", None) != VERSION
    ):
        raise ValueError("silver_check_materialization_binding_invalid")
    asof = getattr(metadata.get("goldenshare/silver_asof"), "value", None)
    lower = getattr(metadata.get("goldenshare/silver_lower"), "value", None)
    if not asof or not lower:
        raise ValueError("silver_check_scope_missing")
    from datetime import date, timedelta

    def start(day):
        value = date.fromisoformat(day)
        return (
            (value - timedelta(days=value.weekday())).isoformat()
            if freq == "week"
            else value.replace(day=1).isoformat()
        )

    if not start(lower) <= period_start(period, freq) <= start(asof):
        raise ValueError("silver_check_outside_approved_scope")
    rows = current_validation(lake, staging, freq, period, asof=asof)
    verify_period_materialization(
        record, period, target_path(lake, freq, period), rows=rows
    )
    return dg.AssetCheckResult(
        passed=True,
        metadata=build_check_metadata(
            check_scope={
                "file_contract": CheckScope.SCHEMA,
                "key_partition": CheckScope.PARTITION_ALIGNMENT,
                "source_projection": CheckScope.RECONCILIATION,
            }[kind],
            checked_row_count=rows,
            file_path=target_path(lake, freq, period),
            extra_metadata={
                "goldenshare/silver_rule": VERSION,
                "goldenshare/reason_code": "ok",
            },
        ),
    )


def _build_check(asset, freq, partitions, kind, name):
    @dg.asset_check(asset=asset, name=name, partitions_def=partitions, blocking=True)
    def check(
        context: dg.AssetCheckExecutionContext, lake_root: LakeRootResource
    ) -> dg.AssetCheckResult:
        try:
            return evaluate(
                context, lake_root.root(), DEFAULT_LAKE_STAGING_ROOT, freq, kind
            )
        except Exception as error:  # noqa: BLE001 -- A check reports invalid file facts without leaking SQL or data.
            reason = (
                str(error)
                if isinstance(error, ValueError)
                else "silver_file_unreadable"
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
    silver_stock_weekly_file_contract_check,
    silver_stock_weekly_key_partition_check,
    silver_stock_weekly_source_projection_check,
) = tuple(
    _build_check(silver_stock_weekly, "week", cn_a_stock_week_ends, kind, name)
    for kind, name in zip(
        ("file_contract", "key_partition", "source_projection"),
        check_names("week"),
        strict=True,
    )
)

(
    silver_stock_monthly_file_contract_check,
    silver_stock_monthly_key_partition_check,
    silver_stock_monthly_source_projection_check,
) = tuple(
    _build_check(silver_stock_monthly, "month", cn_a_stock_months, kind, name)
    for kind, name in zip(
        ("file_contract", "key_partition", "source_projection"),
        check_names("month"),
        strict=True,
    )
)
