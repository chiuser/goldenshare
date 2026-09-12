"""Input context from effective facts, independent of calculation publication."""
from datetime import date

from sqlalchemy import select, func, case

from src.biz.models.wealth.trading_assistant.accounts import InitialPosition, Initialization
from src.biz.schemas.wealth.market.trading_assistant.accounts import EntryContext
from src.biz.services.wealth.market.trading_assistant.account_acceptance import accepted_time
from src.biz.services.wealth.market.trading_assistant.calculation.precision import format_cents
from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsUnavailable, apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents
from src.biz.services.wealth.market.trading_assistant.validation import InvalidLedger
from .accounts import AccountQueries
from .effective_ledger import effective_ledger


class EntryContextQuery:
    def __init__(self, policy, market):
        self.policy, self.market = policy, market
        self.accounts = AccountQueries(policy, market)

    def read(self, session, *, owner_id, account_id, occurred_on: date, ts_code, now, deadline):
        account = self.accounts.owned(session, owner_id=owner_id, account_id=account_id, deadline=deadline)
        if occurred_on < account.initialized_on:
            raise InvalidLedger("occurredOn", occurred_on, "日期不能早于账户初始化日期")
        initial = session.get(Initialization, account.current_initialization_id)
        facts = effective_ledger(owner_id=owner_id, account_id=account_id, fact_version=account.fact_version)
        apply_sql_budget(session, deadline, self.policy)
        delta = session.scalar(select(func.sum(facts.c.net_cash_change)))
        cash = numeric_cents(initial.initial_cash) + (numeric_cents(delta) if delta is not None else 0)
        stock_ref, quantity, available, status, reason = None, None, None, "Ready", None
        if ts_code is not None:
            security = self.market.resolve_security(session, ts_code, deadline)
            stock_ref = {"tsCode":ts_code, "name":security.name}
            try:
                calendar = self.market.read_calendar(session, security.exchange, occurred_on, occurred_on, deadline)
                if not calendar.days[0].is_open:
                    raise InvalidLedger("occurredOn", occurred_on, "请选择交易日")
                position = session.get(InitialPosition, (initial.initialization_id, ts_code))
                signed = case((facts.c.direction == "BUY", facts.c.quantity), else_=-facts.c.quantity)
                apply_sql_budget(session, deadline, self.policy)
                row = session.execute(select(
                    func.coalesce(func.sum(case((facts.c.occurred_on < occurred_on, signed), else_=0)), 0),
                    func.coalesce(func.sum(case((facts.c.occurred_on == occurred_on, signed), else_=0)), 0),
                    func.coalesce(func.sum(case(((facts.c.occurred_on == occurred_on) & (facts.c.direction == "SELL"), facts.c.quantity), else_=0)), 0),
                ).where(facts.c.kind == "TRADE", facts.c.ts_code == ts_code, facts.c.occurred_on <= occurred_on)).one()
                opening = (position.quantity if position else 0) + int(row[0])
                quantity = str(opening + int(row[1]))
                unlocked = position.available_quantity if position and occurred_on == account.initialized_on else opening
                available = str(unlocked - int(row[2]))
            except MarketFactsUnavailable:
                status, reason = "Error", "交易日历暂不可用，不能确认可卖数量"
        deadline.remaining_ms()
        return EntryContext(accountId=str(account_id), factVersion=str(account.fact_version),
            occurredOn=occurred_on.isoformat(), cashThrough=accepted_time(now), availableCash=format_cents(cash),
            stockRef=stock_ref, quantity=quantity, availableQuantity=available,
            fees=self.accounts.fees(session, owner_id=owner_id, account_id=account_id, deadline=deadline),
            calendarDataStatus=status, reason=reason)
