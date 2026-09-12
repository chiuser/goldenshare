"""Build one stock's opening from the fixed initialization or a sealed prior day."""
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid5

from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.accounts import InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import DayResult, PositionState
from src.biz.queries.wealth.market.trading_assistant.effective_ledger import effective_ledger
from .calculation.daily import PositionState as Opening
from .calculation_inputs import CalculationInputMismatch
from .market_facts import MarketFactsReader
from .persistence_values import numeric_cents, numeric_integer


@dataclass(frozen=True, slots=True)
class StockOpening:
    state: Opening
    round_id: UUID
    opened_on: date


def read_stock_opening(session, *, account, generation, trade_date, stock,
                       previous_day_result_id, policy, deadline):
    if (generation.account_id != account.account_id or generation.fact_version != account.fact_version
            or generation.initialization_id != account.current_initialization_id
            or not generation.from_date <= trade_date <= generation.through_date):
        raise CalculationInputMismatch("Opening scope does not match the fixed account inputs")
    calendar = MarketFactsReader(policy).read_calendar(session, "SSE", trade_date, trade_date, deadline).days[0]
    if not calendar.is_open:
        raise CalculationInputMismatch("Stock calculations require a confirmed trading date")
    previous = session.get(DayResult, previous_day_result_id) if previous_day_result_id else None
    if previous_day_result_id is not None and (previous is None or previous.account_id != account.account_id
            or previous.status != "SEALED" or previous.trade_date != calendar.previous_trade_date):
        raise CalculationInputMismatch("Opening must refer to the immediately preceding sealed trading day")
    initial = session.get(InitialPosition, (generation.initialization_id, stock))
    if initial is not None and initial.account_id != account.account_id:
        raise CalculationInputMismatch("Foreign initialization stock")
    prior = session.scalars(select(PositionState).where(PositionState.account_id == account.account_id,
        PositionState.day_result_id == previous_day_result_id, PositionState.ts_code == stock).limit(2)).all() if previous else []
    if len(prior) > 1:
        raise CalculationInputMismatch("Ambiguous prior stock round")
    if prior and numeric_integer(prior[0].quantity) > 0:
        row = prior[0]
        quantity = numeric_integer(row.quantity)
        available = (initial.available_quantity if trade_date == account.initialized_on
                     and initial is not None and row.opened_on == initial.opened_on else quantity)
        return StockOpening(Opening(quantity, available, numeric_cents(row.remaining_buy_cost),
            numeric_cents(row.cumulative_buy_input), numeric_cents(row.cumulative_sell_net)), row.round_id, row.opened_on)
    if initial is not None and initial.opened_on == trade_date:
        pool = initial.quantity * numeric_cents(initial.cost_price)
        available = initial.available_quantity if trade_date == account.initialized_on else initial.quantity
        return StockOpening(Opening(initial.quantity, available, pool, pool, 0),
            uuid5(account.account_id, f"INITIAL:{generation.initialization_id}:{stock}"), trade_date)
    if initial is not None and initial.opened_on < trade_date and previous is None:
        raise CalculationInputMismatch("Historical initial holding has no sealed preceding state")
    facts = effective_ledger(owner_id=account.owner_id, account_id=account.account_id,
                             fact_version=generation.fact_version)
    first_buy = session.scalar(select(facts.c.ledger_id).where(facts.c.kind == "TRADE", facts.c.direction == "BUY",
        facts.c.ts_code == stock, facts.c.occurred_on == trade_date).order_by(facts.c.ledger_id).limit(1))
    if first_buy is None:
        raise CalculationInputMismatch("No opening holding or new buy exists for this stock")
    return StockOpening(Opening(0, 0, 0, 0, 0), uuid5(account.account_id, f"BUY:{first_buy}:{stock}"), trade_date)
