"""The three weekly checks share facts for the exact same file version."""

from orchestrator.defs.io.stock_period_raw import audit_file
from orchestrator.defs.run_contracts.stock_weekly import StockWeeklySource


def audit_weekly_file(source, week, root, *, kind="key_partition"):
    StockWeeklySource(source)
    if kind not in ("file_contract", "key_partition", "delivery_reconciliation"):
        raise ValueError("period_check_kind_invalid")
    return audit_file(root, "week", week)["rows"]
