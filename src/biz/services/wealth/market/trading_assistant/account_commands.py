"""Account creation and fee commands using the same retained-request protocol."""
import asyncio
from dataclasses import replace
from uuid import UUID

from src.biz.schemas.wealth.market.trading_assistant.recovery import RecoveryRejection
from src.biz.schemas.wealth.market.trading_assistant.errors import FieldErrorDto
from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountCreateScope,AccountFeesScope
from .account_acceptance import AccountAcceptance
from .execution_policy import Deadline
from .market_facts import SecurityNotEligible
from .transaction_boundary import CommitOutcomeUnknown
from .write_protocol import WriteProtocol,WriteProtocolConflict


class AccountCommandService:
    def __init__(self,transactions,market,policy,now,*,executor_id):
        self.transactions,self.market,self.policy,self.now,self.executor_id = transactions,market,policy,now,executor_id
        self.protocol = WriteProtocol(policy)
        self.acceptance = AccountAcceptance(self.protocol)

    async def create(self,*,owner_id,command):
        return await self._save(owner_id=owner_id,command=command,account_id=None)

    async def update_fees(self,*,owner_id,account_id,command):
        return await self._save(owner_id=owner_id,command=command,account_id=account_id)

    async def _save(self,*,owner_id,command,account_id):
        deadline = Deadline.after_ms(self.policy.write_request_budget_ms)
        operation = "ACCOUNT_CREATE" if account_id is None else "FEES_UPDATE"
        scope = AccountCreateScope(scopeType="ACCOUNT_CREATE") if account_id is None else AccountFeesScope(
            scopeType="ACCOUNT_FEES",accountId=str(account_id))
        payload = command.model_dump(mode="json",exclude={"requestId","attemptId","expectedRequestStateVersion"})
        state = await self.transactions.run(lambda session:self.protocol.register(session,
            owner_id=owner_id,request_id=UUID(command.requestId),attempt_id=UUID(command.attemptId),scope=scope,
            operation=operation,payload=payload,now=self.now(),executor_id=self.executor_id,deadline=deadline,
            expected_state_version=int(command.expectedRequestStateVersion) if command.expectedRequestStateVersion is not None else None),
            deadline=deadline,write=True)
        if not state.execute:
            return state
        client_row_id = None
        try:
            securities = {}
            if account_id is None:
                # Each identity lookup is bounded and the original absolute deadline is shared.
                for position in command.initialPositions:
                    client_row_id = position.clientRowId
                    securities[position.tsCode] = await self.transactions.run(
                        lambda session:self.market.resolve_security(session,position.tsCode,deadline),deadline=deadline,write=False)
                client_row_id = None
            def accept(session):
                nonlocal client_row_id
                now = self.now()
                locked = self.protocol.lock_execution(session,state,now=now,executor_id=self.executor_id,deadline=deadline)
                if account_id is None:
                    # Acceptance must not trust an identity resolved before acquiring
                    # the execution fence. Keep the same overall SQL/time budget.
                    for position in command.initialPositions:
                        client_row_id = position.clientRowId
                        securities[position.tsCode] = self.market.resolve_security(session, position.tsCode, deadline)
                    client_row_id = None
                    return self.acceptance.create(session,locked,command,securities=securities,now=now)
                return self.acceptance.update_fees(session,locked,command,account_id=account_id,now=now)
            return await self.transactions.run(accept,deadline=deadline,write=True)
        except (CommitOutcomeUnknown,asyncio.CancelledError):
            raise
        except Exception as error:
            rejection = RecoveryRejection(
                code=error.code if isinstance(error,WriteProtocolConflict) else "TA_REQUEST_INVALID" if isinstance(error,SecurityNotEligible) else "TA_WRITE_FAILED",
                message="股票资料不支持登记，请检查" if isinstance(error,SecurityNotEligible) else "保存未完成，请重新核对",
                field="initialPositions.tsCode" if isinstance(error,SecurityNotEligible) else None)
            def stop(session):
                now = self.now()
                return self.protocol.stop(session,self.protocol.lock_execution(session,state,now=now,
                    executor_id=self.executor_id,deadline=deadline),rejection,now)
            stopped = await self.transactions.run(stop,deadline=deadline,write=True)
            fields = () if rejection.field is None else (FieldErrorDto(field=rejection.field,
                clientRowId=client_row_id, message=rejection.message, affectedOn=None),)
            return replace(stopped, field_errors=fields)
