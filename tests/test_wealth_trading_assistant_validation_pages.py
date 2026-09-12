"""Full-day validation across real PostgreSQL page boundaries."""
from datetime import date, datetime, timezone
from dataclasses import replace
from uuid import UUID, uuid4

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from src.biz.models.wealth.trading_assistant.ledger import Ledger, LedgerRevision
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsReader
from src.biz.services.wealth.market.trading_assistant.validation import CashValidation
from src.biz.services.wealth.market.trading_assistant.validation_pages import ValidationPageReader
import pytest


def seed_cash_day(database, count=501):
    now = datetime.now(timezone.utc)
    offset = uuid4().int - count
    with database.begin() as conn:
        account,_,_ = seed_account(conn)
        ledger, revisions = [], []
        for n in range(count):
            identifier = UUID(int=offset+n)
            inward = n == count-1
            amount = f"{count-1 if inward else 1}.00"
            ledger.append(dict(ledger_id=identifier,account_id=account,kind="CASH_FLOW",created_at=now))
            revisions.append(dict(ledger_id=identifier,account_id=account,kind="CASH_FLOW",revision=1,
                accepted_fact_version=n+2,occurred_on=date(2026,9,11),accepted_at=now,status="ACTIVE",
                direction="IN" if inward else "OUT",cash_amount=amount,
                net_cash_change=amount if inward else "-"+amount))
        conn.execute(insert(Ledger),ledger)
        conn.execute(insert(LedgerRevision),revisions)
    return account


def test_mid_day_negative_page_is_not_a_negative_day(database):
    account = seed_cash_day(database)
    policy = TradingAssistantExecutionPolicyV1()
    reader = ValidationPageReader(policy,MarketFactsReader(policy))
    with Session(database) as session,session.begin():
        first = reader.read(session,owner_id=1,account_id=account,fact_version=502,
            state=CashValidation(0),deadline=Deadline.after_ms(10000))
        assert first.rows == 500 and not first.complete
        assert first.state.cash_cents == 0 and first.state.day_delta_cents == -50000
    with Session(database) as session,session.begin():
        last = reader.read(session,owner_id=1,account_id=account,fact_version=502,
            state=first.state,after=first.after,deadline=Deadline.after_ms(10000))
        assert last.complete and last.rows == 1 and last.state.cash_cents == 0
        assert last.state.checked_rows == 501


def test_byte_boundary_returns_continuation_not_false_completion(database):
    account = seed_cash_day(database,5)
    policy = replace(TradingAssistantExecutionPolicyV1(),page_bytes=140)
    reader = ValidationPageReader(policy,MarketFactsReader(policy))
    state,after = CashValidation(0),None
    total,pages = 0,0
    while True:
        with Session(database) as session,session.begin():
            page = reader.read(session,owner_id=1,account_id=account,fact_version=6,
                state=state,after=after,deadline=Deadline.after_ms(10000))
        total += page.rows
        pages += 1
        assert page.bytes_read <= policy.page_bytes
        state,after = page.state,page.after
        if page.complete:
            break
    assert total == 5 and pages == 5 and state.cash_cents == 0


def test_checkpoint_resume_is_exact_and_replay_is_not_accumulated_twice(database):
    from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate,ValidationCheckpoint
    from src.biz.services.wealth.market.trading_assistant.validation_checkpoints import ValidationCheckpoints
    from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocol
    account = seed_cash_day(database)
    policy = TradingAssistantExecutionPolicyV1()
    reader = ValidationPageReader(policy,MarketFactsReader(policy))
    store = ValidationCheckpoints(WriteProtocol(policy))
    candidate,run = uuid4(),uuid4()
    now = datetime.now(timezone.utc)
    with Session(database) as session,session.begin():
        session.add(ValidationCandidate(candidate_id=candidate,owner_id=1,account_id=account,purpose="PREVIEW",
            input_schema_version=1,input_digest=b"a"*32,input_payload={},basis={},created_at=now))
        session.flush()
        first = reader.read(session,owner_id=1,account_id=account,fact_version=502,
            state=CashValidation(0),deadline=Deadline.after_ms(10000))
        checkpoint = store.store(session,owner_id=1,candidate_id=candidate,run_id=run,stock=None,
            basis_digest=b"b"*32,before=None,page=first,now=now,deadline=Deadline.after_ms(10000))
        checkpoint_id = checkpoint.checkpoint_id
    with Session(database) as session,session.begin():
        stored = session.get(ValidationCheckpoint,checkpoint_id)
        restored = store.restore(stored,basis_digest=b"b"*32)
        assert restored == first and not restored.complete
        repeated = store.store(session,owner_id=1,candidate_id=candidate,run_id=run,stock=None,
            basis_digest=b"b"*32,before=None,page=restored,now=now,deadline=Deadline.after_ms(10000))
        assert repeated.checkpoint_id == checkpoint_id
        with pytest.raises(ValueError,match="different facts"):
            store.restore(stored,basis_digest=b"c"*32)
        final = reader.read(session,owner_id=1,account_id=account,fact_version=502,
            state=restored.state,after=restored.after,deadline=Deadline.after_ms(10000))
        store.store(session,owner_id=1,candidate_id=candidate,run_id=run,stock=None,
            basis_digest=b"b"*32,before=restored.after,page=final,now=now,deadline=Deadline.after_ms(10000))
        assert final.complete and final.state.cash_cents == 0


def test_completion_requires_cash_and_every_affected_stock(database):
    from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate
    from src.biz.services.wealth.market.trading_assistant.validation_checkpoints import ValidationCheckpoints
    from src.biz.services.wealth.market.trading_assistant.validation_completion import read_completion
    from src.biz.services.wealth.market.trading_assistant.validation_pages import ValidationPage
    from src.biz.services.wealth.market.trading_assistant.validation import QuantityValidation
    from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocol
    policy = TradingAssistantExecutionPolicyV1()
    store = ValidationCheckpoints(WriteProtocol(policy))
    with database.begin() as conn:
        account, _, _ = seed_account(conn)
    candidate, run = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    args = dict(owner_id=1,account_id=account,candidate_id=candidate,run_id=run,basis_digest=b"d"*32,
                affected_stocks=("000001.SZ","600000.SH"),checkpoints=store,policy=policy)
    with Session(database) as session,session.begin():
        session.add(ValidationCandidate(candidate_id=candidate,owner_id=1,account_id=account,purpose="PREVIEW",
            input_schema_version=1,input_digest=b"a"*32,input_payload={},basis={},created_at=now))
        session.flush()
        for stock in (None,"000001.SZ","600000.SH"):
            with pytest.raises(ValueError,match="incomplete"):
                read_completion(session,**args,deadline=Deadline.after_ms(10000))
            state = (QuantityValidation(date(2026,9,11),0,0) if stock else CashValidation(0))
            store.store(session,owner_id=1,candidate_id=candidate,run_id=run,stock=stock,
                basis_digest=b"d"*32,before=None,page=ValidationPage(state,None,True,0,0,()),
                now=now,deadline=Deadline.after_ms(10000))
    with Session(database) as session,session.begin():
        proof = read_completion(session,**args,deadline=Deadline.after_ms(10000))
        assert [(s[0],s[1],s[3]) for s in proof.scans] == [
            ("CASH","",0),("QUANTITY","000001.SZ",0),("QUANTITY","600000.SH",0)]
        with pytest.raises(ValueError,match="different facts"):
            read_completion(session,**{**args,"basis_digest":b"e"*32},deadline=Deadline.after_ms(10000))


def test_validator_pages_commit_before_cancellation_and_replay_without_double_count(database):
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine
    from src.app.runtime.trading_assistant_transactions import TradingAssistantTransactions
    from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate,ValidationCheckpoint
    from src.biz.schemas.wealth.market.trading_assistant.accounts import CashFlowInput
    from src.biz.services.wealth.market.trading_assistant.ledger_preparation import prepare_cash
    from src.biz.services.wealth.market.trading_assistant.ledger_validation import LedgerValidator,LedgerValidationInput
    from src.biz.services.wealth.market.trading_assistant.validation_checkpoints import ValidationCheckpoints
    from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocol
    account = seed_cash_day(database)
    policy = TradingAssistantExecutionPolicyV1()
    reader = ValidationPageReader(policy,MarketFactsReader(policy))
    store = ValidationCheckpoints(WriteProtocol(policy))
    candidate,run = uuid4(),uuid4()
    now = datetime.now(timezone.utc)
    change = prepare_cash(account_id=account,ledger_id=uuid4(),
        data=CashFlowInput(direction="IN",occurredOn="2026-09-11",amount="1.00"))
    job = LedgerValidationInput(1,candidate,run,502,b"f"*32,change,CashValidation(0),())
    with Session(database) as session,session.begin():
        session.add(ValidationCandidate(candidate_id=candidate,owner_id=1,account_id=account,purpose="PREVIEW",
            input_schema_version=1,input_digest=b"a"*32,input_payload={},basis={},created_at=now))
    async def execute():
        engine = create_async_engine(database.url)
        try:
            validator = LedgerValidator(TradingAssistantTransactions(engine),reader,store,policy,lambda:now)
            calls = 0
            def cancelled():
                nonlocal calls
                calls += 1
                return calls >= 4
            with pytest.raises(asyncio.CancelledError):
                await validator.validate(job,deadline=Deadline.after_ms(10000),cancelled=cancelled)
            with Session(database) as session:
                pages = list(session.scalars(select(ValidationCheckpoint).where(ValidationCheckpoint.candidate_id == candidate)))
                assert len(pages) == 1 and pages[0].checked_row_count == 500
                assert pages[0].completed_range["complete"] is False
            proof = await validator.validate(job,deadline=Deadline.after_ms(10000),cancelled=lambda:False)
            assert proof.scans[0][3] == 502
        finally:
            await engine.dispose()
    asyncio.run(execute())
    with Session(database) as session:
        pages = list(session.scalars(select(ValidationCheckpoint).where(ValidationCheckpoint.candidate_id == candidate)))
        assert len(pages) == 2
        final = next(p for p in pages if p.completed_range["complete"])
        assert store.restore(final,basis_digest=b"f"*32).state.cash_cents == 100
        assert session.get(Ledger,change.ledger_id) is None
