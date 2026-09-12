"""Committed progress resumes; failed units roll back before status is saved."""
from datetime import timedelta
from contextlib import contextmanager

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, deadline, retire, DAY, AT
from tests.test_wealth_trading_assistant_publication_storage import publication_db
from tests.test_wealth_trading_assistant_calculation_interruptions import interruptions_db
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.services.wealth.market.trading_assistant.generation_execution import GenerationExecution
from src.biz.services.wealth.market.trading_assistant.generation_steps import GenerationSteps
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationDataUnavailable
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import CalculationExecutionLost
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.publication import PublicationReceipt
from src.foundation.models.core.trade_calendar import TradeCalendar


@pytest.mark.parametrize("kind", ["TRANSIENT", "EXHAUSTED", "FAILED", "WAITING_DATA"])
def test_failed_unit_rolls_back_then_revalidates_on_reclaim(interruptions_db, monkeypatch, kind):
    inputs, lease, generation, _ = setup(interruptions_db)
    with Session(interruptions_db) as session, session.begin():
        if kind == "EXHAUSTED":
            session.get(Recalculation, lease.account_id).transient_failure_count = 5
        if session.get(TradeCalendar, ("SSE", DAY)) is None:
            session.add(TradeCalendar(exchange="SSE", trade_date=DAY, is_open=True,
                pretrade_date=DAY - timedelta(days=1)))
    original = GenerationSteps.advance
    class Locked(Exception):
        sqlstate = "55P03"
    def interrupted(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if kind in ("TRANSIENT", "EXHAUSTED"):
            raise OperationalError("test", {}, Locked())
        if kind == "WAITING_DATA":
            raise CalculationDataUnavailable("missing valuation")
        raise ValueError("invalid internal state")
    monkeypatch.setattr(GenerationSteps, "advance", interrupted)
    runner = GenerationExecution(inputs.execution, sessionmaker(interruptions_db))
    assert runner.run(lease, generation_id=generation) == ("FAILED" if kind == "EXHAUSTED" else kind)
    with Session(interruptions_db) as session, session.begin():
        saved = session.get(CalculationGeneration, generation)
        assert saved.stage == ("WAITING_DATA" if kind == "WAITING_DATA" else "FAILED")
        assert saved.resume_stage == "PREPARING"
        assert saved.total_trade_date_count is None  # Calendar write rolled back.
        assert session.scalar(select(func.count()).select_from(CalculationBatch).where(
            CalculationBatch.generation_id == generation)) == 0
        assert inputs.execution.claim(session, executor_id="early", deadline=deadline()) is None
        pending = session.get(Recalculation, lease.account_id)
        assert (pending.next_attempt_at is None) == (kind in ("FAILED", "EXHAUSTED"))
        if kind == "EXHAUSTED":
            assert pending.transient_failure_count == 6
            assert "自动重试已达上限" in saved.reason
        # Simulate the due time or already-tested explicit retry admission.
        pending.next_attempt_at = session.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
    monkeypatch.setattr(GenerationSteps, "advance", original)
    with Session(interruptions_db) as session, session.begin():
        resumed = inputs.execution.claim(session, executor_id="resumed", deadline=deadline())
    assert GenerationExecution(inputs.execution, sessionmaker(interruptions_db)).run(
        resumed, generation_id=generation) == "CALENDAR"
    with Session(interruptions_db) as session:
        saved = session.get(CalculationGeneration, generation)
        assert saved.stage == "PREPARING" and saved.reason is None and saved.resume_stage is None
        assert saved.total_trade_date_count == 1
        pending = session.get(Recalculation, lease.account_id)
        assert pending.executor_id is None and pending.transient_failure_count == 0
    retire(interruptions_db, resumed)


@pytest.mark.parametrize("published", [False, True])
def test_committed_unit_with_lost_reply_is_not_repeated(interruptions_db, published):
    inputs, lease, generation, _ = setup(interruptions_db)
    with Session(interruptions_db) as session, session.begin():
        if session.get(TradeCalendar, ("SSE", DAY)) is None:
            session.add(TradeCalendar(exchange="SSE", trade_date=DAY, is_open=True,
                pretrade_date=DAY - timedelta(days=1)))
    if published:
        with Session(interruptions_db) as session, session.begin():
            steps = GenerationSteps(inputs.execution)
            assert steps.advance(session, lease, generation_id=generation, deadline=deadline()) == "CALENDAR"
            steps.prepare_date(session, lease, generation_id=generation,
                business_date=DAY, valuation_at=AT, deadline=deadline())
        for _ in range(40):
            with Session(interruptions_db) as session, session.begin():
                stage = GenerationSteps(inputs.execution).advance(session, lease,
                    generation_id=generation, deadline=deadline())
            if stage == "MANIFEST_CHECK":
                break
        else:
            pytest.fail("Publication was not prepared")
    injected = []
    class LostReplySession(Session):
        @contextmanager
        def begin(self, nested=False):
            with super().begin(nested=nested):
                yield
            # The actual database commit has completed; only its reply is lost.
            if not injected:
                injected.append(True)
                raise OperationalError("lost commit reply", {}, ConnectionError())
    runner = GenerationExecution(inputs.execution, sessionmaker(interruptions_db, class_=LostReplySession))
    if published:
        assert runner.run(lease, generation_id=generation) == "PUBLISHED"
    else:
        # Successful ordinary units already released their lease. The old
        # runner cannot overwrite that committed progress with failure state.
        with pytest.raises(CalculationExecutionLost):
            runner.run(lease, generation_id=generation)
    assert injected == [True]
    with Session(interruptions_db) as session, session.begin():
        saved = session.get(CalculationGeneration, generation)
        assert saved.stage == ("PUBLISHED" if published else "PREPARING")
        assert saved.reason is None and saved.total_trade_date_count == 1
        assert session.scalar(select(func.count()).select_from(PublicationReceipt).where(
            PublicationReceipt.generation_id == generation)) == int(published)
        if published:
            assert session.get(Account, lease.account_id).published_generation_id == generation
            assert session.get(Recalculation, lease.account_id) is None
        else:
            resumed = inputs.execution.claim(session, executor_id="after-lost-reply", deadline=deadline())
            assert resumed is not None and resumed.fence > lease.fence
            GenerationSteps(inputs.execution).prepare_date(session, resumed, generation_id=generation,
                business_date=DAY, valuation_at=AT, deadline=deadline())
    if not published:
        assert GenerationExecution(inputs.execution, sessionmaker(interruptions_db)).run(
            resumed, generation_id=generation) == "DAY_START"
    retire(interruptions_db, lease)


def test_superseded_runner_does_not_pause_new_target(interruptions_db):
    inputs, lease, generation, _ = setup(interruptions_db)
    with Session(interruptions_db) as session, session.begin():
        account = session.get(Account, lease.account_id)
        pending = session.get(Recalculation, lease.account_id)
        account.calculation_target_version = pending.target_version = 2
        pending.next_attempt_at = session.scalar(select(func.clock_timestamp()))
        expected_time = pending.next_attempt_at
    with pytest.raises(CalculationExecutionLost):
        GenerationExecution(inputs.execution, sessionmaker(interruptions_db)).run(lease, generation_id=generation)
    with Session(interruptions_db) as session:
        pending = session.get(Recalculation, lease.account_id)
        assert pending.target_version == 2 and pending.next_attempt_at == expected_time
        assert pending.transient_failure_count == 0
        assert session.get(CalculationGeneration, generation).stage == "PREPARING"
        assert session.scalar(select(func.count()).select_from(CalculationBatch).where(
            CalculationBatch.generation_id == generation)) == 0
    retire(interruptions_db, lease)
