"""Owned immutable facts for a ledger validation run; no business acceptance."""
from dataclasses import asdict
from uuid import UUID, uuid4

from sqlalchemy import select, func

from src.biz.models.wealth.trading_assistant.accounts import Account, Initialization, InitialPosition, FeeVersion
from src.biz.models.wealth.trading_assistant.ledger import LedgerRevision
from src.biz.models.wealth.trading_assistant.recovery import WriteRequest, ValidationCandidate, ValidationCheckpoint
from src.biz.schemas.wealth.market.trading_assistant.accounts import TradeInput, CashFlowInput
from src.biz.queries.wealth.market.trading_assistant.effective_ledger import effective_ledger
from .account_acceptance import assert_retained_input
from .ledger_preparation import prepare_trade, prepare_cash, prepare_void
from .ledger_validation import LedgerValidationInput, StockOpening
from .market_facts import apply_sql_budget, facts_digest
from .persistence_values import numeric_cents
from .validation import CashValidation, QuantityValidation, InvalidLedger
from .write_protocol import WriteProtocolConflict


PROTOCOL_FIELDS = {"requestId", "attemptId", "expectedRequestStateVersion", "expectedRevision"}


def prepare_candidate(session, *, state, command, ledger_id, market, policy, deadline):
    apply_sql_budget(session, deadline, policy)
    request = session.get(WriteRequest,(state.owner_id,state.request_id))
    if request is None:
        raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
    assert_retained_input(request,command)
    candidate = session.get(ValidationCandidate,request.candidate_id)
    return prepare_ledger_facts(session, owner_id=state.owner_id,
        account_id=UUID(state.scope_key.removeprefix("ACCOUNT_LEDGER:")), operation=state.operation,
        target=state.target, input_digest=request.input_digest, candidate=candidate, command=command,
        ledger_id=ledger_id, market=market, policy=policy, deadline=deadline)


def prepare_ledger_facts(session, *, owner_id, account_id, operation, target, input_digest,
                         candidate, command, ledger_id, market, policy, deadline):
    """Shared prospective facts for explicit PREVIEW or retained SAVE candidates."""
    if candidate.owner_id != owner_id or candidate.account_id != account_id or candidate.input_digest != input_digest:
        raise ValueError("Candidate ownership or input differs")
    if target is None and candidate.basis.get("ledgerId"):
        # A cancelled create keeps its allocated identity when compatible input is retried.
        ledger_id = UUID(candidate.basis["ledgerId"])
    account = session.scalar(select(Account).where(Account.account_id == account_id,Account.owner_id == owner_id))
    if account is None:
        raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
    initial = session.get(Initialization,account.current_initialization_id)
    current_fee = session.get(FeeVersion,account.current_fee_version_id)
    original = None
    if target is not None:
        if target.accountId != str(account_id):
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        ledger_id = UUID(target.recordId)
        original = session.scalar(select(LedgerRevision).where(LedgerRevision.account_id == account_id,
            LedgerRevision.ledger_id == ledger_id,LedgerRevision.accepted_fact_version <= account.fact_version)
            .order_by(LedgerRevision.revision.desc()).limit(1))
        if original is None or original.kind != target.kind:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        if original.status != "ACTIVE" or str(original.revision) != command.expectedRevision:
            raise WriteProtocolConflict("TA_STATE_CONFLICT")
    data = command.model_dump(mode="json",exclude=PROTOCOL_FIELDS)
    if operation.endswith("_VOID"):
        change = prepare_void(account_id=account_id,ledger_id=ledger_id,original=original)
    elif operation.startswith("TRADE_"):
        change = prepare_trade(account_id=account_id,ledger_id=ledger_id,data=TradeInput.model_validate(data),
                               fee=current_fee,original=original)
    else:
        change = prepare_cash(account_id=account_id,ledger_id=ledger_id,data=CashFlowInput.model_validate(data),original=original)
    if change.occurred_on < account.initialized_on:
        raise InvalidLedger("tradeDate" if change.kind == "TRADE" else "occurredOn",change.occurred_on,
                            "日期不能早于账户初始化日期")
    if operation == "CASH_FLOW_CREATE" and change.direction == "OUT":
        facts = effective_ledger(owner_id=owner_id, account_id=account_id, fact_version=account.fact_version)
        delta = session.scalar(select(func.sum(facts.c.net_cash_change)))
        current_cash = numeric_cents(initial.initial_cash) + (numeric_cents(delta) if delta is not None else 0)
        if current_cash + change.net_cash_cents < 0:
            raise InvalidLedger("amount", change.occurred_on, "转出金额超过当前可用现金，请检查。")
    openings, securities = [], []
    for stock in change.affected_stocks:
        security = market.resolve_security(session,stock,deadline)
        securities.append(asdict(security))
        position = session.get(InitialPosition,(initial.initialization_id,stock))
        openings.append(StockOpening(stock,security.exchange,QuantityValidation(account.initialized_on,
            position.quantity if position else 0,position.available_quantity if position else 0)))
    basis = dict(accountId=str(account_id),factVersion=str(account.fact_version),
        initializationId=str(initial.initialization_id),inputDigest=input_digest.hex(),ruleVersion=1,
        feeVersionId=str(change.fee_version_id) if change.fee_version_id else None,
        sourceRevision=str(change.source_revision) if change.source_revision else None,
        ledgerId=str(change.ledger_id),securities=securities)
    digest = bytes.fromhex(facts_digest(basis))
    previous_run = session.scalar(select(ValidationCheckpoint.validation_run_id).where(
        ValidationCheckpoint.candidate_id == candidate.candidate_id,
        ValidationCheckpoint.basis_digest == digest).order_by(ValidationCheckpoint.updated_at.desc()).limit(1))
    job = LedgerValidationInput(owner_id,candidate.candidate_id,previous_run or uuid4(),account.fact_version,digest,change,
                                CashValidation(numeric_cents(initial.initial_cash)),tuple(openings))
    return job, basis
