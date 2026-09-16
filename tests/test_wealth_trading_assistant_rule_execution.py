"""Real isolated PostgreSQL fencing; not a rule publication/notification test."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_rule_storage import rule_database, seed_rule
from tests.test_wealth_trading_assistant_persistence import database
from src.biz.models.wealth.trading_assistant.rules import Rule, RuleExecution
from src.biz.services.wealth.market.trading_assistant.execution_policy import (
    Deadline, TradingAssistantExecutionPolicyV1,
)
from src.biz.services.wealth.market.trading_assistant.rule_execution import (
    RuleExecutionLost, RuleExecutionStore,
)


def deadline():
    return Deadline.after_ms(2000)


def seed_due(engine):
    with engine.begin() as conn:
        rule, _ = seed_rule(conn)
        now = datetime.now(timezone.utc)
        conn.execute(insert(RuleExecution).values(rule_id=rule, owner_user_id=1,
            next_attempt_at=now - timedelta(days=1), fence=0, observed_state_version=1,
            last_business_updated_at=now, transient_failures=0))
    return rule


def claim(store, engine):
    with Session(engine) as session, session.begin():
        return store.claim(session, executor_id="test-worker", deadline=deadline())


@pytest.fixture
def store():
    return RuleExecutionStore(TradingAssistantExecutionPolicyV1())


def test_claim_is_exclusive_and_release_retains_business_progress(rule_database, store):
    rule_id = seed_due(rule_database)
    lease = claim(store, rule_database)
    assert lease.rule_id == rule_id
    assert claim(store, rule_database) is None
    with Session(rule_database) as session, session.begin():
        with store.batch(session, lease, deadline=deadline()) as (_, pending):
            pending.waiting_reason = "missing-minute"
        store.release(session, lease, deadline=deadline())
    next_lease = claim(store, rule_database)
    assert next_lease.fence == lease.fence + 1
    with pytest.raises(RuleExecutionLost), Session(rule_database) as session, session.begin():
        with store.batch(session, lease, deadline=deadline()):
            pytest.fail("Old lease must not enter the batch")
    with Session(rule_database) as session, session.begin():
        with store.batch(session, next_lease, deadline=deadline()) as (_, pending):
            assert pending.waiting_reason == "missing-minute"
            pending.next_attempt_at = None
        store.release(session, next_lease, deadline=deadline())


@pytest.mark.parametrize("change", ["CLOSE", "REVISE", "EXPIRE", "OWNER"])
def test_changed_state_or_identity_cannot_commit_a_late_batch(rule_database, store, change):
    rule_id = seed_due(rule_database)
    lease = claim(store, rule_database)
    with rule_database.begin() as conn:
        if change == "CLOSE":
            conn.execute(update(Rule).where(Rule.rule_id == rule_id).values(
                state="CLOSED", state_version=2, closed_at=datetime.now(timezone.utc)))
        elif change == "REVISE":
            conn.execute(update(Rule).where(Rule.rule_id == rule_id).values(state_version=2))
        elif change == "EXPIRE":
            conn.execute(update(RuleExecution).where(RuleExecution.rule_id == rule_id).values(
                lease_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
        else:
            lease = replace(lease, owner_id=2)
    with pytest.raises(RuleExecutionLost), Session(rule_database) as session, session.begin():
        with store.batch(session, lease, deadline=deadline()):
            pytest.fail("Invalid lease must not enter the batch")
    with rule_database.begin() as conn:
        conn.execute(update(RuleExecution).where(RuleExecution.rule_id == rule_id).values(next_attempt_at=None))


def test_expiry_during_batch_rolls_back_candidate_writes(rule_database, store):
    rule_id = seed_due(rule_database)
    lease = claim(store, rule_database)
    with pytest.raises(RuleExecutionLost), Session(rule_database) as session, session.begin():
        with store.batch(session, lease, deadline=deadline()) as (_, pending):
            pending.waiting_reason = "must-roll-back"
            pending.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    with rule_database.begin() as conn:
        assert conn.scalar(select(RuleExecution.waiting_reason).where(RuleExecution.rule_id == rule_id)) is None
        conn.execute(update(RuleExecution).where(RuleExecution.rule_id == rule_id).values(next_attempt_at=None))
