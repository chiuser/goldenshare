"""Fixed ind_ths history registration entry; native events are completion facts."""

from orchestrator.defs.bootstrap.moneyflow_history_events import (
    report_moneyflow_history_events,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    INDUSTRY_THS_MONEYFLOW_AUTOMATION,
)


def report_industry_moneyflow_ths_history_events(
    *, instance, plan, apply=False, cancel=lambda: False, progress=lambda _: None
):
    return report_moneyflow_history_events(
        instance=instance,
        plan=plan,
        contract=INDUSTRY_THS_MONEYFLOW_AUTOMATION,
        apply=apply,
        cancel=cancel,
        progress=progress,
    )
