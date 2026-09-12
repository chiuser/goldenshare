"""An initialization replacement changes opening balances, never invents a trade."""
from dataclasses import dataclass, asdict
from uuid import UUID, uuid4

from sqlalchemy import select, union

from src.biz.models.wealth.trading_assistant.accounts import Account, Initialization, InitialPosition
from src.biz.models.wealth.trading_assistant.recovery import WriteRequest, ValidationCandidate, ValidationCheckpoint
from src.biz.queries.wealth.market.trading_assistant.effective_ledger import effective_ledger
from .account_acceptance import assert_retained_input
from .calculation.precision import parse_money_cents
from .ledger_validation import LedgerValidationInput, StockOpening
from .market_facts import apply_sql_budget, facts_digest
from .validation import CashValidation, QuantityValidation
from .write_protocol import WriteProtocolConflict


@dataclass(frozen=True, slots=True)
class InitializationChange:
    account_id: UUID
    affected_stocks: tuple[str, ...]
    replacement: None = None
    replaced_ledger_id: None = None


def prepare_initialization(session, *, state, command, market, policy, deadline):
    apply_sql_budget(session, deadline, policy)
    request = session.get(WriteRequest, (state.owner_id, state.request_id))
    assert_retained_input(request, command)
    account_id = UUID(state.scope_key.removeprefix("ACCOUNT_LEDGER:"))
    candidate = session.get(ValidationCandidate, request.candidate_id)
    return prepare_initialization_facts(session, owner_id=state.owner_id, account_id=account_id,
        candidate=candidate, command=command, market=market, policy=policy, deadline=deadline)


def prepare_initialization_facts(session, *, owner_id, account_id, candidate, command, market, policy, deadline):
    if candidate.owner_id != owner_id or candidate.account_id != account_id:
        raise ValueError("Initialization candidate belongs to another owner or account")
    account = session.scalar(select(Account).where(Account.account_id == account_id, Account.owner_id == owner_id))
    if account is None:
        raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
    initial = session.get(Initialization, account.current_initialization_id)
    if str(initial.revision) != command.expectedRevision:
        raise WriteProtocolConflict("TA_STATE_CONFLICT")
    proposed = {row.tsCode: row for row in command.initialPositions}
    facts = effective_ledger(owner_id=owner_id, account_id=account_id, fact_version=account.fact_version)
    stocks = union(select(InitialPosition.ts_code).where(InitialPosition.initialization_id == initial.initialization_id),
        select(facts.c.ts_code).where(facts.c.kind == "TRADE")).subquery()
    affected, after = set(proposed), None
    while True:
        apply_sql_budget(session, deadline, policy)
        query = select(stocks.c.ts_code)
        if after is not None:
            query = query.where(stocks.c.ts_code > after)
        page = session.scalars(query.order_by(stocks.c.ts_code).limit(policy.page_rows)).all()
        affected.update(page)
        if len(page) < policy.page_rows:
            break
        after = page[-1]
    openings, securities = [], []
    for stock in sorted(affected):
        security = market.resolve_security(session, stock, deadline)
        securities.append(asdict(security))
        row = proposed.get(stock)
        openings.append(StockOpening(stock, security.exchange, QuantityValidation(account.initialized_on,
            row.quantity if row else 0, row.availableQuantity if row else 0)))
    basis = dict(accountId=str(account_id), factVersion=str(account.fact_version),
        initializationId=str(initial.initialization_id), inputDigest=candidate.input_digest.hex(),
        ruleVersion=1, securities=securities)
    digest = bytes.fromhex(facts_digest(basis))
    previous_run = session.scalar(select(ValidationCheckpoint.validation_run_id).where(
        ValidationCheckpoint.candidate_id == candidate.candidate_id, ValidationCheckpoint.basis_digest == digest)
        .order_by(ValidationCheckpoint.updated_at.desc()).limit(1))
    change = InitializationChange(account_id, tuple(sorted(affected)))
    job = LedgerValidationInput(owner_id, candidate.candidate_id, previous_run or uuid4(),
        account.fact_version, digest, change, CashValidation(parse_money_cents(command.initialCash)), tuple(openings))
    return job, basis
