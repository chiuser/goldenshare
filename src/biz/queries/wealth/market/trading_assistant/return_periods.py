"""Scope-level period reads: accounts never share cash or average percentages."""
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from src.biz.schemas.wealth.market.trading_assistant.common import Coverage
from src.biz.services.wealth.market.trading_assistant.calculation.returns import ProfitResult, aggregate_returns
from .return_account_period import AccountPeriodReturnsQuery
from .return_stock_period import StockPeriodReturnsQuery


@dataclass(frozen=True, slots=True)
class PeriodRangeRead:
    result: ProfitResult
    coverage: Coverage


class PeriodReturnsQuery:
    def __init__(self, policy):
        self.whole = AccountPeriodReturnsQuery(policy)
        self.stock = StockPeriodReturnsQuery(policy)

    def read(self, session, *, owner_id, basis, start, end, today, deadline, stock=None):
        if any(type(day) is not date for day in (start, end, today)) or start > end:
            raise ValueError("Invalid scoped return range")
        result = aggregate_returns(())
        accounts = []
        for reference in basis.context.accounts:
            deadline.remaining_ms()
            args = dict(owner_id=owner_id, basis=basis, account_id=UUID(reference.accountId),
                start=start, end=end, today=today, deadline=deadline)
            value = self.whole.read(session, **args) if stock is None else self.stock.read(session, stock=stock, **args)
            result = aggregate_returns((result, value.result))
            accounts.extend(value.coverage.accounts)
        issues = [account for account in accounts if account.dataStatus not in ("Ready", "Empty")]
        ready = any(account.dataStatus in ("Ready", "Partial") for account in accounts)
        status = ("Partial" if ready else "Error" if any(a.dataStatus == "Error" for a in issues) else
            "Recalculating" if any(a.dataStatus == "Recalculating" for a in issues) else "Delayed") if issues else (
            "Ready" if ready else "Empty")
        return PeriodRangeRead(result, Coverage(dataStatus=status, reason=issues[0].reason if issues else None,
                                                isFinal=not issues, accounts=accounts))
