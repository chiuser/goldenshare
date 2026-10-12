"""Fixed THS stock moneyflow event-plan entry; shared protocol lives in moneyflow_event_plan."""

from pathlib import Path

from orchestrator.defs.bootstrap.moneyflow_event_plan import (
    build_moneyflow_event_plan,
    validate_moneyflow_event_plan,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    STOCK_THS_MONEYFLOW_AUTOMATION,
)


def build_stock_moneyflow_ths_event_plan(
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
        contract=STOCK_THS_MONEYFLOW_AUTOMATION,
    )


def validate_stock_moneyflow_ths_event_plan(plan, instance, *, check=lambda: None):
    return validate_moneyflow_event_plan(
        plan, instance, check=check, contract=STOCK_THS_MONEYFLOW_AUTOMATION
    )
