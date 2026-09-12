"""Bounded expiry maintenance. Never validates or accepts a saved candidate."""
from datetime import datetime
from typing import Callable

from sqlalchemy import and_, select
from sqlalchemy.exc import DBAPIError

from src.biz.models.wealth.trading_assistant.recovery import WriteAttempt, WriteRequest
from .execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from .market_facts import apply_sql_budget
from .transaction_boundary import TransactionRunner
from .write_protocol import WriteProtocol


class RecoveryMaintenance:
    def __init__(self, transactions: TransactionRunner, protocol: WriteProtocol,
                 policy: TradingAssistantExecutionPolicyV1, now: Callable[[], datetime]):
        self.transactions, self.protocol, self.policy, self.now = transactions, protocol, policy, now

    async def sweep(self, *, deadline: Deadline, cancelled: Callable[[], bool]) -> int:
        """Each revoked attempt commits independently; cancellation retains prior units."""
        if cancelled():
            return 0
        scan_at = self.now()

        def scan(session):
            apply_sql_budget(session, deadline, self.policy)
            return session.execute(select(WriteAttempt.owner_id, WriteAttempt.request_id, WriteRequest.scope_key)
                .join(WriteRequest, and_(WriteRequest.owner_id == WriteAttempt.owner_id,
                    WriteRequest.request_id == WriteAttempt.request_id,
                    WriteRequest.current_attempt_id == WriteAttempt.attempt_id))
                .where(WriteAttempt.status == "PROCESSING", WriteAttempt.lease_until <= scan_at)
                .order_by(WriteAttempt.lease_until, WriteAttempt.owner_id,
                          WriteAttempt.request_id, WriteAttempt.attempt_id)
                .limit(self.policy.page_rows)).all()

        rows = await self.transactions.run(scan, deadline=deadline, write=False)
        stopped = 0
        for owner_id, request_id, key in rows:
            if cancelled():
                break
            deadline.remaining_ms()
            unit = Deadline.after_ms(deadline.bounded_ms(self.policy.batch_budget_ms), deadline.clock)

            def expire(session):
                return self.protocol.expire(session, owner_id=owner_id, request_id=request_id,
                    key=key, now=self.now(), deadline=unit)

            try:
                state = await self.transactions.run(expire, deadline=unit, write=True)
            except DBAPIError as exc:
                # A busy scope remains unresolved; do not let it starve unrelated scopes.
                if getattr(exc.orig, "sqlstate", None) != "55P03":
                    raise
                continue
            if state is not None and state.status == "NOT_SAVED":
                stopped += 1
        return stopped
