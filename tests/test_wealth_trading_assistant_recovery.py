"""Target-bound recovery against the isolated M2 PostgreSQL migration."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from src.biz.models.wealth.trading_assistant.ledger import Ledger
from src.biz.queries.wealth.market.trading_assistant.write_recovery import WriteRecoveryQueries
from src.biz.schemas.wealth.market.trading_assistant.targets import LedgerTarget
from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountLedgerScope
from src.biz.schemas.wealth.market.trading_assistant.recovered_inputs import RecoveryInputResponse
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocol, WriteProtocolConflict, canonical_input
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1


def deadline():
    return Deadline.after_ms(10000)


@pytest.mark.parametrize("operation,kind", [
    ("TRADE_CORRECT", "TRADE"), ("TRADE_VOID", "TRADE"),
    ("CASH_FLOW_CORRECT", "CASH_FLOW"), ("CASH_FLOW_VOID", "CASH_FLOW"),
])
def test_target_is_required_typed_and_digest_bound(operation, kind):
    account, record, other = map(str, (uuid4(), uuid4(), uuid4()))
    target = LedgerTarget(accountId=account, recordId=record, kind=kind)
    key = "ACCOUNT_LEDGER:" + account
    assert canonical_input(operation, key, {}, target)[1] != canonical_input(
        operation, key, {}, target.model_copy(update={"recordId": other}))[1]
    for invalid in (None, target.model_copy(update={"accountId": other}),
                    target.model_copy(update={"kind": "CASH_FLOW" if kind == "TRADE" else "TRADE"})):
        with pytest.raises(ValueError):
            canonical_input(operation, key, {}, invalid)
    with pytest.raises(ValueError):
        canonical_input("TRADE_CREATE", key, {}, target)


def test_missing_recovery_target_key_rejected():
    with pytest.raises(ValidationError):
        TypeAdapter(RecoveryInputResponse).validate_python(dict(
            requestId=str(uuid4()), operationType="TRADE_VOID", inputSchemaVersion="1",
            input={"expectedRevision": "1"}))


def test_saved_recovery_rejects_wrong_record_receipt():
    from src.biz.schemas.wealth.market.trading_assistant.recovery import RecoveryStatusDto
    from tests.test_wealth_trading_assistant_contracts import operation_fixtures, ID, ID2
    receipt = dict(requestId=ID, attemptId=ID2, operationType="TRADE_CORRECT",
                   acceptedAt="2026-09-11T16:00:00+08:00", result=operation_fixtures()[0]["TRADE_CORRECT"])
    value = dict(requestId=ID, attemptId=ID2, operationType="TRADE_CORRECT",
        scope=dict(scopeType="ACCOUNT_LEDGER", accountId=ID),
        target=dict(accountId=ID,kind="TRADE",recordId=receipt["result"]["tradeId"]),
        stateVersion="1", outcome="SAVED", inputRetained=True, summary=dict(title="更正交易",lines=[]),
        receipt=receipt, rejection=None, updatedAt=receipt["acceptedAt"])
    assert RecoveryStatusDto(**value)
    with pytest.raises(ValidationError, match="retained ledger target"):
        RecoveryStatusDto(**{**value, "target":{**value["target"], "recordId":str(uuid4())}})


def test_expiry_maintenance_commits_each_unit_and_honors_cancellation(database):
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine
    from src.app.runtime.trading_assistant_transactions import TradingAssistantTransactions
    from src.biz.services.wealth.market.trading_assistant.recovery_maintenance import RecoveryMaintenance
    policy = TradingAssistantExecutionPolicyV1()
    protocol = WriteProtocol(policy)
    now = datetime.now(timezone.utc)
    states = []
    for _ in range(3):
        with database.begin() as conn:
            account, _, _ = seed_account(conn)
        with Session(database) as session, session.begin():
            states.append(protocol.register(session, owner_id=1, request_id=uuid4(), attempt_id=uuid4(),
                scope=AccountLedgerScope(scopeType="ACCOUNT_LEDGER",accountId=str(account)),
                operation="CASH_FLOW_CREATE", payload={"direction":"IN","occurredOn":"2026-09-11","amount":"1.00"},
                now=now, executor_id="dead-process", deadline=deadline()))

    async def run():
        engine = create_async_engine(database.url)
        try:
            runner = TradingAssistantTransactions(engine)
            maintenance = RecoveryMaintenance(runner,protocol,policy,lambda:now+timedelta(seconds=16))
            checks = 0
            def cancel_after_first():
                nonlocal checks
                checks += 1
                return checks >= 3
            assert await maintenance.sweep(deadline=deadline(),cancelled=cancel_after_first) == 1
            with Session(database) as session:
                values = [protocol.read(session,owner_id=1,request_id=s.request_id).status for s in states]
                assert values.count("NOT_SAVED") == 1 and values.count("PROCESSING") == 2
            assert await maintenance.sweep(deadline=deadline(),cancelled=lambda:False) == 2
            assert await maintenance.sweep(deadline=deadline(),cancelled=lambda:False) == 0
        finally:
            await engine.dispose()
    asyncio.run(run())
    with Session(database) as session:
        for state in states:
            restored = WriteRecoveryQueries(policy).recoverable_input(
                session,owner_id=1,request_id=state.request_id,deadline=deadline())
            assert restored.input.amount == "1.00"
        # Maintenance did not auto-accept even valid retained cash entries.
        from src.biz.models.wealth.trading_assistant.ledger import LedgerRevision
        assert session.scalar(select(LedgerRevision.ledger_id).where(
            LedgerRevision.account_id.in_([UUID(s.scope_key.split(":")[1]) for s in states])).limit(1)) is None


@pytest.mark.parametrize("same_request", [True, False])
def test_concurrent_scope_registration_has_one_executor(database, same_request):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from src.biz.models.wealth.trading_assistant.recovery import WriteAttempt
    policy = TradingAssistantExecutionPolicyV1()
    protocol = WriteProtocol(policy)
    now = datetime.now(timezone.utc)
    with database.begin() as conn:
        account, _, _ = seed_account(conn)
    scope = AccountLedgerScope(scopeType="ACCOUNT_LEDGER", accountId=str(account))
    request, attempt = uuid4(), uuid4()
    barrier = Barrier(8)
    def register(_):
        barrier.wait(timeout=10)
        try:
            with Session(database) as session, session.begin():
                return protocol.register(session, owner_id=1,
                    request_id=request if same_request else uuid4(), attempt_id=attempt if same_request else uuid4(),
                    scope=scope, operation="CASH_FLOW_CREATE",
                    payload={"direction":"IN","occurredOn":"2026-09-11","amount":"1.00"},
                    now=now, executor_id="test", deadline=deadline()).execute
        except WriteProtocolConflict as exc:
            assert not same_request and exc.code == "TA_SCOPE_WRITE_PENDING"
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(register, range(8)))
    assert results.count(True) == 1
    with Session(database) as session, session.begin():
        from src.biz.models.wealth.trading_assistant.recovery import WriteRequest
        active = session.execute(select(WriteRequest.request_id).join(WriteAttempt,
            (WriteAttempt.owner_id == WriteRequest.owner_id) & (WriteAttempt.request_id == WriteRequest.request_id))
            .where(WriteRequest.scope_key == "ACCOUNT_LEDGER:"+str(account), WriteAttempt.status == "PROCESSING")).all()
        assert len(active) == 1
        protocol.expire(session,owner_id=1,request_id=active[0][0],key="ACCOUNT_LEDGER:"+str(account),
                        now=now+timedelta(seconds=16),deadline=deadline())


@pytest.mark.parametrize("kind", ["TRADE", "CASH_FLOW"])
def test_refresh_recovers_exact_target_and_rejects_cross_target_replay(database, kind):
    policy = TradingAssistantExecutionPolicyV1()
    protocol, queries = WriteProtocol(policy), WriteRecoveryQueries(policy)
    now = datetime.now(timezone.utc)
    with database.begin() as conn:
        account, _, _ = seed_account(conn)
        foreign, _, _ = seed_account(conn)
        records = [uuid4(), uuid4(), uuid4()]
        for record, owner_account in zip(records, [account, account, foreign]):
            conn.execute(insert(Ledger).values(ledger_id=record, account_id=owner_account,
                                               kind=kind, created_at=now))
    scope = AccountLedgerScope(scopeType="ACCOUNT_LEDGER", accountId=str(account))
    target = LedgerTarget(accountId=str(account), kind=kind, recordId=str(records[1]))
    args = dict(owner_id=1, request_id=uuid4(), attempt_id=uuid4(), scope=scope,
                operation=kind + "_VOID", payload={"expectedRevision": "1"}, target=target,
                now=now, executor_id="test")
    with Session(database) as session, session.begin():
        state = protocol.register(session, **args, deadline=deadline())
    # A new session represents reload without any original form state.
    with Session(database) as session, session.begin():
        status = queries.pending(session, owner_id=1, scope=scope, deadline=deadline()).pendingRequest
        assert status.target == target and status.inputRetained and status.outcome == "PROCESSING"
        assert protocol.read(session, owner_id=1, request_id=state.request_id).target == target
        with pytest.raises(WriteProtocolConflict, match="TA_RECOVERY_STATE_CHANGED"):
            queries.recoverable_input(session, owner_id=1, request_id=state.request_id, deadline=deadline())
        assert queries.pending(session, owner_id=2, scope=scope, deadline=deadline()).pendingRequest is None
        with pytest.raises(WriteProtocolConflict, match="TA_RECOVERY_UNAVAILABLE"):
            queries.status(session, owner_id=2, request_id=state.request_id, deadline=deadline())
    for record, error in [(records[0], "TA_REQUEST_ID_CONFLICT"), (records[2], "TA_OBJECT_NOT_FOUND")]:
        with pytest.raises(WriteProtocolConflict, match=error):
            with Session(database) as session, session.begin():
                protocol.register(session, **{**args, "target":target.model_copy(update={"recordId":str(record)})},
                                  deadline=deadline())
    with Session(database) as session, session.begin():
        protocol.expire(session, owner_id=1, request_id=state.request_id, key=state.scope_key,
                        now=now+timedelta(seconds=16), deadline=deadline())
    with Session(database) as session, session.begin():
        restored = queries.recoverable_input(session, owner_id=1, request_id=state.request_id, deadline=deadline())
        assert restored.target.model_dump() == target.model_dump() and restored.input.expectedRevision == "1"
        assert queries.pending(session, owner_id=1, scope=scope, deadline=deadline()).pendingRequest is None
        # Reading did not start a retry or alter the explicit stop proof.
        assert queries.status(session, owner_id=1, request_id=state.request_id, deadline=deadline()).outcome == "NOT_SAVED"
