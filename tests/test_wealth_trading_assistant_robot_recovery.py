"""Original robot candidate binding, real storage and official recovery GETs."""
import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError, TypeAdapter
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import create_async_engine
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.test_wealth_trading_assistant_persistence import database
from tests.test_wealth_trading_assistant_rule_storage import rule_database, NOW
from tests.test_wealth_trading_assistant_robot_storage import robot_database, candidate, test_row
from src.biz.models.wealth.trading_assistant.robots import RobotTest, RobotConfig
from src.biz.models.wealth.trading_assistant.recovery import WriteRequest
from src.biz.schemas.wealth.market.trading_assistant.robot import TestCandidateCommand as RobotTestCommand, ConfirmCandidateCommand
from src.biz.schemas.wealth.market.trading_assistant.recovered_inputs import RecoveryInputResponse
from src.biz.schemas.wealth.market.trading_assistant.scopes import RobotScope
from src.biz.queries.wealth.market.trading_assistant.write_recovery import WriteRecoveryQueries
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocol, WriteProtocolConflict, canonical_input
from src.biz.services.wealth.market.trading_assistant.robot_recovery_input import bind_robot_candidate

POLICY = TradingAssistantExecutionPolicyV1()
SCOPE = RobotScope(scopeType="ROBOT")


def deadline():
    return Deadline.after_ms(5000)


def payload(operation, cid, test_id=None):
    identity = dict(requestId=str(uuid4()), attemptId=str(uuid4()))
    command = (RobotTestCommand(**identity, expectedCandidateVersion="1") if operation == "ROBOT_TEST" else
        ConfirmCandidateCommand(**identity, expectedConfigVersionId=None, testId=str(test_id), receivedConfirmed=True))
    return bind_robot_candidate(operation, candidate_id=cid, command=command)


@pytest.mark.parametrize("operation", ["ROBOT_TEST", "ROBOT_CONFIRM"])
def test_candidate_is_required_digest_bound_and_not_editable(operation):
    first, second, test = uuid4(), uuid4(), uuid4()
    a, b = payload(operation, first, test), payload(operation, second, test)
    assert canonical_input(operation, "ROBOT", a)[1] != canonical_input(operation, "ROBOT", b)[1]
    for bad in (None, "invalid", 1):
        with pytest.raises(ValidationError):
            canonical_input(operation, "ROBOT", dict(a, candidateId=bad))
    with pytest.raises(ValidationError):
        canonical_input(operation, "ROBOT", {k:v for k,v in a.items() if k != "candidateId"})
    with pytest.raises(ValidationError):
        canonical_input(operation, "ROBOT", dict(a, webhook="secret"))
    result = dict(requestId=str(uuid4()), operationType=operation, inputSchemaVersion="1", target=None, input=a)
    assert TypeAdapter(RecoveryInputResponse).validate_python(result).input.candidateId == str(first)
    model = RobotTestCommand if operation == "ROBOT_TEST" else ConfirmCandidateCommand
    with pytest.raises(ValidationError):
        model.model_validate(dict(a, requestId=str(uuid4()), attemptId=str(uuid4())))


@pytest.mark.parametrize("operation", ["ROBOT_TEST", "ROBOT_CONFIRM"])
def test_register_expire_restore_original_and_reject_retarget(robot_database, operation):
    protocol, queries = WriteProtocol(POLICY), WriteRecoveryQueries(POLICY)
    with Session(robot_database) as s:
        first, second, foreign = candidate(s), candidate(s), candidate(s, owner=2)
        test = test_row(s, first)
        original = payload(operation, first["candidate_id"], test["test_id"])
        request, attempt = uuid4(), uuid4()
        args = dict(owner_id=1, request_id=request, attempt_id=attempt, scope=SCOPE,
            operation=operation, payload=original, now=NOW, executor_id="original", deadline=deadline())
        state = protocol.register(s, **args)
        assert state.execute
        assert not protocol.register(s, **args).execute
        # Retained JSON is safe and includes the original route, not secret data.
        row = s.get(WriteRequest, (1, request))
        assert row.input_payload == original and row.candidate_id is None
        other_test = test_row(s, second)
        with pytest.raises(WriteProtocolConflict, match="TA_REQUEST_ID_CONFLICT"):
            protocol.register(s, **dict(args, payload=payload(operation, second["candidate_id"], other_test["test_id"])))
        with pytest.raises(WriteProtocolConflict, match="TA_OBJECT_NOT_FOUND"):
            protocol.register(s, **dict(args, payload=payload(operation, foreign["candidate_id"], test["test_id"])))
        assert queries.pending(s, owner_id=1, scope=SCOPE, deadline=deadline()).pendingRequest.requestId == str(request)
        assert queries.pending(s, owner_id=2, scope=SCOPE, deadline=deadline()).pendingRequest is None
        before = s.scalar(select(func.count()).select_from(RobotTest))
        protocol.expire(s, owner_id=1, request_id=request, key="ROBOT", now=NOW+timedelta(seconds=16), deadline=deadline())
        restored = queries.recoverable_input(s, owner_id=1, request_id=request, deadline=deadline())
        assert restored.input.model_dump(mode="json") == original
        for _ in range(3):
            queries.status(s, owner_id=1, request_id=request, deadline=deadline())
            queries.recoverable_input(s, owner_id=1, request_id=request, deadline=deadline())
        assert s.scalar(select(func.count()).select_from(RobotTest)) == before
        assert s.scalar(select(func.count()).select_from(RobotConfig)) == 0
        with pytest.raises(WriteProtocolConflict, match="TA_RECOVERY_UNAVAILABLE"):
            queries.recoverable_input(s, owner_id=2, request_id=request, deadline=deadline())


def test_saved_unknown_test_receipt_replay_does_not_reopen_attempt(robot_database):
    protocol, queries = WriteProtocol(POLICY), WriteRecoveryQueries(POLICY)
    with Session(robot_database) as s:
        c = candidate(s)
        request, attempt = uuid4(), uuid4()
        args = dict(owner_id=1, request_id=request, attempt_id=attempt, scope=SCOPE,
            operation="ROBOT_TEST", payload=payload("ROBOT_TEST", c["candidate_id"]),
            now=NOW, executor_id="test", deadline=deadline())
        state = protocol.register(s, **args)
        t = test_row(s, c, "IN_FLIGHT")
        protocol.saved(s, protocol.lock_execution(s, state, now=NOW, executor_id="test", deadline=deadline()),
            dict(requestId=str(request), attemptId=str(attempt), operationType="ROBOT_TEST", acceptedAt=NOW.isoformat(),
                 result=dict(testId=str(t["test_id"]), state="IN_FLIGHT", startedAt=NOW.isoformat(), completedAt=None, reason=None)), NOW)
        row = s.get(RobotTest, t["test_id"])
        row.state, row.completed_at = "UNKNOWN", NOW + timedelta(seconds=10)
        s.flush()
        replay = protocol.register(s, **args)
        assert replay.status == "SAVED" and not replay.execute
        assert replay.receipt["result"]["testId"] == str(t["test_id"])
        assert s.scalar(select(func.count()).select_from(RobotTest)) == 1
        with pytest.raises(WriteProtocolConflict, match="TA_RECOVERY_STATE_CHANGED"):
            queries.recoverable_input(s, owner_id=1, request_id=request, deadline=deadline())


def test_official_recovery_api_returns_original_candidate_without_side_effects(robot_database):
    protocol = WriteProtocol(POLICY)
    with Session(robot_database) as s, s.begin():
        c = candidate(s)
        request, attempt = uuid4(), uuid4()
        protocol.register(s, owner_id=1, request_id=request, attempt_id=attempt, scope=SCOPE,
            operation="ROBOT_TEST", payload=payload("ROBOT_TEST", c["candidate_id"]), now=NOW,
            executor_id="gone", deadline=deadline())

    async def exercise():
        from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
        from src.biz.api.wealth.market.trading_assistant.router import create_trading_assistant_router
        engine = create_async_engine(robot_database.url)
        deps = build_trading_assistant_dependencies(engine, policy=POLICY, now=lambda:NOW, executor_id="api")
        owner = [1]
        async def auth(): return owner[0]
        app = FastAPI()
        app.include_router(create_trading_assistant_router(auth_dependency=auth, dependencies_dependency=lambda:deps))
        root = "/wealth/market/trading-assistant/write-requests"
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                pending = await client.get(root + "/pending", params=dict(scopeType="ROBOT"))
                assert pending.status_code == 200, pending.text
                assert pending.json()["pendingRequest"]["requestId"] == str(request)
                assert (await client.get(root + "/pending", params=dict(scopeType="ROBOT", ruleId=str(uuid4())))).status_code == 400
                with Session(robot_database) as s, s.begin():
                    protocol.expire(s, owner_id=1, request_id=request, key="ROBOT", now=NOW+timedelta(seconds=16), deadline=deadline())
                for _ in range(3):
                    result = await client.get(root + f"/{request}/input")
                    assert result.status_code == 200, result.text
                    assert result.json()["input"]["candidateId"] == str(c["candidate_id"])
                owner[0] = 2
                assert (await client.get(root + f"/{request}/input")).status_code == 404
                assert (await client.get(root + "/pending", params=dict(scopeType="ROBOT"))).json() == {"pendingRequest":None}
        finally:
            await engine.dispose()
    asyncio.run(exercise())
    with Session(robot_database) as s:
        assert s.scalar(select(func.count()).select_from(RobotTest)) == 0
