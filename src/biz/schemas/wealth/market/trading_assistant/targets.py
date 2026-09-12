"""Immutable ledger target, distinct from editable business input."""
from typing import Literal

from .common import Contract
from .value_types import EntityId


class LedgerTarget(Contract):
    accountId: EntityId
    kind: Literal["TRADE", "CASH_FLOW"]
    recordId: EntityId


class TradeTarget(LedgerTarget):
    kind: Literal["TRADE"]


class CashFlowTarget(LedgerTarget):
    kind: Literal["CASH_FLOW"]


def validate_target(operation: str, target: LedgerTarget | None, account_id: str | None = None):
    expected = {
        "TRADE_CORRECT": "TRADE", "TRADE_VOID": "TRADE",
        "CASH_FLOW_CORRECT": "CASH_FLOW", "CASH_FLOW_VOID": "CASH_FLOW",
    }.get(operation)
    if expected is None:
        if target is not None:
            raise ValueError("This operation has no ledger target")
    elif target is None or target.kind != expected:
        raise ValueError("Correction and void require the matching ledger target")
    elif account_id is not None and target.accountId != account_id:
        raise ValueError("Ledger target must belong to the scope account")


def validate_target_receipt(target: LedgerTarget | None, receipt):
    if target is not None:
        result = receipt.result
        record_id = getattr(result, "tradeId" if target.kind == "TRADE" else "cashFlowId", None)
        if result.accountId != target.accountId or record_id != target.recordId:
            raise ValueError("Receipt does not belong to the retained ledger target")
