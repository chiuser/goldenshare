"""Computed stock and cash stages join into a candidate, never an early publication."""
from datetime import timedelta
from uuid import uuid4, uuid5
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, deadline, retire, DAY, AT, fact
from tests.test_wealth_trading_assistant_publication_storage import publication_db
from src.biz.models.wealth.trading_assistant.accounts import Account, InitialPosition, FeeVersion
from src.biz.queries.wealth.market.trading_assistant.read_context import CurrentReadContextQuery
from src.biz.queries.wealth.market.trading_assistant.current_positions import CurrentPositionsQuery, PublishedPositionsUnavailable
from src.biz.queries.wealth.market.trading_assistant.calculation_status import CalculationStatusQuery
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from src.biz.models.wealth.trading_assistant.calculation import DayResult
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot
from src.biz.services.wealth.market.trading_assistant.account_day_batches import AccountDayBatches
from src.biz.services.wealth.market.trading_assistant.calculation.daily import PositionState
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.cash_balances import CashBalances
from src.biz.services.wealth.market.trading_assistant.cash_day_batches import CashDayBatches
from src.biz.services.wealth.market.trading_assistant.snapshot_candidates import SnapshotCandidates
from src.biz.services.wealth.market.trading_assistant.stock_day_batches import StockDayBatches
from src.biz.services.wealth.market.trading_assistant.day_scope_verification import DayScopeVerification
from src.biz.services.wealth.market.trading_assistant.day_sealing import DaySealing
from src.biz.services.wealth.market.trading_assistant.stock_day_verification import StockDayVerification
from src.biz.services.wealth.market.trading_assistant.calendar_inputs import CalendarInputs
from src.biz.services.wealth.market.trading_assistant.generation_publication import GenerationPublication
from src.foundation.models.core.trade_calendar import TradeCalendar


@pytest.mark.parametrize("held", [False, True])
def test_snapshot_composition_requires_completed_inputs(publication_db, held):
    inputs, lease, generation, fee = setup(publication_db)
    execution = inputs.execution
    day = uuid4()
    args = dict(generation_id=generation, day_result_id=day)
    snapshots = SnapshotCandidates(execution)
    with Session(publication_db) as session, session.begin():
        if session.get(TradeCalendar, ("SSE", DAY)) is None:
            session.add(TradeCalendar(exchange="SSE", trade_date=DAY, is_open=True, pretrade_date=DAY-timedelta(days=1)))
        session.add(DayResult(day_result_id=day, account_id=lease.account_id, origin_generation_id=generation,
            trade_date=DAY, input_digest=b"a"*32, status="BUILDING"))
        if held:
            account = session.get(Account, lease.account_id)
            session.add(InitialPosition(initialization_id=account.current_initialization_id,
                account_id=lease.account_id, ts_code="000001.SZ", client_row_id="initial-1", opened_on=DAY,
                quantity=1000, available_quantity=1000, cost_price="10.00"))
            inputs.save_valuation_page(session, lease, generation_id=generation,
                facts=(fact(price="11.00"),), fee_version_id=fee, valuation_at=AT,
                after_stock=None, deadline=deadline())
        assert CalendarInputs(execution).freeze_next(session, lease, generation_id=generation, deadline=deadline())
    with pytest.raises(CalculationInputMismatch, match="Complete stock and cash"):
        with Session(publication_db) as session, session.begin():
            snapshots.save(session, lease, **args, valuation_at=AT, deadline=deadline())
    if held:
        stock_args = args | dict(stock="000001.SZ", opening=PositionState(1000, 1000, 1000000, 1000000, 0))
        with Session(publication_db) as session, session.begin():
            stocks = StockDayBatches(execution)
            assert stocks.summarize_page(session, lease, **stock_args, deadline=deadline())
            assert stocks.prepare_sell_page(session, lease, **stock_args, deadline=deadline())
            initial_id = session.get(Account, lease.account_id).current_initialization_id
            round_id = uuid5(lease.account_id, f"INITIAL:{initial_id}:000001.SZ")
            assert stocks.close_page(session, lease, **stock_args, round_id=round_id, opened_on=DAY, deadline=deadline())
    for expected in ([False, True] if held else [True]):
        with Session(publication_db) as session, session.begin():
            assert DayScopeVerification(execution).verify_next(session, lease, **args,
                previous_day_result_id=None, deadline=deadline()) == expected
    for expected in ([False, True] if held else [True]):
        with Session(publication_db) as session, session.begin():
            assert AccountDayBatches(execution).reduce_page(session, lease, **args,
                previous_day_result_id=None, deadline=deadline()) == expected
    for page in range(1, 3 if held else 2):
        with Session(publication_db) as session, session.begin():
            assert AccountDayBatches(execution).verify_page(session, lease, **args,
                previous_day_result_id=None, page_key=f"{page:020d}", deadline=deadline()) == (page == (2 if held else 1))
    with Session(publication_db) as session, session.begin():
        cash = CashDayBatches(execution)
        cash_args = dict(generation_id=generation, business_date=DAY)
        assert cash.reduce_page(session, lease, **cash_args, deadline=deadline())
        cash.verify_page(session, lease, **cash_args, page_key=f"{1:020d}", deadline=deadline())
        assert CashBalances(execution).close_date(session, lease, **cash_args, deadline=deadline()) == 0
    with pytest.raises(RuntimeError, match="crash"):
        with Session(publication_db) as session, session.begin():
            snapshots.save(session, lease, **args, valuation_at=AT, deadline=deadline())
            raise RuntimeError("crash")
    for _ in range(2):
        with Session(publication_db) as session, session.begin():
            SnapshotCandidates(execution).save(session, lease, **args, valuation_at=AT, deadline=deadline())
    with Session(publication_db) as session:
        saved = session.get(AccountSnapshot, (lease.account_id, day))
        assert saved.cash_amount == 0
        assert saved.stock_market_value == saved.total_assets == (11000 if held else 0)
        assert saved.day_profit_amount == (989.50 if held else None)
        assert saved.closed_trade_count == 0
        assert session.get(DayResult, day).status == "BUILDING"
        assert session.get(Account, lease.account_id).published_generation_id is None
    with pytest.raises(CalculationInputMismatch, match="cannot be overwritten"):
        with Session(publication_db) as session, session.begin():
            snapshots.save(session, lease, **args, valuation_at=AT+timedelta(minutes=1), deadline=deadline())
    if held:
        with pytest.raises(CalculationInputMismatch, match="unverified"):
            with Session(publication_db) as session, session.begin():
                DaySealing(execution).seal(session, lease, **args, deadline=deadline())
        for stage in ("STOCK_SUMMARY", "STOCK_BASE", "STOCK_CLOSED"):
            with Session(publication_db) as session, session.begin():
                assert StockDayVerification(execution).verify_page(session, lease, **stock_args,
                    round_id=round_id, opened_on=DAY, stage=stage, page_key=f"{1:020d}", deadline=deadline())
    with pytest.raises(RuntimeError, match="crash"):
        with Session(publication_db) as session, session.begin():
            DaySealing(execution).seal(session, lease, **args, deadline=deadline())
            raise RuntimeError("crash")
    for _ in range(2):
        with Session(publication_db) as session, session.begin():
            assert len(DaySealing(execution).seal(session, lease, **args, deadline=deadline())) == 32
    with Session(publication_db) as session:
        assert session.get(DayResult, day).status == "SEALED"
        assert session.get(Account, lease.account_id).published_generation_id is None
    publisher = GenerationPublication(execution)
    with pytest.raises(CalculationInputMismatch):
        with Session(publication_db) as session, session.begin():
            publisher.publish(session, lease, generation_id=generation, deadline=deadline())
    for _ in range(2):
        with Session(publication_db) as session, session.begin():
            assert publisher.append_next(session, lease, generation_id=generation, deadline=deadline())
    with pytest.raises(CalculationInputMismatch, match="readback"):
        with Session(publication_db) as session, session.begin():
            publisher.publish(session, lease, generation_id=generation, deadline=deadline())
    with Session(publication_db) as session, session.begin():
        assert publisher.verify_date(session, lease, generation_id=generation, business_date=DAY, deadline=deadline())
    with pytest.raises(RuntimeError, match="crash"):
        with Session(publication_db) as session, session.begin():
            publisher.publish(session, lease, generation_id=generation, deadline=deadline())
            raise RuntimeError("crash")
    with Session(publication_db) as session, session.begin():
        assert not publisher.confirmed(session, owner_id=1, account_id=lease.account_id,
            generation_id=generation, target_version=lease.target_version)
        publisher.publish(session, lease, generation_id=generation, deadline=deadline())
    with Session(publication_db) as session:
        assert session.get(Account, lease.account_id).published_generation_id == generation
        assert publisher.confirmed(session, owner_id=1, account_id=lease.account_id,
            generation_id=generation, target_version=lease.target_version)
        assert not publisher.confirmed(session, owner_id=2, account_id=lease.account_id,
            generation_id=generation, target_version=lease.target_version)
    context_query = CurrentReadContextQuery(execution.policy)
    position_query = CurrentPositionsQuery(execution.policy)
    def read_positions(token=None, target_day=DAY, cutoff=AT):
        with Session(publication_db) as session, session.begin():
            context = context_query.capture(session, owner_id=1, account_mode="SINGLE", account_id=lease.account_id,
                target_through=cutoff, context_token=token, deadline=deadline())
            page = position_query.page(session, basis=context, account_id=lease.account_id,
                trade_date=target_day, deadline=deadline())
            return context, page
    before, page = read_positions()
    with Session(publication_db) as session:
        status = CalculationStatusQuery(execution.policy).read(session,owner_id=1,
            account_id=lease.account_id,deadline=deadline())
        assert status.stage == "PUBLISHED" and status.publishedGenerationId == str(generation)
        assert status.progress.completedTradeDateCount == status.progress.totalTradeDateCount == 1
    assert len(page.items) == int(held) and page.next_stock is None
    if held:
        assert page.items[0].valuation.result.profit_cents == 98950
        assert page.items[0].fee_version_id == fee
        with pytest.raises(PublishedPositionsUnavailable, match="晚于读取截止"):
            read_positions(cutoff=AT-timedelta(seconds=1))
    # Retrying an already published target is a readback receipt, not new work.
    from src.biz.services.wealth.market.trading_assistant.calculation_retries import CalculationRetryService
    from src.biz.schemas.wealth.market.trading_assistant.calculation_status import CalculationRetryCommand
    from src.biz.models.wealth.trading_assistant.calculation import Recalculation
    retry = CalculationRetryService(None, execution.policy, lambda:AT, executor_id="published-retry")
    with Session(publication_db) as session, session.begin():
        response = retry.accept(session, owner_id=1, account_id=lease.account_id,
            command=CalculationRetryCommand(requestId=str(uuid4()),attemptId=str(uuid4()),
                calculationTargetVersion=str(lease.target_version)), deadline=deadline())
        assert response.receipt["result"]["stage"] == "PUBLISHED"
        assert session.get(Recalculation,lease.account_id) is None
        assert session.get(Account,lease.account_id).published_generation_id == generation
    # Current fees affect a real published holding read, not the historical row.
    updated_fee = uuid4()
    with Session(publication_db) as session, session.begin():
        session.add(FeeVersion(fee_version_id=updated_fee,account_id=lease.account_id,
            commission_rate=Decimal("0.0020"), minimum_commission=Decimal("0.00"),
            stamp_tax_rate=Decimal("0.0020"), created_at=AT))
        session.flush()
        session.get(Account,lease.account_id).current_fee_version_id = updated_fee
    with pytest.raises(WriteProtocolConflict, match="TA_READ_CONTEXT_CHANGED"):
        read_positions(before.context.contextToken)
    after, page = read_positions()
    assert before.context.accounts == after.context.accounts
    assert len(page.items) == int(held)
    if held:
        assert page.items[0].fee_version_id == updated_fee
        assert page.items[0].valuation.result.profit_cents == 95600
    with Session(publication_db) as session:
        assert session.get(AccountSnapshot,(lease.account_id,day)).holding_profit_amount == (Decimal("989.50") if held else 0)
    with pytest.raises(PublishedPositionsUnavailable, match="目标交易日"):
        read_positions(target_day=DAY+timedelta(days=1))
    with Session(publication_db) as session, session.begin():
        session.get(Account,lease.account_id).fact_version += 1
    with pytest.raises(PublishedPositionsUnavailable, match="当前事实"):
        read_positions()
    retire(publication_db, lease)
