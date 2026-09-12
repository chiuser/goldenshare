"""Request-driven ledger writes. Recovery reads never call this coordinator."""
import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate
from src.biz.schemas.wealth.market.trading_assistant.recovery import RecoveryRejection
from src.biz.schemas.wealth.market.trading_assistant.errors import FieldErrorDto
from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountLedgerScope
from .execution_policy import Deadline
from .ledger_acceptance import LedgerAcceptance, ValidationBasisChanged
from .ledger_candidate import prepare_candidate
from .initialization_candidate import prepare_initialization
from .initialization_acceptance import InitializationAcceptance
from .ledger_validation import LedgerValidator
from .market_facts import MarketFactsUnavailable, SecurityNotEligible
from .transaction_boundary import CommitOutcomeUnknown
from .validation import InvalidLedger
from .validation_checkpoints import ValidationCheckpoints
from .validation_pages import ValidationPageReader
from .validation_basis import verify_source_basis
from .write_protocol import WriteProtocol, WriteProtocolConflict


class LedgerCommandService:
    def __init__(self, transactions, market, policy, now, *, executor_id: str):
        self.transactions, self.market, self.policy, self.now, self.executor_id = transactions, market, policy, now, executor_id
        self.protocol = WriteProtocol(policy)
        self.checkpoints = ValidationCheckpoints(self.protocol)
        self.validator = LedgerValidator(transactions,ValidationPageReader(policy,market),self.checkpoints,policy,now)
        self.acceptance = LedgerAcceptance(self.protocol,self.checkpoints)
        self.initialization_acceptance = InitializationAcceptance(self.protocol,self.checkpoints)

    async def save(self, *, owner_id: int, account_id: UUID, operation: str, command,
                   target=None, cancelled=lambda:False):
        deadline = Deadline.after_ms(self.policy.write_request_budget_ms)
        payload = command.model_dump(mode="json",exclude={"requestId","attemptId","expectedRequestStateVersion"})
        state = await self.transactions.run(lambda session:self.protocol.register(session,
            owner_id=owner_id,request_id=UUID(command.requestId),attempt_id=UUID(command.attemptId),
            scope=AccountLedgerScope(scopeType="ACCOUNT_LEDGER",accountId=str(account_id)),operation=operation,
            payload=payload,target=target,now=self.now(),executor_id=self.executor_id,deadline=deadline,
            expected_state_version=int(command.expectedRequestStateVersion) if command.expectedRequestStateVersion is not None else None),
            deadline=deadline,write=True)
        if not state.execute:
            return state
        ledger_id = UUID(target.recordId) if target else uuid4()
        try:
            for rebase in range(self.policy.max_validation_rebases+1):
                if cancelled():
                    raise asyncio.CancelledError()
                def prepare(session):
                    if operation == "INITIALIZATION_CORRECT":
                        return prepare_initialization(session, state=state, command=command,
                            market=self.market, policy=self.policy, deadline=deadline)
                    return prepare_candidate(session, state=state, command=command, ledger_id=ledger_id,
                        market=self.market, policy=self.policy, deadline=deadline)
                job,basis = await self.transactions.run(prepare,deadline=deadline,write=False)
                if rebase:
                    job = replace(job, run_id=uuid4())
                else:
                    try:
                        await self.transactions.run(lambda s:verify_source_basis(s, job,
                            market=self.market, deadline=deadline, basis=basis), deadline=deadline, write=False)
                    except ValidationBasisChanged:
                        # An expired attempt's pages cannot survive changed calendar facts.
                        job = replace(job, run_id=uuid4())

                def retain_basis(session):
                    _,request,attempt = self.protocol.lock_execution(session,state,now=self.now(),
                        executor_id=self.executor_id,deadline=deadline)
                    candidate = session.get(ValidationCandidate,request.candidate_id)
                    candidate.basis = basis
                    attempt.basis = {**basis,"validationRunId":str(job.run_id)}

                await self.transactions.run(retain_basis,deadline=deadline,write=True)
                proof = await self.validator.validate(job,deadline=deadline,cancelled=cancelled,
                    execution=state,executor_id=self.executor_id)

                def accept(session):
                    now = self.now()
                    locked = self.protocol.lock_execution(session,state,now=now,
                        executor_id=self.executor_id,deadline=deadline)
                    verify_source_basis(session, job, market=self.market, deadline=deadline)
                    acceptance = self.initialization_acceptance if operation == "INITIALIZATION_CORRECT" else self.acceptance
                    return acceptance.accept(session,locked,command,job,proof,now=now,deadline=deadline)

                try:
                    return await self.transactions.run(accept,deadline=deadline,write=True)
                except ValidationBasisChanged:
                    if rebase == self.policy.max_validation_rebases:
                        raise WriteProtocolConflict("TA_STATE_CONFLICT")
        except (CommitOutcomeUnknown, asyncio.CancelledError):
            # Never stop an attempt when its commit may have succeeded.
            raise
        except Exception as error:
            affected_on = None
            client_row_id = None
            if isinstance(error,InvalidLedger):
                message = error.message
                field = error.field
                affected_on = error.occurred_on.isoformat()
                if operation.startswith("TRADE_") and field == "amount":
                    field = "quantity"
                if operation == "INITIALIZATION_CORRECT":
                    if field == "amount":
                        field = "initialCash"
                    elif field == "quantity":
                        row = next((p for p in command.initialPositions if p.tsCode == error.ts_code), None)
                        if row is not None:
                            client_row_id = row.clientRowId
                            initialized_on = job.stocks[0].state.initialized_on if job.stocks else None
                            field = "initialPositions.availableQuantity" if error.occurred_on == initialized_on else "initialPositions.quantity"
                        else:
                            field = "initialPositions"
                rejection = RecoveryRejection(code="TA_REQUEST_INVALID",message=message,field=field)
            elif isinstance(error,SecurityNotEligible):
                field = "tsCode"
                if operation == "INITIALIZATION_CORRECT":
                    row = next((p for p in command.initialPositions if p.tsCode == error.ts_code), None)
                    client_row_id = row.clientRowId if row is not None else None
                    field = "initialPositions.tsCode" if row is not None else "initialPositions"
                rejection = RecoveryRejection(code="TA_REQUEST_INVALID",message="请选择有效的 A 股股票",field=field)
            elif isinstance(error,WriteProtocolConflict):
                rejection = RecoveryRejection(code=error.code,message="记录或校验依据已变化，请重新核对",field=None)
            elif isinstance(error,MarketFactsUnavailable):
                rejection = RecoveryRejection(code="TA_WRITE_FAILED",message="交易日历或证券资料暂不可用，请稍后核对",field=None)
            else:
                rejection = RecoveryRejection(code="TA_WRITE_FAILED",message="本次保存未完成，请重新核对",field=None)

            def stop(session):
                now = self.now()
                locked = self.protocol.lock_execution(session,state,now=now,executor_id=self.executor_id,deadline=deadline)
                return self.protocol.stop(session,locked,rejection,now)

            # Uses the original remaining budget. If stopping cannot be proved, propagate
            # the uncertainty; expiry maintenance will not auto-accept the candidate.
            stopped = await self.transactions.run(stop,deadline=deadline,write=True)
            fields = () if rejection.field is None else (FieldErrorDto(field=rejection.field,
                clientRowId=client_row_id, message=rejection.message, affectedOn=affected_on),)
            return replace(stopped, field_errors=fields)
