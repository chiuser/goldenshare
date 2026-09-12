"""Bounded current holding valuation from one owned, published read context.

This is an internal M3 projection, not the full positions HTTP response. The
caller supplies the verified expected trading day; older data cannot pass as
today's price. Historical snapshots are never changed by this query.
"""
from dataclasses import dataclass
from datetime import date, datetime
from fractions import Fraction
from uuid import UUID

from sqlalchemy import and_, func, select

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult, PositionState
from src.biz.models.wealth.trading_assistant.calculation_inputs import ValuationBasis
from src.biz.models.wealth.trading_assistant.publication import PublicationDay
from src.biz.services.wealth.market.trading_assistant.calculation.daily import PositionState as KernelPosition
from src.biz.services.wealth.market.trading_assistant.calculation.returns import RoundValuation, value_round
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents, numeric_integer
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .read_context import OwnedReadContext


class PublishedPositionsUnavailable(RuntimeError):
    """No complete/current publication; caller must not present Ready values."""


@dataclass(frozen=True, slots=True)
class CurrentHoldingValue:
    account_id: UUID
    stock_code: str
    round_id: UUID
    quantity: int
    fee_version_id: UUID
    valuation: RoundValuation


@dataclass(frozen=True, slots=True)
class CurrentHoldingPage:
    items: tuple[CurrentHoldingValue, ...]
    next_stock: str | None


class CurrentPositionsQuery:
    def __init__(self, policy):
        self.policy = policy

    def page(self, session, *, basis: OwnedReadContext, account_id: UUID, trade_date: date,
             deadline, after_stock: str | None = None) -> CurrentHoldingPage:
        # basis is constructed by CurrentReadContextQuery in this same read
        # transaction, never by deserializing a client-provided version array.
        account = next((a for a in basis.context.accounts if a.accountId == str(account_id)), None)
        fees = next((f for f in basis.fees if f.account_id == account_id), None)
        if account is None or fees is None:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        if account.publishedGenerationId is None:
            raise PublishedPositionsUnavailable("账户收益尚未发布")
        apply_sql_budget(session, deadline, self.policy)
        generation_id = UUID(account.publishedGenerationId)
        generation = session.execute(select(CalculationGeneration.fact_version,
            CalculationGeneration.target_version, CalculationGeneration.stage).where(
            CalculationGeneration.account_id == account_id,
            CalculationGeneration.generation_id == generation_id)).one_or_none()
        if generation is None or (generation.fact_version, generation.target_version, generation.stage) != (
                int(account.factVersion), int(account.calculationTargetVersion), "PUBLISHED"):
            raise PublishedPositionsUnavailable("当前事实尚未完成核算发布")
        day = session.execute(select(DayResult.day_result_id, DayResult.origin_generation_id,
            DayResult.status).join(PublicationDay, and_(PublicationDay.account_id == DayResult.account_id,
            PublicationDay.day_result_id == DayResult.day_result_id,
            PublicationDay.trade_date == DayResult.trade_date)).where(
            PublicationDay.account_id == account_id, PublicationDay.generation_id == generation_id,
            PublicationDay.trade_date == trade_date)).one_or_none()
        if day is None or day.status != "SEALED":
            raise PublishedPositionsUnavailable("目标交易日估值尚未就绪")
        query = select(PositionState, ValuationBasis, func.count().over(partition_by=PositionState.ts_code)).outerjoin(
            ValuationBasis, and_(ValuationBasis.account_id == PositionState.account_id,
                ValuationBasis.generation_id == day.origin_generation_id,
                ValuationBasis.trade_date == trade_date, ValuationBasis.ts_code == PositionState.ts_code)).where(
            PositionState.account_id == account_id, PositionState.day_result_id == day.day_result_id,
            PositionState.quantity > 0)
        if after_stock is not None:
            query = query.where(PositionState.ts_code > after_stock)
        rows = session.execute(query.order_by(PositionState.ts_code, PositionState.round_id)
                               .limit(self.policy.page_rows + 1)).all()
        result = []
        for state, price, count in rows[:self.policy.page_rows]:
            if count != 1:
                raise ValueError("Multiple current rounds for the same stock/day")
            if price is None or price.quality != "READY" or price.price is None:
                raise PublishedPositionsUnavailable("持仓估值依据尚未就绪")
            if price.valuation_at > datetime.fromisoformat(basis.context.targetThrough.replace("Z", "+00:00")):
                raise PublishedPositionsUnavailable("持仓估值晚于读取截止")
            quantity = numeric_integer(state.quantity)
            kernel = KernelPosition(quantity, quantity, numeric_cents(state.remaining_buy_cost),
                numeric_cents(state.cumulative_buy_input), numeric_cents(state.cumulative_sell_net))
            result.append(CurrentHoldingValue(account_id, state.ts_code, state.round_id, quantity,
                fees.fee_version_id, value_round(kernel, Fraction(price.price), fees.fees)))
        deadline.remaining_ms()
        return CurrentHoldingPage(tuple(result), result[-1].stock_code if len(rows) > self.policy.page_rows else None)
