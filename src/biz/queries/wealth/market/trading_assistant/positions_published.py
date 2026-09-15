"""Read only the fixed publication's round metadata and daily endpoints."""
from dataclasses import dataclass
from uuid import UUID, uuid5

from sqlalchemy import and_, func, select

from src.biz.models.wealth.trading_assistant.calculation import PositionState
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot, PublicationDay
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from .return_endpoints import PublishedStockEndpointsQuery
from .current_positions import CurrentPositionsQuery, PublishedPositionsUnavailable


@dataclass(frozen=True, slots=True)
class PublishedHolding:
    value: object
    round_number: int
    opening_source: str
    day_profit_cents: int | None


class PositionsPublishedQuery:
    def __init__(self, policy):
        self.policy = policy
        self.current = CurrentPositionsQuery(policy)
        self.endpoints = PublishedStockEndpointsQuery(policy)

    def read(self, session, *, basis, account, cutoff, deadline):
        if cutoff.valuation_date is None:
            raise PublishedPositionsUnavailable(cutoff.reason or "估值日期不可确认")
        ref = next(item for item in basis.context.accounts if item.accountId == str(account.account_id))
        result, after = {}, None
        while True:
            page = self.current.page(session, basis=basis, account_id=account.account_id,
                trade_date=cutoff.valuation_date, deadline=deadline, after_stock=after)
            codes = [item.stock_code for item in page.items]
            generation_id = UUID(ref.publishedGenerationId)
            rounds = self._round_counts(session, account.account_id, generation_id,
                                        cutoff.valuation_date, codes, deadline)
            daily = (self._daily(session, account.account_id, generation_id, cutoff.today, codes, deadline)
                     if cutoff.valuation_date == cutoff.today else {})
            for item in page.items:
                initial_id = uuid5(account.account_id,
                    f"INITIAL:{account.current_initialization_id}:{item.stock_code}")
                result[item.stock_code] = PublishedHolding(item, rounds[item.stock_code],
                    "INITIALIZATION" if item.round_id == initial_id else "TRADE", daily.get(item.stock_code))
            if page.next_stock is None:
                return result, self._snapshot(session, account.account_id, generation_id, cutoff.today, deadline)
            after = page.next_stock

    def _round_counts(self, session, account_id, generation_id, day, codes, deadline):
        if not codes:
            return {}
        apply_sql_budget(session, deadline, self.policy)
        return dict(session.execute(select(PositionState.ts_code, func.count(func.distinct(PositionState.round_id)))
            .join(PublicationDay, and_(PublicationDay.account_id == PositionState.account_id,
                  PublicationDay.day_result_id == PositionState.day_result_id)).where(
                PublicationDay.account_id == account_id, PublicationDay.generation_id == generation_id,
                PublicationDay.trade_date <= day, PositionState.ts_code.in_(codes))
            .group_by(PositionState.ts_code)).all())

    def _snapshot(self, session, account_id, generation_id, day, deadline):
        apply_sql_budget(session, deadline, self.policy)
        return session.scalar(select(AccountSnapshot).join(PublicationDay,
            and_(PublicationDay.account_id == AccountSnapshot.account_id,
                 PublicationDay.day_result_id == AccountSnapshot.day_result_id)).where(
            PublicationDay.account_id == account_id, PublicationDay.generation_id == generation_id,
            PublicationDay.trade_date == day))

    def _endpoints(self, session, account_id, generation_id, day, codes, deadline):
        values = self.endpoints.read(session, account_id=account_id, generation_id=generation_id,
                                     day=day, codes=codes, deadline=deadline)
        return {code: (value.round_id, value.opened_on, value.profit_cents) for code, value in values.items()}

    def _daily(self, session, account_id, generation_id, day, codes, deadline):
        if not codes:
            return {}
        apply_sql_budget(session, deadline, self.policy)
        previous = session.scalar(select(func.max(PublicationDay.trade_date)).where(
            PublicationDay.account_id == account_id, PublicationDay.generation_id == generation_id,
            PublicationDay.trade_date < day))
        ending = self._endpoints(session, account_id, generation_id, day, codes, deadline)
        opening = self._endpoints(session, account_id, generation_id, previous, codes, deadline) if previous else {}
        result = {}
        for code, (round_id, opened_on, profit) in ending.items():
            prior = opening.get(code)
            if prior and prior[0] == round_id:
                result[code] = profit - prior[2]
            elif opened_on == day:
                result[code] = profit
            else:
                raise ValueError("Published day lacks its prior round endpoint")
        return result
