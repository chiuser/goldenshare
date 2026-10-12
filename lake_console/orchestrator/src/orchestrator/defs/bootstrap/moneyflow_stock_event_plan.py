"""Fixed Traditional stock moneyflow event-plan entry; shared protocol lives in moneyflow_event_plan."""

from pathlib import Path

from orchestrator.defs.bootstrap.moneyflow_event_plan import (
    _assemble,
    build_moneyflow_event_plan,
    moneyflow_event_instance_identity,
    validate_moneyflow_event_plan,
)
from orchestrator.defs.bootstrap.moneyflow_event_preview import (
    stock_moneyflow_history_proof,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_STOCK_EVENT_PLAN_MAX_DATES,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    STOCK_MONEYFLOW_AUTOMATION,
)


def build_stock_moneyflow_event_plan(
    *,
    instance,
    staging_root: Path,
    lake_root: Path,
    operation_id: str,
    cutoff: str,
    expected_cohort_hash: str,
    dates=None,
):
    return build_moneyflow_event_plan(
        instance=instance,
        staging_root=staging_root,
        lake_root=lake_root,
        operation_id=operation_id,
        cutoff=cutoff,
        expected_cohort_hash=expected_cohort_hash,
        dates=dates,
        contract=STOCK_MONEYFLOW_AUTOMATION,
    )


def validate_stock_moneyflow_event_plan(plan, instance, *, check=lambda: None):
    return validate_moneyflow_event_plan(
        plan, instance, check=check, contract=STOCK_MONEYFLOW_AUTOMATION
    )


def build_stock_moneyflow_event_plans(
    *,
    instance,
    staging_root: Path,
    lake_root: Path,
    operation_id: str,
    cutoff: str,
    expected_cohort_hash: str,
):
    """Freeze all source dates into bounded independent plans from one physical proof."""
    identity = moneyflow_event_instance_identity(instance, lake_root)
    proof = stock_moneyflow_history_proof(
        staging_root=staging_root,
        lake_root=lake_root,
        operation_id=operation_id,
        cutoff=cutoff,
        expected_cohort_hash=expected_cohort_hash,
    )
    dates = tuple(entry["day"] for entry in proof["entries"])
    return tuple(
        _assemble(
            proof,
            staging_root=staging_root,
            lake_root=lake_root,
            operation_id=operation_id,
            identity=identity,
            contract=STOCK_MONEYFLOW_AUTOMATION,
            dates=dates[offset : offset + MONEYFLOW_STOCK_EVENT_PLAN_MAX_DATES],
        )
        for offset in range(0, len(dates), MONEYFLOW_STOCK_EVENT_PLAN_MAX_DATES)
    )
