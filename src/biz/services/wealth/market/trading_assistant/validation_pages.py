"""Bounded prospective ledger scans, without acceptance or returns calculation."""
from dataclasses import dataclass
from datetime import date
import json
from uuid import UUID

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.trading_assistant.effective_ledger import ReplacementFact, validation_page
from .execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from .market_facts import MarketFactsReader, apply_sql_budget
from .persistence_values import numeric_cents
from .validation import (CashValidation, QuantityValidation, advance_cash, advance_quantity,
                         finish_cash_day, finish_quantity_day)


@dataclass(frozen=True, slots=True)
class ValidationPage:
    state: CashValidation | QuantityValidation
    after: tuple[date, UUID] | None
    complete: bool
    rows: int
    bytes_read: int
    # Concrete calendar facts are retained, not merely a largest checked date.
    calendar_facts: tuple[tuple[str, bool, str | None], ...]


class ValidationPageReader:
    def __init__(self, policy: TradingAssistantExecutionPolicyV1, market: MarketFactsReader):
        self.policy, self.market = policy, market

    def read(self, session: Session, *, owner_id: int, account_id: UUID, fact_version: int,
             state: CashValidation | QuantityValidation, deadline: Deadline,
             after: tuple[date, UUID] | None = None, stock: str | None = None,
             exchange: str | None = None, replaced_ledger_id: UUID | None = None,
             replacement: ReplacementFact | None = None) -> ValidationPage:
        if isinstance(state, QuantityValidation) != (stock is not None):
            raise ValueError("Quantity stage requires exactly one stock")
        if stock is not None and exchange is None:
            raise ValueError("Quantity stage requires validated security market")
        batch = Deadline.after_ms(deadline.bounded_ms(self.policy.batch_budget_ms), deadline.clock)
        apply_sql_budget(session,batch,self.policy)
        statement = validation_page(owner_id=owner_id,account_id=account_id,fact_version=fact_version,
            limit=self.policy.page_rows,policy=self.policy,stock=stock,after=after,
            replaced_ledger_id=replaced_ledger_id,replacement=replacement)
        count, measured = 0, 0
        cursor = after
        calendar = {}
        # Server-side cursor avoids materializing an entire result before a byte check.
        result = session.execute(statement.execution_options(stream_results=True,yield_per=1))
        ended = True
        try:
            for row in result:
                batch.remaining_ms()
                size = len(json.dumps([str(row.ledger_id),row.occurred_on.isoformat(),row.kind,
                    row.direction,row.quantity,str(row.net_cash_change),row.ts_code],
                    ensure_ascii=False,separators=(",", ":")).encode())
                if measured + size > self.policy.page_bytes:
                    if count == 0:
                        raise ValueError("A validation projection exceeds the batch byte budget")
                    ended = False
                    break
                if isinstance(state,CashValidation):
                    state = advance_cash(state,row.occurred_on,numeric_cents(row.net_cash_change))
                else:
                    if row.occurred_on not in calendar:
                        basis = self.market.read_calendar(session,exchange,row.occurred_on,row.occurred_on,batch)
                        calendar[row.occurred_on] = basis.days[0]
                    state = advance_quantity(state,row.occurred_on,row.direction,row.quantity,
                                             is_open=calendar[row.occurred_on].is_open)
                measured += size
                count += 1
                cursor = (row.occurred_on,row.ledger_id)
                batch.remaining_ms()
        finally:
            result.close()
        # A full page may stop mid-day or at a SQL limit; an empty next page proves EOF.
        complete = ended and count < self.policy.page_rows
        if complete:
            state = finish_cash_day(state) if isinstance(state,CashValidation) else finish_quantity_day(state)
        deadline.remaining_ms()
        evidence = tuple((d.isoformat(),f.is_open,f.previous_trade_date.isoformat() if f.previous_trade_date else None)
                         for d,f in sorted(calendar.items()))
        return ValidationPage(state,cursor,complete,count,measured,evidence)
