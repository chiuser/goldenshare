"""Committed progress resumes; failed units roll back before status is saved."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, deadline, retire, DAY
from tests.test_wealth_trading_assistant_publication_storage import publication_db
from tests.test_wealth_trading_assistant_calculation_interruptions import interruptions_db
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.services.wealth.market.trading_assistant.generation_execution import GenerationExecution
from src.biz.services.wealth.market.trading_assistant.generation_steps import GenerationSteps
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationDataUnavailable
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
