"""One bounded account batch's execution fence, design §§4.8 and 4.24.

Caller owns the short transaction. No scheduler, thread, or inferred progress.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select, func, or_

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import Recalculation
from .market_facts import apply_sql_budget


class CalculationExecutionLost(RuntimeError):
    """The caller must discard this batch; it cannot publish or clear newer work."""


@dataclass(frozen=True, slots=True)
class CalculationLease:
    account_id: UUID
    target_version: int
    executor_id: str
    fence: int


class RecalculationExecution:
    def __init__(self, policy):
        self.policy = policy

    def claim(self, session, *, executor_id, deadline):
        if not isinstance(executor_id, str) or not executor_id:
            raise ValueError("Executor identity is required")
        apply_sql_budget(session, deadline, self.policy)
        now = session.scalar(select(func.clock_timestamp()))
        pending = session.scalar(select(Recalculation).join(Account,
            Account.account_id == Recalculation.account_id).where(
                Recalculation.next_attempt_at.is_not(None),
                Recalculation.next_attempt_at <= now,
                Recalculation.target_version == Account.calculation_target_version,
                or_(Recalculation.lease_until.is_(None), Recalculation.lease_until <= now))
            .order_by(Recalculation.next_attempt_at, Recalculation.last_claimed_at.asc().nulls_first(),
                Recalculation.account_id).limit(1)
            .with_for_update(of=(Account, Recalculation), skip_locked=True)
            .execution_options(populate_existing=True))
        if pending is None:
            return None
        pending.executor_id = executor_id
        pending.fence += 1
        pending.lease_until = now + timedelta(seconds=self.policy.lease_seconds)
        pending.last_claimed_at = now
        pending.updated_at = now
        deadline.remaining_ms()
        session.flush()
        return CalculationLease(pending.account_id, pending.target_version, executor_id, pending.fence)

    def _lock(self, session, lease, deadline):
        apply_sql_budget(session, deadline, self.policy)
        account = session.scalar(select(Account).where(Account.account_id == lease.account_id)
            .with_for_update().execution_options(populate_existing=True))
        pending = session.scalar(select(Recalculation).where(Recalculation.account_id == lease.account_id)
            .with_for_update().execution_options(populate_existing=True))
        self._verify(session, lease, account, pending, deadline)
        return account, pending

    @staticmethod
    def _verify(session, lease, account, pending, deadline):
        deadline.remaining_ms()
        now = session.scalar(select(func.clock_timestamp()))
        if (account is None or pending is None or account.calculation_target_version != lease.target_version
                or pending.target_version != lease.target_version or pending.fence != lease.fence
                or pending.executor_id != lease.executor_id or pending.lease_until is None
                or pending.lease_until <= now):
            raise CalculationExecutionLost("Calculation target or execution fence no longer matches")

    @contextmanager
    def batch(self, session, lease, *, deadline):
        """Keep candidate writes and the final fence check in the same transaction."""
        account, pending = self._lock(session, lease, deadline)
        yield account
        session.flush()
        self._verify(session, lease, account, pending, deadline)

    def release(self, session, lease, *, deadline):
        """Yield one execution opportunity without clearing pending work or failures."""
        _, pending = self._lock(session, lease, deadline)
        now = session.scalar(select(func.clock_timestamp()))
        pending.executor_id = None
        pending.lease_until = None
        if pending.next_attempt_at is not None:
            pending.next_attempt_at = max(pending.next_attempt_at, now)
        pending.updated_at = now
        session.flush()
