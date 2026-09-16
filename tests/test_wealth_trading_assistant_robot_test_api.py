"""Actual route, App dependency and isolated PostgreSQL; no external sending."""
import asyncio
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database
from tests.test_wealth_trading_assistant_rule_storage import rule_database, NOW
from tests.test_wealth_trading_assistant_robot_storage import robot_database, candidate, test_row
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.api.wealth.market.trading_assistant.router import create_trading_assistant_router
from src.biz.models.wealth.trading_assistant.robots import RobotTest
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1


def test_test_evidence_reads_are_owned_exact_and_side_effect_free(robot_database):
    with Session(robot_database) as s, s.begin():
        own, other_candidate, foreign = candidate(s), candidate(s), candidate(s, owner=2)
        rows = [(candidate(s), state) for state in ("IN_FLIGHT", "SUCCEEDED", "FAILED", "UNKNOWN")]
        tests = [(c, test_row(s, c, state)) for c, state in rows]
        wrong_test = test_row(s, own)
        foreign_test = test_row(s, foreign)
        before = [(r.test_id, r.state, r.completed_at) for r in s.scalars(select(RobotTest).order_by(RobotTest.test_id))]

    async def exercise():
        engine = create_async_engine(robot_database.url)
        policy = TradingAssistantExecutionPolicyV1()
        deps = build_trading_assistant_dependencies(engine, policy=policy, now=lambda: NOW, executor_id="test-api")
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(engine.sync_engine, "before_cursor_execute", capture)
        owner = [1]
        async def auth():
            return owner[0]
        app = FastAPI()
        app.include_router(create_trading_assistant_router(auth_dependency=auth, dependencies_dependency=lambda: deps))
        def path(c, t):
            return f"/wealth/market/trading-assistant/robot/candidates/{c}/tests/{t}"
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                for c, t in tests:
                    for _ in range(2):
                        result = await client.get(path(c["candidate_id"], t["test_id"]))
                        assert result.status_code == 200, result.text
                        body = result.json()
                        assert set(body) == {"testId", "state", "startedAt", "completedAt", "reason"}
                        assert body["state"] == t["state"] and body["testId"] == str(t["test_id"])
                        assert (body["completedAt"] is None) == (t["state"] == "IN_FLIGHT")
                        assert body["startedAt"] and body["reason"] == t["reason"]
                for c, t in ((other_candidate["candidate_id"], wrong_test["test_id"]),
                             (foreign["candidate_id"], foreign_test["test_id"]), (uuid4(), uuid4())):
                    assert (await client.get(path(c, t))).status_code == 404
                assert (await client.get(path("invalid", wrong_test["test_id"]))).status_code == 400
                owner[0] = 2
                assert (await client.get(path(own["candidate_id"], wrong_test["test_id"]))).status_code == 404
                assert (await client.get(path(foreign["candidate_id"], foreign_test["test_id"]))).status_code == 200
            # The real read runner sets transaction isolation before any SELECT.
            assert any("REPEATABLE READ" in q.upper() for q in statements)
            assert any("READ ONLY" in q.upper() for q in statements)
            assert not any(q.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in statements)
            assert not any("credential_blob" in q or "FOR UPDATE" in q.upper() for q in statements)
        finally:
            await engine.dispose()
    asyncio.run(exercise())
    with Session(robot_database) as s:
        assert [(r.test_id, r.state, r.completed_at) for r in s.scalars(select(RobotTest).order_by(RobotTest.test_id))] == before
