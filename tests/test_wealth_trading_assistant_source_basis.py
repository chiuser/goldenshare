"""Source changes invalidate page reuse and final acceptance, without deleting facts."""
from dataclasses import asdict
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import insert, update
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.security_serving import Security
from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsReader
from src.biz.services.wealth.market.trading_assistant.validation import QuantityValidation
from src.biz.services.wealth.market.trading_assistant.validation_pages import ValidationPage
from src.biz.services.wealth.market.trading_assistant.validation_checkpoints import ValidationCheckpoints
from src.biz.services.wealth.market.trading_assistant.validation_basis import verify_source_basis, ValidationBasisChanged
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocol


def test_source_recheck_detects_calendar_and_security_changes(database):
    day = date(2026, 9, 11)
    policy = TradingAssistantExecutionPolicyV1()
    market = MarketFactsReader(policy)
    candidate, run = uuid4(), uuid4()
    with database.begin() as conn:
        account, _, _ = seed_account(conn)
        conn.execute(insert(Security).values(ts_code="000001.SZ", symbol="000001", name="测试", exchange="SZSE",
            security_type="EQUITY", curr_type="CNY", source="test"))
        conn.execute(insert(TradeCalendar).values(exchange="SSE", trade_date=day, is_open=True, pretrade_date=date(2026, 9, 10)))
    job = SimpleNamespace(candidate_id=candidate, run_id=run, owner_id=1, change=SimpleNamespace(account_id=account))
    with Session(database) as session, session.begin():
        security = market.resolve_security(session, "000001.SZ", Deadline.after_ms(5000))
        session.add(ValidationCandidate(candidate_id=candidate, owner_id=1, account_id=account, purpose="PREVIEW",
            input_schema_version=1, input_digest=b"a"*32, input_payload={}, basis={"securities":[asdict(security)]},
            created_at=datetime.now(timezone.utc)))
        session.flush()
        ValidationCheckpoints(WriteProtocol(policy)).store(session, owner_id=1, candidate_id=candidate, run_id=run,
            stock="000001.SZ", basis_digest=b"b"*32, before=None,
            page=ValidationPage(QuantityValidation(day, 0, 0), None, True, 0, 0, (("2026-09-11", True, "2026-09-10"),)),
            now=datetime.now(timezone.utc), deadline=Deadline.after_ms(5000))
        verify_source_basis(session, job, market=market, deadline=Deadline.after_ms(5000))
    with database.begin() as conn:
        conn.execute(update(TradeCalendar).values(is_open=False))
    with Session(database) as session, session.begin(), pytest.raises(ValidationBasisChanged):
        verify_source_basis(session, job, market=market, deadline=Deadline.after_ms(5000))
    with database.begin() as conn:
        conn.execute(update(TradeCalendar).values(is_open=True))
        conn.execute(update(Security).values(name="修订名称"))
    with Session(database) as session, session.begin(), pytest.raises(ValidationBasisChanged):
        verify_source_basis(session, job, market=market, deadline=Deadline.after_ms(5000))


def test_initial_account_rechecks_stock_eligibility_after_early_lookup(database):
    import asyncio
    from sqlalchemy import select, func
    from sqlalchemy.ext.asyncio import create_async_engine
    from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
    from src.biz.schemas.wealth.market.trading_assistant.accounts import CreateAccountCommand
    from src.biz.models.wealth.trading_assistant.accounts import Account
    with database.begin() as connection:
        connection.execute(insert(Security).values(ts_code="600004.SH", name="初始身份测试", exchange="SSE", security_type="EQUITY", curr_type="CNY", source="test"))
        before = connection.scalar(select(func.count()).select_from(Account))
    async def run():
        engine = create_async_engine(database.url)
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(),
            now=lambda:datetime(2026,9,11,8,tzinfo=timezone.utc), executor_id="initial-identity")
        resolve = deps.accounts.market.resolve_security
        changed = False
        def change_after_lookup(session, stock, deadline):
            nonlocal changed
            result = resolve(session,stock,deadline)
            if not changed:
                changed = True
                with database.begin() as connection:
                    connection.execute(update(Security).where(Security.ts_code == stock).values(curr_type="USD"))
            return result
        deps.accounts.market.resolve_security = change_after_lookup
        try:
            state = await deps.accounts.create(owner_id=1,command=CreateAccountCommand(requestId=str(uuid4()), attemptId=str(uuid4()),
                name="身份变更测试", brokerName="券商", commissionRateWan="2.35", minimumCommission="5.00", stampTaxRatePct="0.05",
                initialCash="0.00", initialPositions=[dict(clientRowId="identity-row", tsCode="600004.SH", openedOn="2026-09-11", quantity=10, availableQuantity=10, costPrice="10.00")]))
            assert state.status == "NOT_SAVED"
            assert state.field_errors[0].field == "initialPositions.tsCode" and state.field_errors[0].clientRowId == "identity-row"
        finally:
            await engine.dispose()
    asyncio.run(run())
    with database.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Account)) == before
