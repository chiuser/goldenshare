"""Original initialization and aligned proposed rows for the approved R12 review."""
from uuid import uuid4

from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate
from src.biz.queries.wealth.market.trading_assistant.accounts import AccountQueries
from src.biz.schemas.wealth.market.trading_assistant.accounts import InitializationPosition
from src.biz.schemas.wealth.market.trading_assistant.previews import InitializationCorrectionPreview, InitializationPreviewFacts, ChangedField
from src.biz.schemas.wealth.market.trading_assistant.errors import FieldErrorDto
from .calculation.precision import format_cents, parse_money_cents
from .execution_policy import Deadline
from .initialization_candidate import prepare_initialization_facts
from .ledger_validation import LedgerValidator
from .market_facts import apply_sql_budget
from .validation import InvalidLedger
from .validation_checkpoints import ValidationCheckpoints
from .validation_pages import ValidationPageReader
from .write_protocol import WriteProtocol, WriteProtocolConflict, canonical_input


class InitializationPreviewService:
    def __init__(self, transactions, market, policy, now):
        self.transactions, self.market, self.policy, self.now = transactions, market, policy, now
        self.accounts = AccountQueries(policy, market)
        self.validator = LedgerValidator(transactions, ValidationPageReader(policy, market),
            ValidationCheckpoints(WriteProtocol(policy)), policy, now)

    async def preview(self, *, owner_id, account_id, command):
        deadline = Deadline.after_ms(self.policy.read_request_budget_ms)
        payload, digest = canonical_input("INITIALIZATION_CORRECT", f"ACCOUNT_LEDGER:{account_id}", command.model_dump(mode="json"))
        def prepare(session):
            before = self.accounts.initialization(session, owner_id=owner_id, account_id=account_id, deadline=deadline)
            candidate = ValidationCandidate(candidate_id=uuid4(), owner_id=owner_id, account_id=account_id,
                purpose="PREVIEW", request_id=None, input_schema_version=1, input_digest=digest,
                input_payload=payload, basis={}, created_at=self.now())
            session.add(candidate)
            session.flush()
            job, basis = prepare_initialization_facts(session, owner_id=owner_id, account_id=account_id,
                candidate=candidate, command=command, market=self.market, policy=self.policy, deadline=deadline)
            candidate.basis = basis
            names = {fact["ts_code"]:fact["name"] for fact in basis["securities"]}
            after = [InitializationPosition(**row.model_dump(), stockRef={"tsCode":row.tsCode, "name":names[row.tsCode]},
                costAmount=format_cents(parse_money_cents(row.costPrice) * row.quantity)) for row in command.initialPositions]
            return job, before, after
        job, original, proposed = await self.transactions.run(prepare, deadline=deadline, write=True)
        errors = []
        try:
            await self.validator.validate(job, deadline=deadline, cancelled=lambda:False)
        except InvalidLedger as error:
            row = next((row for row in command.initialPositions if row.tsCode == error.ts_code), None)
            field = "initialCash" if error.field == "amount" else "initialPositions"
            if error.field == "quantity" and row is not None:
                field += ".availableQuantity" if error.occurred_on.isoformat() == original.initializedOn else ".quantity"
            errors.append(FieldErrorDto(field=field, clientRowId=row.clientRowId if row else None,
                message=error.message, affectedOn=error.occurred_on.isoformat()))
        def final_check(session):
            from .validation_basis import verify_source_basis, ValidationBasisChanged
            try:
                verify_source_basis(session, job, market=self.market, deadline=deadline)
            except ValidationBasisChanged as error:
                raise WriteProtocolConflict("TA_READ_CONTEXT_CHANGED") from error
            apply_sql_budget(session, deadline, self.policy)
            version = session.scalar(select(Account.fact_version).where(Account.account_id == account_id, Account.owner_id == owner_id))
            if version != job.fact_version:
                raise WriteProtocolConflict("TA_READ_CONTEXT_CHANGED")
        await self.transactions.run(final_check, deadline=deadline, write=False)
        before_by_stock = {row.tsCode:row for row in original.initialPositions}
        after_by_stock = {row.tsCode:row for row in proposed}
        stocks = sorted(before_by_stock.keys() | after_by_stock.keys())
        changed = []
        if original.initialCash != command.initialCash:
            changed.append(ChangedField(field="initialCash", clientRowId=None))
        for stock in stocks:
            before, after = before_by_stock.get(stock), after_by_stock.get(stock)
            if before is None or after is None:
                changed.append(ChangedField(field="initialPositions", clientRowId=(after or before).clientRowId))
            else:
                for field in ("openedOn", "quantity", "availableQuantity", "costPrice"):
                    if getattr(before, field) != getattr(after, field):
                        changed.append(ChangedField(field=f"initialPositions.{field}", clientRowId=after.clientRowId))
        return InitializationCorrectionPreview(
            before=InitializationPreviewFacts(initialCash=original.initialCash, initialPositions=[before_by_stock.get(s) for s in stocks]),
            after=InitializationPreviewFacts(initialCash=command.initialCash, initialPositions=[after_by_stock.get(s) for s in stocks]),
            changedFields=changed, affectedFromDate=job.change.affected_from.isoformat(), factVersion=original.factVersion,
            expectedRevision=command.expectedRevision, fieldErrors=errors)
