"""Bounded historical stock-day increments from the fixed account publication."""
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid5

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.accounts import InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import PositionState
from src.biz.models.wealth.trading_assistant.publication import PublicationDay
from src.biz.services.wealth.market.trading_assistant.calculation.periods import stock_period_return
from src.biz.services.wealth.market.trading_assistant.calculation.returns import ProfitResult
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents
from .return_days import PublishedReturnDaysQuery, PublishedReturnsUnavailable
from .return_endpoints import PublishedStockEndpointsQuery, StockReturnEndpoint
from .return_scope import ReturnScopeQuery


@dataclass(frozen=True, slots=True)
class StockReturnDay:
    day: date
    endpoint: StockReturnEndpoint
    opening_cost_cents: int
    initial_cost_cents: int
    buy_input_cents: int
    sell_net_cents: int
    result: ProfitResult


def stock_day_increment(day, ending, prior, *, initial_cost_cents=0):
    """Sealed round cash differences are exact; a new round never inherits old profit."""
    if type(day) is not date or type(initial_cost_cents) is not int or initial_cost_cents < 0:
        raise ValueError("Invalid stock-day inputs")
    if prior is not None and prior.stock != ending.stock:
        raise ValueError("Mixed stock endpoints")
    if prior is not None and prior.round_id == ending.round_id:
        if initial_cost_cents or prior.opened_on != ending.opened_on or prior.state.quantity == 0:
            raise ValueError("Invalid continued round")
        opening, opening_profit = prior.state.pool_cents, prior.profit_cents
        buy = ending.state.buy_investment_cents - prior.state.buy_investment_cents
        net = ending.state.sell_net_cents - prior.state.sell_net_cents
    elif ending.opened_on == day:
        if prior is not None and prior.state.quantity:
            raise ValueError("New round cannot replace an open prior round")
        opening, opening_profit = 0, 0
        buy = ending.state.buy_investment_cents - initial_cost_cents
        net = ending.state.sell_net_cents
    else:
        raise ValueError("Published day lacks its prior round endpoint")
    if buy < 0:
        raise ValueError("Cumulative buy input decreased within a round")
    result = stock_period_return(opening + initial_cost_cents, buy,
        ending.profit_cents - opening_profit, participates=True)
    return StockReturnDay(day, ending, opening, initial_cost_cents, buy, net, result)


@dataclass(frozen=True, slots=True)
class StockReturnPage:
    items: tuple[StockReturnDay, ...]
    next_stock: str | None


class PublishedStockReturnDaysQuery:
    def __init__(self, policy):
        self.policy = policy
        self.scopes = ReturnScopeQuery(policy)
        self.days = PublishedReturnDaysQuery(policy)
        self.endpoints = PublishedStockEndpointsQuery(policy)

    def page(self, session, *, owner_id, basis, account_id, day, deadline, after_stock=None, stock=None):
        if type(day) is not date or (after_stock is not None and (not isinstance(after_stock, str) or not after_stock)):
            raise ValueError("Invalid stock-day page")
        scope = self.scopes.read(session, owner_id=owner_id, basis=basis, account_id=account_id, deadline=deadline)
        published = self.days.page(session, basis=basis, account_id=account_id, start=day, end=day, deadline=deadline)
        if not published.items:
            raise PublishedReturnsUnavailable("目标日期收益尚未发布")
        ref = next(ref for ref in basis.context.accounts if ref.accountId == str(account_id))
        generation_id = UUID(ref.publishedGenerationId)
        query = select(PositionState.ts_code).where(PositionState.account_id == account_id,
            PositionState.day_result_id == published.items[0].day_result_id).distinct()
        if after_stock is not None:
            query = query.where(PositionState.ts_code > after_stock)
        if stock is not None:
            query = query.where(PositionState.ts_code == stock)
        apply_sql_budget(session, deadline, self.policy)
        codes = session.scalars(query.order_by(PositionState.ts_code).limit(self.policy.page_rows + 1)).all()
        selected = codes[:self.policy.page_rows]
        ending = self.endpoints.read(session, account_id=account_id, generation_id=generation_id,
                                     day=day, codes=selected, deadline=deadline)
        if set(ending) != set(selected):
            raise ValueError("Published stock selection lacks sealed endpoints")
        apply_sql_budget(session, deadline, self.policy)
        previous = session.scalar(select(func.max(PublicationDay.trade_date)).where(
            PublicationDay.account_id == account_id, PublicationDay.generation_id == generation_id,
            PublicationDay.trade_date < day))
        opening = self.endpoints.read(session, account_id=account_id, generation_id=generation_id,
            day=previous, codes=selected, deadline=deadline) if previous else {}
        apply_sql_budget(session, deadline, self.policy)
        initial = dict(session.execute(select(InitialPosition.ts_code,
            InitialPosition.cost_price * InitialPosition.quantity).where(
                InitialPosition.account_id == account_id, InitialPosition.initialization_id == scope.initialization_id,
                InitialPosition.opened_on == day, InitialPosition.ts_code.in_(selected))).all()) if selected else {}
        items = []
        for code in selected:
            endpoint = ending[code]
            injected = (numeric_cents(initial[code]) if code in initial and endpoint.round_id == uuid5(account_id,
                f"INITIAL:{scope.initialization_id}:{code}") else 0)
            items.append(stock_day_increment(day, endpoint, opening.get(code), initial_cost_cents=injected))
        deadline.remaining_ms()
        return StockReturnPage(tuple(items), selected[-1] if len(codes) > self.policy.page_rows else None)
