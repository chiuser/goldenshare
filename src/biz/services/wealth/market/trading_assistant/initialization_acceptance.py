"""Atomically replace the opening version after all affected history is checked."""
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert

from src.biz.models.wealth.trading_assistant.accounts import Account, Initialization, InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import Recalculation
from src.biz.schemas.wealth.market.trading_assistant.receipts import InitializationCorrectReceipt
from .account_acceptance import assert_retained_input, accepted_time
from .calculation.precision import parse_money_cents
from .ledger_acceptance import ValidationBasisChanged
from .persistence_values import money_numeric
from .validation_completion import read_completion
from .write_protocol import WriteProtocolConflict


class InitializationAcceptance:
    def __init__(self, protocol, checkpoints):
        self.protocol, self.checkpoints = protocol, checkpoints

    def accept(self, session, locked, command, job, proof, *, now, deadline):
        _, request, attempt = locked
        if (request.operation_type != "INITIALIZATION_CORRECT" or request.owner_id != job.owner_id
                or request.candidate_id != job.candidate_id or request.target is not None
                or request.scope_key != f"ACCOUNT_LEDGER:{job.change.account_id}"
                or str(request.request_id) != command.requestId or str(attempt.attempt_id) != command.attemptId):
            raise ValueError("Initialization command and locked validation differ")
        assert_retained_input(request, command)
        account = session.scalar(select(Account).where(Account.account_id == job.change.account_id,
            Account.owner_id == job.owner_id).with_for_update().execution_options(populate_existing=True))
        if account is None:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        if account.fact_version != job.fact_version:
            raise ValidationBasisChanged()
        initial = session.get(Initialization, account.current_initialization_id)
        if str(initial.revision) != command.expectedRevision:
            raise WriteProtocolConflict("TA_STATE_CONFLICT")
        verified = read_completion(session, owner_id=job.owner_id, account_id=account.account_id,
            candidate_id=job.candidate_id, run_id=job.run_id, basis_digest=job.basis_digest,
            affected_stocks=job.change.affected_stocks, checkpoints=self.checkpoints,
            policy=self.protocol.policy, deadline=deadline)
        if proof != verified:
            raise ValueError("Initialization completion proof differs")
        new_id, version = uuid4(), account.fact_version + 1
        session.add(Initialization(initialization_id=new_id, account_id=account.account_id,
            revision=initial.revision + 1, accepted_fact_version=version, source_initialization_id=initial.initialization_id,
            initial_cash=money_numeric(parse_money_cents(command.initialCash)), created_at=now))
        session.flush()
        for row in command.initialPositions:
            deadline.remaining_ms()
            session.add(InitialPosition(initialization_id=new_id, account_id=account.account_id,
                client_row_id=row.clientRowId, ts_code=row.tsCode, quantity=row.quantity,
                available_quantity=row.availableQuantity, cost_price=money_numeric(parse_money_cents(row.costPrice))))
        account.current_initialization_id = new_id
        account.fact_version = version
        account.calculation_target_version += 1
        pending = insert(Recalculation).values(account_id=account.account_id,
            target_version=account.calculation_target_version, affected_from_date=account.initialized_on,
            next_attempt_at=now, fence=0, transient_failure_count=0, updated_at=now)
        session.execute(pending.on_conflict_do_update(index_elements=[Recalculation.account_id], set_={
            "target_version":pending.excluded.target_version,
            "affected_from_date":func.least(Recalculation.affected_from_date, pending.excluded.affected_from_date),
            "next_attempt_at":now, "updated_at":now}))
        receipt = InitializationCorrectReceipt(requestId=command.requestId, attemptId=command.attemptId,
            operationType="INITIALIZATION_CORRECT", acceptedAt=accepted_time(now), result=dict(
                accountId=str(account.account_id), initializationId=str(new_id), initializationRevision=str(initial.revision + 1),
                factVersion=str(version), affectedFromDate=account.initialized_on.isoformat()))
        return self.protocol.saved(session, locked, receipt.model_dump(mode="json"), now)
