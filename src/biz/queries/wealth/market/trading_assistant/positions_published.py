"""Read only the fixed publication's round metadata and daily endpoints."""
from dataclasses import dataclass
from fractions import Fraction
from uuid import UUID, uuid5

from sqlalchemy import and_, func, select

from src.biz.models.wealth.trading_assistant.accounts import FeeVersion
from src.biz.models.wealth.trading_assistant.calculation import DayResult, PositionState
from src.biz.models.wealth.trading_assistant.calculation_inputs import ValuationBasis
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot, PublicationDay
from src.biz.services.wealth.market.trading_assistant.calculation.daily import PositionState as KernelPosition
from src.biz.services.wealth.market.trading_assistant.calculation.returns import value_round
from src.biz.services.wealth.market.trading_assistant.ledger_preparation import fee_snapshot
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents, numeric_integer
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
        apply_sql_budget(session, deadline, self.policy)
        query = select(PositionState, ValuationBasis, FeeVersion).join(PublicationDay,
            and_(PublicationDay.account_id == PositionState.account_id,
                 PublicationDay.day_result_id == PositionState.day_result_id)).join(DayResult,
            and_(DayResult.account_id == PublicationDay.account_id,
                 DayResult.day_result_id == PublicationDay.day_result_id)).outerjoin(ValuationBasis,
            and_(ValuationBasis.account_id == DayResult.account_id,
                 ValuationBasis.generation_id == DayResult.origin_generation_id,
                 ValuationBasis.trade_date == DayResult.trade_date,
                 ValuationBasis.ts_code == PositionState.ts_code)).outerjoin(FeeVersion,
            and_(FeeVersion.account_id == ValuationBasis.account_id,
                 FeeVersion.fee_version_id == ValuationBasis.fee_version_id)).where(
                PublicationDay.account_id == account_id, PublicationDay.generation_id == generation_id,
                PublicationDay.trade_date == day, DayResult.status == "SEALED", PositionState.ts_code.in_(codes))
        result = {}
        for row, price, fees in session.execute(query):
            if row.ts_code in result:
                raise ValueError("Published stock date has ambiguous rounds")
            quantity = numeric_integer(row.quantity)
            if quantity and (price is None or fees is None or price.quality != "READY"):
                raise ValueError("Published holding is missing frozen valuation evidence")
            state = KernelPosition(quantity, quantity, numeric_cents(row.remaining_buy_cost),
                numeric_cents(row.cumulative_buy_input), numeric_cents(row.cumulative_sell_net))
            # Current rows all have quantity > 0. A closed predecessor is never
            # carried into another round; its profit remains in the account day.
            profit = (value_round(state, Fraction(price.price), fee_snapshot(fees)).result.profit_cents
                      if quantity else state.sell_net_cents - state.buy_investment_cents)
            result[row.ts_code] = (row.round_id, row.opened_on, profit)
        return result

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
