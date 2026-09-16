"""Real retained-request rule writes, using only a fresh isolated database."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4, UUID

import pytest
from sqlalchemy import insert, select, func
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from tests.test_wealth_trading_assistant_rule_storage import rule_database
from src.app.runtime.trading_assistant_transactions import TradingAssistantTransactions
from src.foundation.models.core_serving.security_serving import Security
from src.biz.models.wealth.trading_assistant.rules import Rule, RuleVersion
from src.biz.models.wealth.trading_assistant.ledger import Ledger
from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate
from src.biz.schemas.wealth.market.trading_assistant.rules import (
    CreatePlanCommand, CreateAlertCommand, ReviseConditionsCommand, CloseRuleCommand,
)
from src.biz.schemas.wealth.market.trading_assistant.scopes import RuleCreateScope, RuleScope
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsReader
from src.biz.services.wealth.market.trading_assistant.rule_commands import RuleCommandService
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict, scope_key, parse_scope_key
from src.biz.queries.wealth.market.trading_assistant.write_recovery import WriteRecoveryQueries


NOW = datetime(2026, 9, 15, 10, tzinfo=timezone(timedelta(hours=8)))


def identity():
    return dict(requestId=str(uuid4()), attemptId=str(uuid4()))


@pytest.fixture(scope="module")
def command_database(rule_database):
    with rule_database.begin() as conn:
        conn.execute(insert(Security).values(ts_code="000001.SZ", name="平安银行", exchange="SZSE",
            security_type="EQUITY", curr_type="CNY", source="isolated-test"))
    return rule_database


def plan(account, **changes):
    data = dict(**identity(), accountId=str(account), direction="SELL", stockCode="000001.SZ",
        deadlineAt="2026-09-15T15:00:00+08:00", source="TRADING_ASSISTANT",
        priceCondition={"operator": "LTE", "upper": "10.00"}, volumeCondition=None)
    return CreatePlanCommand.model_validate(data | changes)


def test_create_revision_close_and_original_receipt_replay(command_database):
    with command_database.begin() as conn:
        account, _, _ = seed_account(conn)
    async def execute():
        engine = create_async_engine(command_database.url)
        clock = [NOW]
        policy = TradingAssistantExecutionPolicyV1()
        transactions = TradingAssistantTransactions(engine)
        service = RuleCommandService(transactions, MarketFactsReader(policy), policy, lambda: clock[0],
            executor_id="rule-command-test", resolve_robot=lambda *args: None,
            has_future_checkpoint=lambda session, security, after, through, deadline: after < through)
        queries = WriteRecoveryQueries(policy)
        original = plan(account)
        try:
            saved = await service.create(owner_id=1, kind="PLAN", command=original)
            assert saved.status == "SAVED", saved.rejection
            rule_id = UUID(saved.receipt["result"]["ruleId"])
            assert saved.receipt["result"]["direction"] == "SELL"  # No holdings required.
            assert (await service.create(owner_id=1, kind="PLAN", command=original)).receipt == saved.receipt
            clock[0] += timedelta(microseconds=1)
            revised = await service.revise(owner_id=1, kind="PLAN", rule_id=rule_id,
                command=ReviseConditionsCommand(**identity(), expectedStateVersion="1",
                    priceCondition={"operator": "LTE", "upper": "9.00"}, volumeCondition=None))
            assert revised.status == "SAVED", revised.rejection
            assert revised.receipt["result"]["acceptedStateVersion"] == "2"
            assert revised.receipt["result"]["effectiveAt"].endswith("000001+08:00")
            clock[0] += timedelta(hours=8)  # An overdue rule may still be closed.
            close = CloseRuleCommand(**identity(), expectedStateVersion="2")
            closed = await service.close(owner_id=1, kind="PLAN", rule_id=rule_id, command=close)
            assert closed.status == "SAVED", closed.rejection
            assert (await service.close(owner_id=1, kind="PLAN", rule_id=rule_id, command=close)).receipt == closed.receipt
            assert (await service.create(owner_id=1, kind="PLAN", command=original)).receipt == saved.receipt
            status = await transactions.run(lambda session: queries.status(session, owner_id=1,
                request_id=UUID(close.requestId), deadline=Deadline.after_ms(5000)),
                deadline=Deadline.after_ms(5000), write=False)
            assert status.scope.ruleId == str(rule_id) and status.outcome == "SAVED"
            with Session(command_database) as session:
                versions = session.scalars(select(RuleVersion).where(RuleVersion.rule_id == rule_id)
                    .order_by(RuleVersion.version_no)).all()
                assert [v.price_upper for v in versions] == [10, 9]
                assert session.get(Rule, rule_id).state == "CLOSED"
                assert session.scalar(select(func.count()).select_from(Ledger).where(Ledger.account_id == account)) == 0
        finally:
            await engine.dispose()
    asyncio.run(execute())


def test_rejection_retains_original_rule_input_and_never_allocates_ledger_candidate(command_database):
    with command_database.begin() as conn:
        account, _, _ = seed_account(conn)
    async def execute():
        engine = create_async_engine(command_database.url)
        policy = TradingAssistantExecutionPolicyV1()
        transactions = TradingAssistantTransactions(engine)
        service = RuleCommandService(transactions, MarketFactsReader(policy), policy, lambda: NOW,
            executor_id="rule-test", resolve_robot=lambda *args: None, has_future_checkpoint=lambda *args: False)
        queries = WriteRecoveryQueries(policy)
        command = plan(account, deadlineAt=NOW.isoformat())
        try:
            rejected = await service.create(owner_id=1, kind="PLAN", command=command)
            assert rejected.status == "NOT_SAVED"
            assert rejected.field_errors[0].field == "deadlineAt"
            recovered = await transactions.run(lambda session: queries.recoverable_input(session,
                owner_id=1, request_id=UUID(command.requestId), deadline=Deadline.after_ms(5000)),
                deadline=Deadline.after_ms(5000), write=False)
            assert recovered.operationType == "PLAN_CREATE"
            assert recovered.input.deadlineAt == command.deadlineAt
            with Session(command_database) as session:
                assert session.scalar(select(func.count()).select_from(ValidationCandidate).where(
                    ValidationCandidate.request_id == UUID(command.requestId))) == 0
            with pytest.raises(WriteProtocolConflict, match="TA_ACCOUNT_NOT_FOUND"):
                await service.create(owner_id=2, kind="PLAN", command=plan(account))
            alert = CreateAlertCommand(**identity(), stockCode="000001.SZ", robotId=str(uuid4()),
                deadlineAt="2026-09-15T15:00:00+08:00", source="STOCK_DETAIL",
                priceCondition=None, volumeCondition={"operator": "GTE", "thresholdLots": "1.00"})
            result = await service.create(owner_id=2, kind="ALERT", command=alert)
            assert result.status == "NOT_SAVED" and result.field_errors[0].field == "robotId"
        finally:
            await engine.dispose()
    asyncio.run(execute())


def test_rule_scope_roundtrip_and_rejection_of_ambiguous_encodings():
    for scope in (RuleScope(scopeType="RULE", ruleType="PLAN", ruleId=str(uuid4())),
                  RuleCreateScope(scopeType="RULE_CREATE", ruleType="ALERT", tsCode="000001.SZ", accountId=None)):
        assert parse_scope_key(scope_key(scope)) == scope
        with pytest.raises(ValueError):
            parse_scope_key(scope_key(scope).replace(":", ": ", 1))
