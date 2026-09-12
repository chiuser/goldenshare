"""Real calendar and sealed-state selection, no synthetic historical trades."""
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from src.biz.models.wealth.trading_assistant.accounts import Account, InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult, PositionState
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.biz.queries.wealth.market.trading_assistant.calculation_stocks import stock_day_page
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.stock_openings import read_stock_opening

THU, FRI, SAT, MON = date(2026,9,10), date(2026,9,11), date(2026,9,12), date(2026,9,14)
POLICY = TradingAssistantExecutionPolicyV1()


def test_initial_date_available_quantity_and_adjacent_day(database):
    now = datetime.now(timezone.utc)
    generation, thursday, friday = uuid4(), uuid4(), uuid4()
    with database.begin() as conn:
        account, initialization, _ = seed_account(conn)
        conn.execute(insert(CalculationGeneration).values(generation_id=generation, account_id=account,
            target_version=1, fact_version=1, initialization_id=initialization, rule_version=1,
            from_date=THU, through_date=MON, stage="CALCULATING", completed_trade_date_count=0,
            last_business_updated_at=now))
        conn.execute(insert(InitialPosition).values(account_id=account, initialization_id=initialization,
            ts_code="000001.SZ", client_row_id="one", opened_on=THU, quantity=1000,
            available_quantity=600, cost_price="10.00"))
        conn.execute(insert(TradeCalendar), [dict(exchange="SSE", trade_date=day, is_open=opened, pretrade_date=prev)
            for day, opened, prev in ((THU,True,date(2026,9,9)),(FRI,True,THU),(SAT,False,FRI),(MON,True,FRI))])
    with Session(database) as session, session.begin():
        acct, gen = session.get(Account, account), session.get(CalculationGeneration, generation)
        args = dict(account=acct, generation=gen, stock="000001.SZ", policy=POLICY)
        first = read_stock_opening(session, **args, trade_date=THU, previous_day_result_id=None,
                                   deadline=Deadline.after_ms(2000))
        assert first.state.available_quantity == first.state.quantity == 1000
        assert first.state.pool_cents == first.state.buy_investment_cents == 1000000
        assert first.state.sell_net_cents == 0
        assert first == read_stock_opening(session, **args, trade_date=THU, previous_day_result_id=None,
                                           deadline=Deadline.after_ms(2000))
        scope = dict(account_id=account, initialization_id=initialization, fact_version=1,
            trade_date=THU, previous_day_result_id=None, limit=1, policy=POLICY)
        assert session.scalars(stock_day_page(owner_id=1, **scope)).all() == ["000001.SZ"]
        assert session.scalars(stock_day_page(owner_id=2, **scope)).all() == []
        for day_id, day, quantity, pool in ((thursday,THU,1000,10000),(friday,FRI,600,6000)):
            session.add(DayResult(day_result_id=day_id, account_id=account, origin_generation_id=generation,
                trade_date=day, input_digest=b"a"*32, status="SEALED", sealed_at=now))
            session.flush()
            session.add(PositionState(account_id=account, day_result_id=day_id, ts_code="000001.SZ",
                round_id=first.round_id, opened_on=THU, quantity=quantity, remaining_buy_cost=pool,
                cumulative_buy_input=10000, cumulative_sell_net=10000-pool))
        session.flush()
        today = read_stock_opening(session, **args, trade_date=FRI, previous_day_result_id=thursday,
                                   deadline=Deadline.after_ms(2000))
        assert today.state.quantity == 1000 and today.state.available_quantity == 600
        monday = read_stock_opening(session, **args, trade_date=MON, previous_day_result_id=friday,
                                    deadline=Deadline.after_ms(2000))
        assert monday.state.quantity == monday.state.available_quantity == 600
        assert monday.round_id == first.round_id
        assert session.scalars(stock_day_page(owner_id=1, **(scope | {
            "trade_date":MON, "previous_day_result_id":friday}))).all() == ["000001.SZ"]
        for day, previous in ((MON,thursday),(FRI,None),(SAT,friday)):
            with pytest.raises(CalculationInputMismatch):
                read_stock_opening(session, **args, trade_date=day, previous_day_result_id=previous,
                                   deadline=Deadline.after_ms(2000))
