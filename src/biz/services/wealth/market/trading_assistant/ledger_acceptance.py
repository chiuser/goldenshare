"""Final short transaction: ledger revision, versions, pending work and receipt."""
from datetime import datetime
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.ledger import Ledger, LedgerRevision
from src.biz.models.wealth.trading_assistant.calculation import Recalculation
from src.biz.schemas.wealth.market.trading_assistant.receipts import SuccessReceipt
from .account_acceptance import accepted_time, assert_retained_input, scaled_decimal
from .calculation.precision import format_cents
from .execution_policy import Deadline
from .ledger_validation import LedgerValidationInput
from .persistence_values import money_numeric
from .validation_completion import CompletedValidation, read_completion
from .validation_checkpoints import ValidationCheckpoints
from .write_protocol import WriteProtocol, WriteProtocolConflict
from .validation_basis import ValidationBasisChanged


class LedgerAcceptance:
    def __init__(self, protocol: WriteProtocol, checkpoints: ValidationCheckpoints):
        self.protocol, self.checkpoints = protocol, checkpoints

    def accept(self, session: Session, locked: tuple, command, job: LedgerValidationInput,
               proof: CompletedValidation, *, now: datetime, deadline: Deadline):
        _, request, attempt = locked
        change = job.change
        operation = change.kind + ("_VOID" if change.status == "VOID" else
                                  "_CORRECT" if change.source_revision is not None else "_CREATE")
        if (request.operation_type != operation or request.owner_id != job.owner_id
                or request.candidate_id != job.candidate_id
                or request.scope_key != f"ACCOUNT_LEDGER:{change.account_id}"
                or str(request.request_id) != command.requestId or str(attempt.attempt_id) != command.attemptId):
            raise ValueError("Command, validation and locked request must be identical")
        assert_retained_input(request, command)
        if change.source_revision is not None and (request.target is None
                or request.target["recordId"] != str(change.ledger_id)
                or request.target["kind"] != change.kind):
            raise ValueError("Validated change targets another record")
        account = session.scalar(select(Account).where(Account.account_id == change.account_id,
            Account.owner_id == job.owner_id).with_for_update().execution_options(populate_existing=True))
        if account is None:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        if account.fact_version != job.fact_version:
            raise ValidationBasisChanged()
        if change.source_revision is None and change.kind == "TRADE" and account.current_fee_version_id != change.fee_version_id:
            raise ValidationBasisChanged()
        if change.source_revision is not None:
            original = session.scalar(select(LedgerRevision).where(LedgerRevision.ledger_id == change.ledger_id,
                LedgerRevision.account_id == change.account_id).order_by(LedgerRevision.revision.desc()).limit(1))
            if original is None or original.status != "ACTIVE" or original.revision != change.source_revision:
                raise WriteProtocolConflict("TA_STATE_CONFLICT")
            if str(original.revision) != command.expectedRevision:
                raise WriteProtocolConflict("TA_STATE_CONFLICT")
            if original.fee_version_id != change.fee_version_id:
                raise ValueError("Original fee snapshot changed")
        verified = read_completion(session, owner_id=job.owner_id, account_id=change.account_id,
            candidate_id=job.candidate_id, run_id=job.run_id, basis_digest=job.basis_digest,
            affected_stocks=change.affected_stocks, checkpoints=self.checkpoints, policy=self.protocol.policy,
            deadline=deadline)
        if proof != verified:
            raise ValueError("Completion proof does not match persisted checkpoints")
        if change.source_revision is None:
            session.add(Ledger(ledger_id=change.ledger_id,account_id=change.account_id,kind=change.kind,created_at=now))
            session.flush()
        version, revision = account.fact_version + 1, (change.source_revision or 0) + 1
        fees, amounts = change.fees, change.amounts
        session.add(LedgerRevision(ledger_id=change.ledger_id,revision=revision,account_id=change.account_id,
            kind=change.kind,accepted_fact_version=version,occurred_on=change.occurred_on,status=change.status,
            accepted_at=now,source_revision=change.source_revision,note=change.note,direction=change.direction,
            net_cash_change=money_numeric(change.net_cash_cents),ts_code=change.ts_code,quantity=change.quantity,
            price=money_numeric(change.price_cents) if fees else None,
            gross_amount=money_numeric(amounts.gross_cents) if amounts else None,fee_version_id=change.fee_version_id,
            commission_rate=scaled_decimal(fees.commission_rate_millionths,6) if fees else None,
            minimum_commission=money_numeric(fees.minimum_commission_cents) if fees else None,
            stamp_tax_rate=scaled_decimal(fees.stamp_tax_rate_ten_thousandths,4) if fees else None,
            commission_amount=money_numeric(amounts.commission_cents) if amounts else None,
            stamp_tax_amount=money_numeric(amounts.stamp_tax_cents) if amounts else None,
            cash_amount=money_numeric(change.cash_cents) if change.cash_cents is not None else None))
        account.fact_version = version
        account.calculation_target_version += 1
        pending = insert(Recalculation).values(account_id=account.account_id,
            target_version=account.calculation_target_version,affected_from_date=change.affected_from,
            next_attempt_at=now,fence=0,transient_failure_count=0,updated_at=now)
        session.execute(pending.on_conflict_do_update(index_elements=[Recalculation.account_id],set_={
            "target_version":pending.excluded.target_version,
            "affected_from_date":func.least(Recalculation.affected_from_date,pending.excluded.affected_from_date),
            "next_attempt_at":now,"updated_at":now}))
        result = dict(accountId=str(account.account_id),revision=str(revision),factVersion=str(version),
            affectedFromDate=change.affected_from.isoformat(),netCashChange=format_cents(change.net_cash_cents))
        if amounts:
            result.update(tradeId=str(change.ledger_id),feeVersionId=str(change.fee_version_id),
                grossAmount=format_cents(amounts.gross_cents),commissionAmount=format_cents(amounts.commission_cents),
                stampTaxAmount=format_cents(amounts.stamp_tax_cents))
        else:
            result["cashFlowId"] = str(change.ledger_id)
        if change.status == "VOID":
            result["status"] = "VOID"
        receipt = TypeAdapter(SuccessReceipt).validate_python(dict(requestId=str(request.request_id),
            attemptId=str(attempt.attempt_id),operationType=operation,acceptedAt=accepted_time(now),result=result))
        return self.protocol.saved(session,locked,receipt.model_dump(mode="json"),now)
