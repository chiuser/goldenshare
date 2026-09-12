"""Business-read-only previews with isolated, non-accepting validation candidates."""
from uuid import UUID, uuid4

from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.ledger import LedgerRevision
from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate
from src.biz.schemas.wealth.market.trading_assistant import previews as dto
from src.biz.schemas.wealth.market.trading_assistant.errors import FieldErrorDto
from .calculation.precision import format_cents
from .execution_policy import Deadline
from .ledger_candidate import prepare_ledger_facts
from .ledger_validation import LedgerValidator
from .market_facts import apply_sql_budget, MarketFactsUnavailable
from .persistence_values import numeric_cents
from .validation import InvalidLedger
from .validation_checkpoints import ValidationCheckpoints
from .validation_pages import ValidationPageReader
from .write_protocol import WriteProtocol, WriteProtocolConflict, canonical_input


def projected_facts(change):
    if change.kind == "TRADE":
        amounts = change.amounts
        return dto.TradePreviewFacts(tsCode=change.ts_code, direction=change.direction,
            tradeDate=change.occurred_on.isoformat(), price=format_cents(change.price_cents), quantity=change.quantity,
            note=change.note, grossAmount=format_cents(amounts.gross_cents),
            commissionAmount=format_cents(amounts.commission_cents), stampTaxAmount=format_cents(amounts.stamp_tax_cents),
            netCashChange=format_cents(change.net_cash_cents), feeVersionId=str(change.fee_version_id))
    return dto.CashPreviewFacts(direction=change.direction, occurredOn=change.occurred_on.isoformat(),
        amount=format_cents(change.cash_cents), netCashChange=format_cents(change.net_cash_cents), note=change.note)


def original_facts(row):
    if row.kind == "TRADE":
        return dto.TradePreviewFacts(tsCode=row.ts_code, direction=row.direction, tradeDate=row.occurred_on.isoformat(),
            price=format_cents(numeric_cents(row.price)), quantity=row.quantity, note=row.note,
            grossAmount=format_cents(numeric_cents(row.gross_amount)), commissionAmount=format_cents(numeric_cents(row.commission_amount)),
            stampTaxAmount=format_cents(numeric_cents(row.stamp_tax_amount)), netCashChange=format_cents(numeric_cents(row.net_cash_change)),
            feeVersionId=str(row.fee_version_id))
    return dto.CashPreviewFacts(direction=row.direction, occurredOn=row.occurred_on.isoformat(),
        amount=format_cents(numeric_cents(row.cash_amount)), netCashChange=format_cents(numeric_cents(row.net_cash_change)), note=row.note)


from .validation_basis import verify_source_basis, ValidationBasisChanged


class LedgerPreviewService:
    def __init__(self, transactions, market, policy, now):
        self.transactions, self.market, self.policy, self.now = transactions, market, policy, now
        self.validator = LedgerValidator(transactions, ValidationPageReader(policy, market),
            ValidationCheckpoints(WriteProtocol(policy)), policy, now)

    async def preview(self, *, owner_id, account_id, command, target=None):
        deadline = Deadline.after_ms(self.policy.read_request_budget_ms)
        operation = (target.kind + "_CORRECT") if target else "TRADE_CREATE"
        payload = command.model_dump(mode="json")
        payload, digest = canonical_input(operation, f"ACCOUNT_LEDGER:{account_id}", payload, target)
        def prepare(session):
            apply_sql_budget(session, deadline, self.policy)
            if session.scalar(select(Account.account_id).where(Account.account_id == account_id, Account.owner_id == owner_id)) is None:
                raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
            candidate = ValidationCandidate(candidate_id=uuid4(), owner_id=owner_id, account_id=account_id,
                purpose="PREVIEW", request_id=None, input_schema_version=1, input_digest=digest,
                input_payload=payload, basis={}, created_at=self.now())
            session.add(candidate)
            session.flush()
            job, basis = prepare_ledger_facts(session, owner_id=owner_id, account_id=account_id,
                operation=operation, target=target, input_digest=digest, candidate=candidate, command=command,
                ledger_id=UUID(target.recordId) if target else uuid4(), market=self.market, policy=self.policy, deadline=deadline)
            candidate.basis = basis
            before = None
            if target:
                before = original_facts(session.get(LedgerRevision, (UUID(target.recordId), int(command.expectedRevision))))
            return job, before
        job, before = await self.transactions.run(prepare, deadline=deadline, write=True)
        errors, status = [], "Ready"
        try:
            await self.validator.validate(job, deadline=deadline, cancelled=lambda:False)
        except InvalidLedger as error:
            field = "quantity" if job.change.kind == "TRADE" and error.field == "amount" else error.field
            errors.append(FieldErrorDto(field=field, clientRowId=None, message=error.message,
                affectedOn=error.occurred_on.isoformat()))
        except MarketFactsUnavailable:
            status = "Error"
            errors.append(FieldErrorDto(field="tradeDate", clientRowId=None,
                message="交易日历暂不可用，不能确认交易合法性", affectedOn=None))
        def final_check(session):
            try:
                verify_source_basis(session, job, market=self.market, deadline=deadline)
            except ValidationBasisChanged as error:
                raise WriteProtocolConflict("TA_READ_CONTEXT_CHANGED") from error
            apply_sql_budget(session, deadline, self.policy)
            account = session.scalar(select(Account).where(Account.account_id == account_id, Account.owner_id == owner_id))
            if account is None or account.fact_version != job.fact_version or (
                target is None and account.current_fee_version_id != job.change.fee_version_id):
                raise WriteProtocolConflict("TA_READ_CONTEXT_CHANGED")
        await self.transactions.run(final_check, deadline=deadline, write=False)
        after = projected_facts(job.change)
        if target is None:
            return dto.TradePreview(**after.model_dump(include={"grossAmount", "commissionAmount", "stampTaxAmount", "netCashChange", "feeVersionId"}),
                factVersion=str(job.fact_version), calendarDataStatus=status, fieldErrors=errors)
        model = dto.TradeCorrectionPreview if target.kind == "TRADE" else dto.CashCorrectionPreview
        changed = [dto.ChangedField(field=key, clientRowId=None) for key, value in after.model_dump().items()
                   if getattr(before, key) != value]
        return model(before=before, after=after, changedFields=changed, affectedFromDate=job.change.affected_from.isoformat(),
            factVersion=str(job.fact_version), expectedRevision=command.expectedRevision, fieldErrors=errors)
