"""THS stock readiness bound to its independent asset and check identities."""

from orchestrator.defs.asset_guards.moneyflow_delivery_readiness import (
    batch_moneyflow_readiness,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    STOCK_THS_MONEYFLOW_AUTOMATION,
)


def batch_stock_moneyflow_ths_readiness(
    instance, lake_root, dates, *, layers=("raw", "silver")
):
    return batch_moneyflow_readiness(
        instance,
        lake_root,
        dates,
        contract=STOCK_THS_MONEYFLOW_AUTOMATION,
        layers=layers,
    )
