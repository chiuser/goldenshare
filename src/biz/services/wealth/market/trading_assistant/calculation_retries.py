"""Accept a retry of derived calculation, never replay accounting facts.

Receipt and scheduling change share one short transaction. Admission does not
prove a previously failed input is now usable: the driver must revalidate it.
"""
from uuid import UUID

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import Recalculation
from src.biz.queries.wealth.market.trading_assistant.calculation_status import CalculationStatusQuery
from src.biz.schemas.wealth.market.trading_assistant.receipts import CalculationRetryReceipt
from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountLedgerScope
from .account_acceptance import accepted_time
from .execution_policy import Deadline
from .write_protocol import WriteProtocol, WriteProtocolConflict


class CalculationRetryService:
    def __init__(self, transactions, policy, now, *, executor_id):
        self.transactions, self.policy, self.now = transactions, policy, now
        self.executor_id = executor_id
        self.protocol = WriteProtocol(policy)
        self.status = CalculationStatusQuery(policy)

    async def retry(self, *, owner_id, account_id, command):
        deadline = Deadline.after_ms(self.policy.write_request_budget_ms)
        return await self.transactions.run(lambda session: self.accept(session,
            owner_id=owner_id, account_id=account_id, command=command, deadline=deadline),
            deadline=deadline, write=True)

    def accept(self, session, *, owner_id, account_id, command, deadline):
        now = self.now()
        state = self.protocol.register(session, owner_id=owner_id,
            request_id=UUID(command.requestId), attempt_id=UUID(command.attemptId),
            scope=AccountLedgerScope(scopeType="ACCOUNT_LEDGER", accountId=str(account_id)),
            operation="CALCULATION_RETRY", payload={"calculationTargetVersion": command.calculationTargetVersion},
            now=now, executor_id=self.executor_id, deadline=deadline,
            expected_state_version=int(command.expectedRequestStateVersion)
                if command.expectedRequestStateVersion is not None else None)
        if not state.execute:
            return state
        locked = self.protocol.lock_execution(session, state, now=now,
            executor_id=self.executor_id, deadline=deadline)
        # Same account -> pending lock order as the calculation execution fence.
        account = session.scalar(select(Account).where(Account.account_id == account_id,
            Account.owner_id == owner_id).with_for_update().execution_options(populate_existing=True))
        if account is None:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        pending = session.scalar(select(Recalculation).where(Recalculation.account_id == account_id)
            .with_for_update().execution_options(populate_existing=True))
        if pending and pending.target_version != account.calculation_target_version:
            raise ValueError("Pending target differs from accepted account target")
        db_now = session.scalar(select(func.clock_timestamp()))
        if (int(command.calculationTargetVersion) == account.calculation_target_version and pending is not None
                and (pending.lease_until is None or pending.lease_until <= db_now)):
            # Preserve generation, checkpoints, failure evidence and business progress.
            # Do not steal an active lease or revive the target the user used to see.
            pending.next_attempt_at = db_now
            pending.transient_failure_count = 0
            pending.updated_at = db_now
            session.flush()
        result = self.status.read(session, owner_id=owner_id, account_id=account_id, deadline=deadline)
        receipt = CalculationRetryReceipt(requestId=command.requestId, attemptId=command.attemptId,
            operationType="CALCULATION_RETRY", acceptedAt=accepted_time(now), result=result)
        deadline.remaining_ms()
        return self.protocol.saved(session, locked, receipt.model_dump(mode="json"), now)
