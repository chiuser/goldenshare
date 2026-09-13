"""Historical price checks use real published inputs and roll back mutations."""
from datetime import timedelta, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, update, delete, event
from sqlalchemy.orm import Session, sessionmaker

from tests.test_wealth_trading_assistant_calculation_work import (
    database, migrated, publication_db, interruptions_db, cutoff_db,
    test_accounts_are_claimed_and_published_with_confirmed_cutoff as publish_accounts,
    DAY, EquityDailyBar, TradeCalendar, Account, CalculationGeneration)
from src.biz.models.wealth.trading_assistant.calculation_inputs import ValuationBasis, CalculationBatch
from src.biz.models.wealth.trading_assistant.accounts import FeeVersion
from src.biz.services.wealth.market.trading_assistant.published_source_check import PublishedSourceCheck
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputMismatch, CalculationDataUnavailable
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import RecalculationExecution
from src.biz.services.wealth.market.trading_assistant.history_source_preparation import HistorySourcePreparation
from src.biz.services.wealth.market.trading_assistant.cutoff_discovery import CutoffDiscovery
from src.biz.services.wealth.market.trading_assistant.calculation_work import CalculationWork
from src.biz.models.wealth.trading_assistant.calculation import Recalculation, DayResult
from src.biz.models.wealth.trading_assistant.publication import PublicationDay
from src.biz.models.wealth.trading_assistant.calculation_inputs import CutoffPreparation


@pytest.fixture(scope="module")
def published(cutoff_db):
    with pytest.MonkeyPatch.context() as patch:
        publish_accounts(cutoff_db, patch, True, True, False)
    with Session(cutoff_db) as session:
        account = session.scalar(select(Account).where(Account.published_generation_id.is_not(None)).limit(1))
        return cutoff_db, account.account_id, account.published_generation_id


def price_origin(session, account_id, generation_id):
    direct = session.get(PublicationDay, (account_id, generation_id, DAY))
    return session.get(DayResult, direct.day_result_id).origin_generation_id


@pytest.mark.parametrize("case", ["unchanged", "price", "calendar", "missing", "corrupt", "foreign", "bad_cursor", "closed", "fees", "corrupt_calendar", "corrupt_terminal"])
def test_one_historical_page_compares_actual_evidence(published, case):
    engine, account_id, generation_id = published
    policy = TradingAssistantExecutionPolicyV1()
    checker = PublishedSourceCheck(RecalculationExecution(policy))
    with Session(engine) as session:
        with session.begin():
            source_id = price_origin(session, account_id, generation_id)
            args = dict(account_id=account_id, generation_id=generation_id, business_date=DAY)
            if case == "price":
                session.execute(update(EquityDailyBar).where(EquityDailyBar.ts_code == "601011.SH",
                    EquityDailyBar.trade_date == DAY).values(close=Decimal("11.0001")))
            elif case == "calendar":
                session.execute(update(TradeCalendar).where(TradeCalendar.exchange == "SSE",
                    TradeCalendar.trade_date == DAY).values(is_open=False))
            elif case == "missing":
                session.execute(delete(EquityDailyBar).where(EquityDailyBar.ts_code == "601011.SH",
                    EquityDailyBar.trade_date == DAY))
            elif case == "corrupt":
                session.execute(update(ValuationBasis).where(ValuationBasis.account_id == account_id,
                    ValuationBasis.generation_id == source_id, ValuationBasis.trade_date == DAY)
                    .values(price=Decimal("999.00")))
            elif case == "foreign":
                args["account_id"] = uuid4()
            elif case == "bad_cursor":
                args["after_page"] = "999999.SZ"
            elif case == "closed":
                args["business_date"] = DAY+timedelta(days=1)
            elif case == "fees":
                fee_id = uuid4()
                session.add(FeeVersion(fee_version_id=fee_id, account_id=account_id, commission_rate=Decimal("0.001"),
                    minimum_commission=Decimal("10.00"), stamp_tax_rate=Decimal("0.001"), created_at=datetime.now(timezone.utc)))
                session.flush()
                session.get(Account, account_id).current_fee_version_id = fee_id
                session.flush()
            elif case == "corrupt_calendar":
                batch = session.scalar(select(CalculationBatch).where(CalculationBatch.account_id == account_id,
                    CalculationBatch.generation_id == generation_id, CalculationBatch.stage == "CALENDAR").limit(1))
                batch.input_digest = b"x"*32
                session.flush()
            elif case == "corrupt_terminal":
                batch = session.get(CalculationBatch, (account_id, source_id, DAY, "VALUATION_END", "", "1"))
                batch.input_digest = b"x"*32
                session.flush()
                args["after_page"] = "601011.SH"
            if case in ("corrupt", "foreign", "bad_cursor", "missing", "corrupt_calendar", "corrupt_terminal"):
                with pytest.raises(CalculationDataUnavailable if case == "missing" else CalculationInputMismatch):
                    checker.page(session, **args, deadline=Deadline.after_ms(2000))
            else:
                page = checker.page(session, **args, deadline=Deadline.after_ms(2000))
                assert page.changed == (case in ("price", "calendar"))
                if case == "price":
                    assert Decimal(page.prices_before[0].price_text) == Decimal("11.00")
                    assert Decimal(page.prices_after[0].price_text) == Decimal("11.0001")
                elif case == "calendar":
                    assert page.calendar_before["is_open"] is True
                    assert page.calendar_after["is_open"] is False
                elif case in ("unchanged", "fees"):
                    assert not page.done and page.next_page == "601011.SH"
                    terminal = checker.page(session, **args, after_page=page.next_page, deadline=Deadline.after_ms(2000))
                    assert terminal.done and not terminal.changed
                else:
                    assert page.done and not page.prices_before
            assert session.get(Account, account_id).published_generation_id == generation_id
            assert session.get(CalculationGeneration, generation_id).stage == "PUBLISHED"
            # Only this isolated test transaction changes source rows; no
            # production data or persisted publication is edited by the check.
            session.rollback()


def test_history_discovery_records_change_once_and_replays_with_original_fees(published):
    engine, account_id, generation_id = published
    policy = TradingAssistantExecutionPolicyV1()
    execution = RecalculationExecution(policy)
    with Session(engine) as session:
        source_id = price_origin(session, account_id, generation_id)
        original = session.scalar(select(ValuationBasis).where(ValuationBasis.account_id == account_id,
            ValuationBasis.generation_id == source_id, ValuationBasis.trade_date == DAY))
        old_fee, old_price = original.fee_version_id, original.price
        old_target = session.get(Account, account_id).calculation_target_version
    # A rolled-back observation must not advance the target or leave a receipt.
    with Session(engine) as session:
        session.execute(update(EquityDailyBar).where(EquityDailyBar.ts_code == "601011.SH",
            EquityDailyBar.trade_date == DAY).values(close=Decimal("13.0101")))
        assert HistorySourcePreparation(execution).step(session, account_id=account_id,
            deadline=Deadline.after_ms(2000)) == "ENQUEUED"
        session.rollback()
    with Session(engine) as session:
        assert session.get(Account, account_id).calculation_target_version == old_target
        assert session.get(Recalculation, account_id) is None
        assert session.get(CutoffPreparation, (account_id, old_target, "HISTORY")) is None
    with Session(engine) as session, session.begin():
        session.execute(update(EquityDailyBar).where(EquityDailyBar.ts_code == "601011.SH",
            EquityDailyBar.trade_date == DAY).values(close=Decimal("13.0101")))
    observed = "2026-09-15T12:00:00+00:00"
    def clock(conn, cursor, statement, parameters, context, executemany):
        return statement.replace("clock_timestamp()", f"TIMESTAMPTZ '{observed}'"), parameters
    event.listen(engine, "before_cursor_execute", clock, retval=True)
    try:
        stages = []
        for _ in range(12):
            # Recreate the scanner every batch, with only database continuation.
            stages.append(CutoffDiscovery(policy, sessionmaker(engine), purpose="HISTORY").run_once())
            if stages[-1] == "IDLE":
                break
        assert stages.count("ENQUEUED") == 2
        with Session(engine) as session:
            account = session.get(Account, account_id)
            assert account.calculation_target_version == old_target+1
            assert account.published_generation_id == generation_id
            pending = session.get(Recalculation, account_id)
            assert pending.affected_from_date == DAY
            proof = session.get(CutoffPreparation, (account_id, old_target, "HISTORY"))
            assert proof.state == "CHANGED"
            assert proof.evidence["generationId"] == str(generation_id)
            assert Decimal(proof.evidence["pricesBefore"][0]["price_text"]) == old_price
            assert Decimal(proof.evidence["pricesAfter"][0]["price_text"]) == Decimal("13.0101")
        for _ in range(250):
            stage = CalculationWork(execution, sessionmaker(engine), rule_version=1,
                resolve_through_date=lambda *args, **kwargs: DAY+timedelta(days=3)).run_once(executor_id="source-replay")
            assert stage not in ("FAILED", "TRANSIENT", "WAITING_DATA")
            if stage == "IDLE":
                break
        else:
            pytest.fail("Historical-source replay did not finish")
        with Session(engine) as session:
            account = session.get(Account, account_id)
            assert account.published_generation_id != generation_id
            new = session.scalar(select(ValuationBasis).where(ValuationBasis.account_id == account_id,
                ValuationBasis.generation_id == account.published_generation_id, ValuationBasis.trade_date == DAY))
            assert (new.price, new.fee_version_id) == (Decimal("13.0101"), old_fee)
            old = session.scalar(select(ValuationBasis).where(ValuationBasis.account_id == account_id,
                ValuationBasis.generation_id == source_id, ValuationBasis.trade_date == DAY))
            assert (old.price, old.fee_version_id) == (old_price, old_fee)
            assert session.get(Recalculation, account_id) is None
        observed = "2026-09-15T13:00:00+00:00"
        rescanned = []
        for _ in range(40):
            stage = CutoffDiscovery(policy, sessionmaker(engine), purpose="HISTORY").run_once()
            rescanned.append(stage)
            if stage == "IDLE":
                break
        assert "ENQUEUED" not in rescanned
        assert rescanned.count("VERIFIED") == 2
        with Session(engine) as session:
            assert session.get(Account, account_id).calculation_target_version == old_target+1
    finally:
        event.remove(engine, "before_cursor_execute", clock)
