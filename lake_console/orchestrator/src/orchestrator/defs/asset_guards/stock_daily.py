import dagster as dg

from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    silver_stock_basic_ready_for_trade_date,
)


def _status_payload(status: AssetReadinessStatus) -> dict[str, object]:
    return {
        "asset_key": status.asset_key,
        "partition_key": status.partition_key,
        "ready": status.ready,
        "materialized": status.materialized,
        "checks_passed": status.checks_passed,
        "freshness_passed": status.freshness_passed,
        "materialization_storage_id": status.materialization_storage_id,
        "materialization_date": status.materialization_date,
        "missing_check_names": list(status.missing_check_names),
        "failed_check_names": list(status.failed_check_names),
        "reason": status.reason,
    }


def assert_silver_stock_basic_fresh_for_stock_daily(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> None:
    status = silver_stock_basic_ready_for_trade_date(instance, trade_date)
    if status.ready:
        return

    raise dg.Failure(
        description=(
            "silver_stock_daily cannot be produced because silver_stock_basic "
            "is not fresh and green for the target trade date."
        ),
        metadata={
            "trade_date": trade_date,
            "readiness_reason": status.reason,
            "silver_stock_basic_status": dg.MetadataValue.json(
                _status_payload(status)
            ),
        },
    )
