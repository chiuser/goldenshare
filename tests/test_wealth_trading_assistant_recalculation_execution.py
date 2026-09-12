"""M3 execution fencing on isolated PostgreSQL; no publication claim."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import Recalculation
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import CalculationExecutionLost, RecalculationExecution


def deadline(): return Deadline.after_ms(2000)


def seed_pending(database):
    with database.begin() as conn:
        account, _, _ = seed_account(conn)
        conn.execute(insert(Recalculation).values(account_id=account, target_version=1,
            affected_from_date="2026-09-11", next_attempt_at=datetime.now(timezone.utc)-timedelta(days=1),
            fence=0, transient_failure_count=0, updated_at=datetime.now(timezone.utc)))
    return account


def test_claim_skip_lock_release_takeover_and_stale_fence(database):
    account = seed_pending(database)
    execution = RecalculationExecution(TradingAssistantExecutionPolicyV1())
    with Session(database) as first, first.begin():
        lease = execution.claim(first, executor_id="first", deadline=deadline())
        assert lease.account_id == account
        with Session(database) as second, second.begin():
            assert execution.claim(second, executor_id="second", deadline=deadline()) is None
    with Session(database) as session, session.begin():
        assert execution.claim(session, executor_id="second", deadline=deadline()) is None
        execution.release(session, lease, deadline=deadline())
    with Session(database) as session, session.begin():
        second = execution.claim(session, executor_id="second", deadline=deadline())
        assert second.fence == lease.fence+1
    with pytest.raises(CalculationExecutionLost):
        with Session(database) as session, session.begin():
            with execution.batch(session, lease, deadline=deadline()): pass
    with database.begin() as conn:
        conn.execute(update(Recalculation).where(Recalculation.account_id==account)
            .values(lease_until=datetime.now(timezone.utc)-timedelta(seconds=1)))
    with Session(database) as session, session.begin():
        third = execution.claim(session, executor_id="third", deadline=deadline())
        assert third.fence == second.fence+1
    with pytest.raises(CalculationExecutionLost):
        with Session(database) as session, session.begin():
            execution.release(session, second, deadline=deadline())
    # Keep this fixture's completed scenario out of later due-work scans.
    with database.begin() as conn:
        conn.execute(update(Recalculation).where(Recalculation.account_id==account)
            .values(next_attempt_at=datetime.now(timezone.utc)+timedelta(days=2)))


def test_batch_rolls_back_on_expiry_and_new_target(database):
    account = seed_pending(database)
    execution = RecalculationExecution(TradingAssistantExecutionPolicyV1())
    with Session(database) as session, session.begin():
        lease = execution.claim(session, executor_id="first", deadline=deadline())
    with pytest.raises(CalculationExecutionLost):
        with Session(database) as session, session.begin():
            with execution.batch(session, lease, deadline=deadline()) as owned:
                owned.name = "must roll back"
                pending = session.get(Recalculation, account)
                pending.lease_until = datetime.now(timezone.utc)-timedelta(seconds=1)
    with database.begin() as conn:
        assert conn.scalar(select(Account.name).where(Account.account_id==account)) == "测试"
        conn.execute(update(Account).where(Account.account_id==account).values(calculation_target_version=2))
        conn.execute(update(Recalculation).where(Recalculation.account_id==account).values(target_version=2))
    with pytest.raises(CalculationExecutionLost):
        with Session(database) as session, session.begin():
            with execution.batch(session, lease, deadline=deadline()): pass
    with database.connect() as conn:
        assert conn.scalar(select(Recalculation.target_version).where(Recalculation.account_id==account)) == 2
