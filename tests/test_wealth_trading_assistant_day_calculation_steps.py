"""One committed unit per call, recovery from fresh Sessions and service objects."""
from datetime import timedelta
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, deadline, retire, DAY, AT, fact
from tests.test_wealth_trading_assistant_publication_storage import publication_db
from src.biz.models.wealth.trading_assistant.accounts import Account, InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import DayResult, CalculationGeneration
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot
from src.biz.services.wealth.market.trading_assistant.calendar_inputs import CalendarInputs
from src.biz.services.wealth.market.trading_assistant.day_calculation_steps import DayCalculationSteps
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import CalculationExecutionLost
from src.foundation.models.core.trade_calendar import TradeCalendar


@pytest.mark.parametrize("held", [False, True])
def test_day_steps_resume_rollback_seal_and_never_publish(publication_db, held):
    inputs, lease, generation, fee = setup(publication_db)
    execution = inputs.execution
    day_id = uuid4()
    args = dict(generation_id=generation, day_result_id=day_id,
        previous_day_result_id=None, valuation_at=AT)
    with Session(publication_db) as session, session.begin():
        if session.get(TradeCalendar,("SSE",DAY)) is None:
            session.add(TradeCalendar(exchange="SSE",trade_date=DAY,is_open=True,pretrade_date=DAY-timedelta(days=1)))
        session.add(DayResult(day_result_id=day_id,account_id=lease.account_id,
            origin_generation_id=generation,trade_date=DAY,input_digest=b"a"*32,status="BUILDING"))
        if held:
            account = session.get(Account,lease.account_id)
            session.add(InitialPosition(initialization_id=account.current_initialization_id,
                account_id=lease.account_id,ts_code="000001.SZ",client_row_id="one",opened_on=DAY,
                quantity=1000,available_quantity=1000,cost_price="10.00"))
            inputs.save_valuation_page(session,lease,generation_id=generation,facts=(fact(price="11.00"),),
                fee_version_id=fee,valuation_at=AT,after_stock=None,deadline=deadline())
        CalendarInputs(execution).freeze_next(session,lease,generation_id=generation,deadline=deadline())
    def count(session):
        return session.scalar(select(func.count()).select_from(CalculationBatch).where(
            CalculationBatch.account_id==lease.account_id,CalculationBatch.generation_id==generation))
    stages = []
    for _ in range(40):
        with Session(publication_db) as session:
            before = count(session)
        # Model a lost process before commit at every distinct unit boundary.
        with pytest.raises(RuntimeError,match="lost before commit"):
            with Session(publication_db) as session, session.begin():
                proposed = DayCalculationSteps(execution).step(session,lease,**args,deadline=deadline())
                raise RuntimeError("lost before commit")
        with Session(publication_db) as session:
            assert count(session)==before
            assert session.get(DayResult,day_id).status=="BUILDING"
        with Session(publication_db) as session, session.begin():
            stage = DayCalculationSteps(execution).step(session,lease,**args,deadline=deadline())
            assert stage==proposed
            assert count(session)-before in (0,1)
        stages.append(stage)
        if stage=="SEALED":
            break
    else:
        pytest.fail("Prepared day did not finish within its bounded fixture unit count")
    assert "ACCOUNT_CASH_CHECK" in stages and "ACCOUNT_STOCKS_CHECK" in stages
    if held:
        assert all(stage in stages for stage in ("STOCK_SUMMARY","STOCK_BASE","STOCK_CLOSED",
            "STOCK_SUMMARY_CHECK","STOCK_BASE_CHECK","STOCK_CLOSED_CHECK"))
    with Session(publication_db) as session, session.begin():
        assert DayCalculationSteps(execution).step(session,lease,**args,deadline=deadline())=="SEALED"
        assert session.get(CalculationGeneration,generation).completed_trade_date_count==1
        assert session.get(Account,lease.account_id).published_generation_id is None
        snapshot=session.get(AccountSnapshot,(lease.account_id,day_id))
        assert str(snapshot.holding_profit_amount)==("989.50" if held else "0.00")
        assert snapshot.stock_market_value==(11000 if held else 0)
    with pytest.raises(CalculationInputMismatch,match="outside"):
        with Session(publication_db) as session, session.begin():
            DayCalculationSteps(execution).step(session,lease,**(args|dict(day_result_id=uuid4())),deadline=deadline())
    with pytest.raises(CalculationExecutionLost):
        with Session(publication_db) as session, session.begin():
            DayCalculationSteps(execution).step(session,replace(lease,fence=lease.fence+1),**args,deadline=deadline())
    retire(publication_db,lease)


def test_missing_valuation_cannot_be_sealed_as_zero(publication_db):
    inputs,lease,generation,_=setup(publication_db)
    day_id=uuid4()
    with Session(publication_db) as session, session.begin():
        account=session.get(Account,lease.account_id)
        session.add(InitialPosition(initialization_id=account.current_initialization_id,
            account_id=lease.account_id,ts_code="000001.SZ",client_row_id="missing",opened_on=DAY,
            quantity=100,available_quantity=100,cost_price="10.00"))
        session.add(DayResult(day_result_id=day_id,account_id=lease.account_id,
            origin_generation_id=generation,trade_date=DAY,input_digest=b"a"*32,status="BUILDING"))
        if session.get(TradeCalendar,("SSE",DAY)) is None:
            session.add(TradeCalendar(exchange="SSE",trade_date=DAY,is_open=True,pretrade_date=DAY-timedelta(days=1)))
        CalendarInputs(inputs.execution).freeze_next(session,lease,generation_id=generation,deadline=deadline())
    with pytest.raises(CalculationInputMismatch):
        for _ in range(30):
            with Session(publication_db) as session, session.begin():
                DayCalculationSteps(inputs.execution).step(session,lease,generation_id=generation,
                    day_result_id=day_id,previous_day_result_id=None,valuation_at=AT,deadline=deadline())
    with Session(publication_db) as session:
        assert session.get(AccountSnapshot,(lease.account_id,day_id)) is None
        assert session.get(DayResult,day_id).status=="BUILDING"
        assert session.get(Account,lease.account_id).published_generation_id is None
    retire(publication_db,lease)


def test_next_trading_day_uses_sealed_predecessor_over_weekend(publication_db):
    inputs,lease,generation,fee=setup(publication_db)
    monday=DAY+timedelta(days=3)
    first_id,second_id=uuid4(),uuid4()
    with Session(publication_db) as session, session.begin():
        session.get(CalculationGeneration,generation).through_date=monday
        account=session.get(Account,lease.account_id)
        session.add(InitialPosition(initialization_id=account.current_initialization_id,
            account_id=lease.account_id,ts_code="000001.SZ",client_row_id="holding",opened_on=DAY,
            quantity=1000,available_quantity=1000,cost_price="10.00"))
        for offset in range(4):
            current=DAY+timedelta(days=offset)
            if session.get(TradeCalendar,("SSE",current)) is None:
                session.add(TradeCalendar(exchange="SSE",trade_date=current,is_open=offset in (0,3),
                    pretrade_date=DAY-timedelta(days=1) if offset==0 else DAY))
        for day_id,business_date,price in ((first_id,DAY,"11.00"),(second_id,monday,"12.00")):
            session.add(DayResult(day_result_id=day_id,account_id=lease.account_id,
                origin_generation_id=generation,trade_date=business_date,input_digest=b"a"*32,status="BUILDING"))
            inputs.save_valuation_page(session,lease,generation_id=generation,
                facts=(replace(fact(price=price),valuation_date=business_date,price_date=business_date),),
                fee_version_id=fee,valuation_at=AT+(business_date-DAY),after_stock=None,deadline=deadline())
        assert CalendarInputs(inputs.execution).freeze_next(session,lease,generation_id=generation,deadline=deadline())
    def advance(session,day_id,previous,business_date):
        return DayCalculationSteps(inputs.execution).step(session,lease,generation_id=generation,
            day_result_id=day_id,previous_day_result_id=previous,
            valuation_at=AT+(business_date-DAY),deadline=deadline())
    # The missing prior position must not be interpreted as an empty account.
    with pytest.raises(CalculationInputMismatch):
        with Session(publication_db) as session, session.begin():
            advance(session,second_id,first_id,monday)
    for day_id,previous,business_date in ((first_id,None,DAY),(second_id,first_id,monday)):
        for _ in range(30):
            with Session(publication_db) as session, session.begin():
                stage=advance(session,day_id,previous,business_date)
            if stage=="SEALED":
                break
        else:
            pytest.fail("Trading day did not finish")
    with Session(publication_db) as session:
        snapshot=session.get(AccountSnapshot,(lease.account_id,second_id))
        assert str(snapshot.day_profit_amount)=="999.50"
        assert snapshot.stock_market_value==12000
        assert snapshot.closed_trade_count==0
        assert session.get(CalculationGeneration,generation).completed_trade_date_count==2
    from src.biz.services.wealth.market.trading_assistant.generation_publication import GenerationPublication
    from src.biz.models.wealth.trading_assistant.publication import PublicationDay, PublicationReceipt
    from src.biz.models.wealth.trading_assistant.calculation import Recalculation
    with pytest.raises(CalculationExecutionLost):
        with Session(publication_db) as session, session.begin():
            session.get(Account,lease.account_id).calculation_target_version+=1
            session.get(Recalculation,lease.account_id).target_version+=1
            session.flush()
            GenerationPublication(inputs.execution).advance(session,lease,
                generation_id=generation,deadline=deadline())
    for expected in ["MANIFEST"]*4+["MANIFEST_CHECK"]*4+["PUBLISHED"]:
        with pytest.raises(RuntimeError,match="publication interrupted"):
            with Session(publication_db) as session, session.begin():
                assert GenerationPublication(inputs.execution).advance(session,lease,
                    generation_id=generation,deadline=deadline())==expected
                raise RuntimeError("publication interrupted")
        with Session(publication_db) as session:
            assert session.get(Account,lease.account_id).published_generation_id is None
            assert session.get(PublicationReceipt,(lease.account_id,generation)) is None
            assert session.get(Recalculation,lease.account_id) is not None
        with Session(publication_db) as session, session.begin():
            stage=GenerationPublication(inputs.execution).advance(session,lease,
                generation_id=generation,deadline=deadline())
            assert stage==expected
    with Session(publication_db) as session:
        days=session.scalars(select(PublicationDay.trade_date).where(
            PublicationDay.account_id==lease.account_id,PublicationDay.generation_id==generation)
            .order_by(PublicationDay.trade_date)).all()
        assert days==[DAY,monday]  # Weekend dates prove coverage but are not stock snapshots.
        assert session.get(Account,lease.account_id).published_generation_id==generation
        assert session.get(Recalculation,lease.account_id) is None
        assert GenerationPublication.confirmed(session,owner_id=1,account_id=lease.account_id,
            generation_id=generation,target_version=lease.target_version)
        assert not GenerationPublication.confirmed(session,owner_id=2,account_id=lease.account_id,
            generation_id=generation,target_version=lease.target_version)
    retire(publication_db,lease)


def test_multi_page_sales_complete_without_double_count(publication_db):
    from tests.test_wealth_trading_assistant_stock_day_batches import setup as setup_sales
    from src.biz.models.wealth.trading_assistant.calculation import ClosedTrade
    stocks, lease, stock_args, _ = setup_sales(publication_db)
    generation, day_id = stock_args["generation_id"], stock_args["day_result_id"]
    with Session(publication_db) as session, session.begin():
        account = session.get(Account,lease.account_id)
        session.add(InitialPosition(initialization_id=account.current_initialization_id,
            account_id=lease.account_id,ts_code="000001.SZ",client_row_id="sold",opened_on=DAY,
            quantity=300,available_quantity=300,cost_price="100.00"))
        if session.get(TradeCalendar,("SSE",DAY)) is None:
            session.add(TradeCalendar(exchange="SSE",trade_date=DAY,is_open=True,pretrade_date=DAY-timedelta(days=1)))
        CalendarInputs(stocks.execution).freeze_next(session,lease,generation_id=generation,deadline=deadline())
    stages=[]
    for _ in range(60):
        with Session(publication_db) as session, session.begin():
            stage=DayCalculationSteps(stocks.execution).step(session,lease,
                generation_id=generation,day_result_id=day_id,previous_day_result_id=None,
                valuation_at=AT,deadline=deadline())
        stages.append(stage)
        if stage=="SEALED":
            break
    else:
        pytest.fail("Sales did not complete")
    assert stages.count("STOCK_CLOSED")==3
    assert stages.count("STOCK_CLOSED_CHECK")==3
    with Session(publication_db) as session:
        rows=session.scalars(select(ClosedTrade).where(ClosedTrade.day_result_id==day_id)).all()
        assert len(rows)==3 and sum(row.allocated_cost for row in rows)==30000
        assert sum(row.net_proceeds for row in rows)==300
        snapshot=session.get(AccountSnapshot,(lease.account_id,day_id))
        assert snapshot.closed_trade_count==3 and snapshot.cash_amount==300
        assert snapshot.stock_market_value==0
    retire(publication_db,lease)
