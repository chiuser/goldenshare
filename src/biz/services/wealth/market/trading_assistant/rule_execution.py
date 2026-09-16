"""Bounded rule leases; caller owns each short transaction (design §4.26).

No check, result, notification or account fact is generated here. The caller must
save intermediate evidence only inside batch(), and terminal commands must invalidate the
lease while holding the same rule lock. Nothing is inferred from a local task.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, or_, select

from src.biz.models.wealth.trading_assistant.rules import Rule, RuleExecution
from .market_facts import apply_sql_budget


class RuleExecutionLost(RuntimeError):
    """Caller must roll back the entire batch, including candidate writes."""


@dataclass(frozen=True, slots=True)
class RuleLease:
    owner_id: int
    rule_id: UUID
    state_version: int
    executor_id: str
    fence: int


class RuleExecutionStore:
    def __init__(self, policy):
        self.policy = policy

    def claim(self, session, *, executor_id, deadline):
        if not isinstance(executor_id, str) or not executor_id:
            raise ValueError("Executor identity is required")
        apply_sql_budget(session, deadline, self.policy)
        now = session.scalar(select(func.clock_timestamp()))
        row = session.execute(select(Rule, RuleExecution).join(RuleExecution,
            Rule.rule_id == RuleExecution.rule_id).where(
                Rule.state == "ACTIVE", RuleExecution.next_attempt_at <= now,
                or_(RuleExecution.lease_until.is_(None), RuleExecution.lease_until <= now))
            .order_by(RuleExecution.next_attempt_at, Rule.rule_id).limit(1)
            .with_for_update(of=(Rule, RuleExecution), skip_locked=True)
            .execution_options(populate_existing=True)).first()
        if row is None:
            return None
        rule, execution = row
        execution.executor_id = executor_id
        execution.fence += 1
        execution.lease_until = now + timedelta(seconds=self.policy.lease_seconds)
        execution.observed_state_version = rule.state_version
        session.flush()
        deadline.remaining_ms()
        return RuleLease(rule.owner_user_id, rule.rule_id, rule.state_version,
                         executor_id, execution.fence)

    def _lock(self, session, lease, deadline):
        apply_sql_budget(session, deadline, self.policy)
        rule = session.scalar(select(Rule).where(Rule.rule_id == lease.rule_id,
            Rule.owner_user_id == lease.owner_id).with_for_update()
            .execution_options(populate_existing=True))
        execution = session.scalar(select(RuleExecution).where(
            RuleExecution.rule_id == lease.rule_id, RuleExecution.owner_user_id == lease.owner_id)
            .with_for_update().execution_options(populate_existing=True))
        self._verify(session, lease, rule, execution, deadline)
        return rule, execution

    @staticmethod
    def _verify(session, lease, rule, execution, deadline):
        deadline.remaining_ms()
        now = session.scalar(select(func.clock_timestamp()))
        if (rule is None or execution is None or rule.state != "ACTIVE"
                or rule.state_version != lease.state_version
                or execution.observed_state_version != lease.state_version
                or execution.fence != lease.fence or execution.executor_id != lease.executor_id
                or execution.lease_until is None or execution.lease_until <= now):
            raise RuleExecutionLost("Rule state or execution fence changed")

    @contextmanager
    def batch(self, session, lease, *, deadline):
        rule, execution = self._lock(session, lease, deadline)
        yield rule, execution
        session.flush()
        self._verify(session, lease, rule, execution, deadline)

    def release(self, session, lease, *, deadline):
        _, execution = self._lock(session, lease, deadline)
        now = session.scalar(select(func.clock_timestamp()))
        execution.executor_id = None
        execution.lease_until = None
        if execution.next_attempt_at is not None:
            execution.next_attempt_at = max(execution.next_attempt_at, now)
        session.flush()
        deadline.remaining_ms()
