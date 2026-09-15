"""Shared frozen stock endpoints for current holdings and historical returns."""
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from uuid import UUID

from sqlalchemy import and_, select

from src.biz.models.wealth.trading_assistant.accounts import FeeVersion
from src.biz.models.wealth.trading_assistant.calculation import DayResult, PositionState
from src.biz.models.wealth.trading_assistant.calculation_inputs import ValuationBasis
from src.biz.models.wealth.trading_assistant.publication import PublicationDay
from src.biz.services.wealth.market.trading_assistant.calculation.daily import PositionState as KernelPosition
from src.biz.services.wealth.market.trading_assistant.calculation.returns import value_round
from src.biz.services.wealth.market.trading_assistant.ledger_preparation import fee_snapshot
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents, numeric_integer


@dataclass(frozen=True, slots=True)
class StockReturnEndpoint:
    stock: str
    round_id: UUID
    opened_on: date
    state: KernelPosition
    profit_cents: int


class PublishedStockEndpointsQuery:
    def __init__(self, policy):
        self.policy = policy

    def read(self, session, *, account_id, generation_id, day, codes, deadline):
        """Caller has already resolved this owned, fixed publication in its transaction."""
        if len(codes) != len(set(codes)) or len(codes) > self.policy.page_rows:
            raise ValueError("Stock endpoint selection must fit one unique page")
        if not codes:
            return {}
        apply_sql_budget(session, deadline, self.policy)
        query = select(PositionState, ValuationBasis, FeeVersion).join(PublicationDay,
            and_(PublicationDay.account_id == PositionState.account_id,
                 PublicationDay.day_result_id == PositionState.day_result_id)).join(DayResult,
            and_(DayResult.account_id == PublicationDay.account_id,
                 DayResult.day_result_id == PublicationDay.day_result_id,
                 DayResult.trade_date == PublicationDay.trade_date)).outerjoin(ValuationBasis,
            and_(ValuationBasis.account_id == DayResult.account_id,
                 ValuationBasis.generation_id == DayResult.origin_generation_id,
                 ValuationBasis.trade_date == DayResult.trade_date,
                 ValuationBasis.ts_code == PositionState.ts_code)).outerjoin(FeeVersion,
            and_(FeeVersion.account_id == ValuationBasis.account_id,
                 FeeVersion.fee_version_id == ValuationBasis.fee_version_id)).where(
                PublicationDay.account_id == account_id, PublicationDay.generation_id == generation_id,
                PublicationDay.trade_date == day, DayResult.status == "SEALED", PositionState.ts_code.in_(codes))
        rows = session.execute(query.limit(self.policy.page_rows + 1)).all()
        if len(rows) > len(codes):
            raise ValueError("Published stock date has ambiguous rounds")
        result = {}
        for row, price, fees in rows:
            deadline.remaining_ms()
            if row.ts_code in result:
                raise ValueError("Published stock date has ambiguous rounds")
            quantity = numeric_integer(row.quantity)
            if quantity and (price is None or fees is None or price.quality != "READY"):
                raise ValueError("Published holding is missing frozen valuation evidence")
            state = KernelPosition(quantity, quantity, numeric_cents(row.remaining_buy_cost),
                numeric_cents(row.cumulative_buy_input), numeric_cents(row.cumulative_sell_net))
            profit = (value_round(state, Fraction(price.price), fee_snapshot(fees)).result.profit_cents
                      if quantity else state.sell_net_cents - state.buy_investment_cents)
            result[row.ts_code] = StockReturnEndpoint(row.ts_code, row.round_id, row.opened_on, state, profit)
        return result
