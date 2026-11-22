"""Refresh a single production Check when its stock-daily input arrives late."""

from datetime import date

import dagster as dg
from sqlalchemy.exc import SQLAlchemyError

from orchestrator.defs.catalog.lake_assets import get_lake_asset_catalog_entry
from orchestrator.defs.checks.daily_audit_coverage import (
    TARGET_VERSION_TAG,
    version_string,
)
from orchestrator.defs.daily_data_audit.evidence import (
    load_evidence,
    metadata,
    verified_stock_daily,
)
from orchestrator.defs.daily_data_audit.registry import (
    LATE_STOCK_DAILY_COVERAGE_CHECKS,
    AuditTarget,
)
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key


def late_stock_daily_coverage_request(context, now, root, day, asset_key):
    daily = verified_stock_daily(context.instance, root, day)
    if not daily:
        return None
    target_day = date.fromisoformat(day)
    check_name = LATE_STOCK_DAILY_COVERAGE_CHECKS[asset_key]
    target = AuditTarget(
        get_lake_asset_catalog_entry(asset_key),
        day,
        target_day,
        True,
        (check_name,),
        False,
        "日更",
    )
    try:
        delivery = load_evidence(context.instance, (target,), target_day, now).get(
            asset_key
        )
    except SQLAlchemyError:
        return None
    if not (delivery and delivery.materialization):
        return None
    published = delivery.materialization
    file_version = metadata(published.asset_materialization).get("audit_file_version")
    original = delivery.checks.get(check_name)
    if not file_version or not original or not original.evaluation.passed:
        return None
    daily_version = version_string(daily[1])
    original_coverage = metadata(original.evaluation).get("audit_coverage") or {}
    if original_coverage.get("inputs", {}).get("silver_stock_daily") == daily_version:
        return None
    return dg.RunRequest(
        run_key=build_asset_update_run_key(
            subject=check_name, unit_id=f"{day}:{published.storage_id}:{daily_version}"
        ),
        partition_key=day,
        asset_selection=[],
        asset_check_keys=[dg.AssetCheckKey(dg.AssetKey(asset_key), check_name)],
        tags={TARGET_VERSION_TAG: version_string(file_version)},
    )
