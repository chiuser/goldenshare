"""Current sell estimates read current account fees, never a purchase's rates.

Historical valuation replay must keep using its frozen ValuationBasis instead.
This bounded read neither enqueues historical recalculation nor changes facts.
"""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, select

from src.biz.models.wealth.trading_assistant.accounts import Account, FeeVersion
from .calculation.fees import FeeSnapshot
from .calculation_inputs import CalculationInputMismatch
from .ledger_preparation import fee_snapshot
from .market_facts import apply_sql_budget


@dataclass(frozen=True, slots=True)
class CurrentFeeBasis:
    account_id: UUID
    fee_version_id: UUID
    fees: FeeSnapshot


def current_fee_basis(session, *, owner_id, account_id, policy, deadline) -> CurrentFeeBasis:
    """One owned projection avoids stale ORM identity-map account references.

    Read once per account/read context and pass the returned snapshot to each
    stock's value_round. The fee identity belongs in that context/cache key.
    """
    apply_sql_budget(session, deadline, policy)
    row = session.execute(select(FeeVersion.fee_version_id, FeeVersion.commission_rate,
        FeeVersion.minimum_commission, FeeVersion.stamp_tax_rate).select_from(Account).join(
        FeeVersion, and_(FeeVersion.account_id == Account.account_id,
                        FeeVersion.fee_version_id == Account.current_fee_version_id)).where(
        Account.owner_id == owner_id, Account.account_id == account_id)).one_or_none()
    if row is None:
        raise CalculationInputMismatch("Owned current account fee basis is unavailable")
    result = CurrentFeeBasis(account_id, row.fee_version_id, fee_snapshot(row))
    deadline.remaining_ms()
    return result
