"""Unscheduled failures and bounded retry delays on isolated PostgreSQL."""
from dataclasses import replace
from datetime import timedelta

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, deadline, retire
from tests.test_wealth_trading_assistant_publication_storage import publication_db
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, Recalculation
from src.biz.services.wealth.market.trading_assistant.calculation_interruptions import CalculationInterruptions
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import CalculationExecutionLost


@pytest.fixture(scope="module")
def interruptions_db(publication_db):
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20260912_000175").module
    assert revision.down_revision == "20260912_000174"
    with publication_db.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        revision.upgrade()
    return publication_db


@pytest.mark.parametrize("kind,delay", [("FAILED", None), ("WAITING_DATA", 60), ("TRANSIENT", 2)])
def test_interruption_atomicity_schedule_and_fence(interruptions_db, kind, delay):
    inputs, lease, generation, _ = setup(interruptions_db)
    service = CalculationInterruptions(inputs.execution)
    args = dict(generation_id=generation, kind=kind, reason="固定输入核验未通过")
    with pytest.raises(RuntimeError, match="rollback"):
        with Session(interruptions_db) as session, session.begin():
            service.record(session, lease, **args, deadline=deadline())
            raise RuntimeError("rollback")
    with Session(interruptions_db) as session, session.begin():
        assert session.get(CalculationGeneration, generation).stage == "PREPARING"
        assert session.get(Recalculation, lease.account_id).executor_id == lease.executor_id
        service.record(session, lease, **args, deadline=deadline())
    with Session(interruptions_db) as session, session.begin():
        pending = session.get(Recalculation, lease.account_id)
        saved = session.get(CalculationGeneration, generation)
        assert saved.stage == ("WAITING_DATA" if kind == "WAITING_DATA" else "FAILED")
        assert saved.resume_stage == "PREPARING" and saved.completed_trade_date_count == 0
        assert pending.executor_id is None and pending.lease_until is None
        if delay is None:
            assert pending.next_attempt_at is None
        else:
            assert pending.next_attempt_at - pending.updated_at == timedelta(seconds=delay)
        assert inputs.execution.claim(session, executor_id="other", deadline=deadline()) is None
    with pytest.raises(CalculationExecutionLost):
        with Session(interruptions_db) as session, session.begin():
            inputs.execution.release(session, lease, deadline=deadline())
    if kind == "FAILED":
        revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20260912_000175").module
        with pytest.raises(IntegrityError):
            with interruptions_db.begin() as conn, Operations.context(MigrationContext.configure(conn)):
                revision.downgrade()
        with Session(interruptions_db) as session:
            assert session.get(Recalculation, lease.account_id).next_attempt_at is None
    retire(interruptions_db, lease)


def test_transient_backoff_persists_across_new_instances(interruptions_db):
    inputs, lease, generation, _ = setup(interruptions_db)
    last_business_update = None
    for attempt, delay in enumerate((2, 4, 8, 16, 30, 30), 1):
        with Session(interruptions_db) as session, session.begin():
            CalculationInterruptions(inputs.execution).record(session, lease, generation_id=generation,
                kind="TRANSIENT", reason="数据库暂不可用", deadline=deadline())
        with Session(interruptions_db) as session, session.begin():
            pending = session.get(Recalculation, lease.account_id)
            assert pending.transient_failure_count == attempt
            assert pending.next_attempt_at - pending.updated_at == timedelta(seconds=delay)
            assert session.get(CalculationGeneration, generation).resume_stage == "PREPARING"
            saved = session.get(CalculationGeneration, generation)
            if last_business_update is not None:
                assert saved.last_business_updated_at == last_business_update
            last_business_update = saved.last_business_updated_at
            pending.next_attempt_at = session.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
        with Session(interruptions_db) as session, session.begin():
            lease = inputs.execution.claim(session, executor_id=f"retry-{attempt}", deadline=deadline())
    with pytest.raises(CalculationExecutionLost):
        with Session(interruptions_db) as session, session.begin():
            CalculationInterruptions(inputs.execution).record(session, replace(lease, fence=lease.fence + 1),
                generation_id=generation, kind="FAILED", reason="旧执行者", deadline=deadline())
    retire(interruptions_db, lease)


def test_new_fact_rearms_unscheduled_target(interruptions_db):
    import asyncio
    from uuid import uuid4
    from sqlalchemy.ext.asyncio import create_async_engine
    from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
    from src.biz.models.wealth.trading_assistant.accounts import Account
    from src.biz.schemas.wealth.market.trading_assistant.accounts import CashFlowCommand
    from tests.test_wealth_trading_assistant_calculation_inputs import AT, DAY
    inputs, lease, generation, _ = setup(interruptions_db)
    with Session(interruptions_db) as session, session.begin():
        CalculationInterruptions(inputs.execution).record(session, lease, generation_id=generation,
            kind="FAILED", reason="核验未通过", deadline=deadline())
    async def save():
        engine = create_async_engine(interruptions_db.url)
        deps = build_trading_assistant_dependencies(engine, policy=inputs.execution.policy,
            now=lambda: AT, executor_id="new-fact")
        try:
            return await deps.ledger.save(owner_id=1, account_id=lease.account_id,
                operation="CASH_FLOW_CREATE", command=CashFlowCommand(requestId=str(uuid4()),
                    attemptId=str(uuid4()), direction="IN", occurredOn=DAY.isoformat(), amount="100.00"))
        finally:
            await engine.dispose()
    result = asyncio.run(save())
    assert result.status == "SAVED", result.rejection
    with Session(interruptions_db) as session:
        account = session.get(Account, lease.account_id)
        pending = session.get(Recalculation, lease.account_id)
        assert account.calculation_target_version == pending.target_version == 2
        assert pending.next_attempt_at is not None
        assert pending.affected_from_date == DAY
        assert session.get(CalculationGeneration, generation).stage == "FAILED"
    retire(interruptions_db, lease)
