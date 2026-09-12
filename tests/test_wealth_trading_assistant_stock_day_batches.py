"""One stock spanning database batches; checkpoints share business transactions."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, update, func
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, deadline
from tests.test_wealth_trading_assistant_calculation_ledger import seed_sells, DAY
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import Recalculation, DayResult, PositionState, ClosedTrade
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.services.wealth.market.trading_assistant.calculation.daily import PositionState as Opening
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputs, CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import RecalculationExecution
from src.biz.services.wealth.market.trading_assistant.stock_day_batches import StockDayBatches


def setup(engine):
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        account, _ = seed_sells(conn, [100, 100, 100])
        conn.execute(update(Account).where(Account.account_id == account).values(fact_version=4))
        conn.execute(insert(Recalculation).values(account_id=account, target_version=1, affected_from_date=DAY,
            next_attempt_at=now, fence=0, transient_failure_count=0, updated_at=now))
    execution = RecalculationExecution(replace(TradingAssistantExecutionPolicyV1(), page_rows=2))
    with Session(engine) as session, session.begin():
        lease = execution.claim(session, executor_id="day-test", deadline=deadline())
        assert lease.account_id == account
    with Session(engine) as session, session.begin():
        generation = CalculationInputs(execution).prepare_generation(session, lease, from_date=DAY,
            through_date=DAY, rule_version=1, deadline=deadline())
        day = uuid4()
        session.add(DayResult(day_result_id=day, account_id=account, origin_generation_id=generation,
                             trade_date=DAY, input_digest=b"x" * 32, status="BUILDING"))
    return StockDayBatches(execution), lease, dict(generation_id=generation, day_result_id=day,
        stock="000001.SZ", opening=Opening(300, 300, 1000000, 1000000, 0)), uuid4()


def test_batched_summary_costs_restart_and_idempotence(migrated):
    service, lease, args, round_id = setup(migrated)
    for expected in (False, False, True, True):
        with Session(migrated) as session, session.begin():
            assert service.summarize_page(session, lease, **args, deadline=deadline()) == expected
    kwargs = args | dict(round_id=round_id, opened_on=DAY)
    with Session(migrated) as session, session.begin():
        assert not service.close_page(session, lease, **kwargs, deadline=deadline())
    with pytest.raises(RuntimeError, match="crash"):
        with Session(migrated) as session, session.begin():
            service.close_page(session, lease, **kwargs, deadline=deadline())
            raise RuntimeError("crash")
    with Session(migrated) as session:
        assert session.scalar(select(func.count()).select_from(ClosedTrade).where(
            ClosedTrade.day_result_id == args["day_result_id"])) == 2
        assert session.get(Account, lease.account_id).published_generation_id is None
    resumed = StockDayBatches(service.execution)
    with pytest.raises(CalculationInputMismatch, match="Round identity"):
        with Session(migrated) as session, session.begin():
            resumed.close_page(session, lease, **(kwargs | {"round_id": uuid4()}), deadline=deadline())
    for expected in (False, True, True):
        with Session(migrated) as session, session.begin():
            assert resumed.close_page(session, lease, **kwargs, deadline=deadline()) == expected
    with Session(migrated) as session:
        rows = session.scalars(select(ClosedTrade).where(ClosedTrade.day_result_id == args["day_result_id"])
                               .order_by(ClosedTrade.sell_ledger_id)).all()
        assert [str(row.allocated_cost) for row in rows] == ["3333.34", "3333.33", "3333.33"]
        assert sum(row.profit_amount for row in rows) == -9700
        state = session.get(PositionState, (lease.account_id, args["day_result_id"], args["stock"], round_id))
        assert state.quantity == state.remaining_buy_cost == 0
        assert state.cumulative_buy_input == 10000 and state.cumulative_sell_net == 300
        assert state.closed_on == DAY
        assert session.get(DayResult, args["day_result_id"]).status == "BUILDING"
    with migrated.begin() as conn:
        conn.execute(update(Recalculation).where(Recalculation.account_id == lease.account_id)
                     .values(next_attempt_at=datetime.now(timezone.utc)+timedelta(days=2)))
