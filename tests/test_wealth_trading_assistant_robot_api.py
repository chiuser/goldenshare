"""Real robot HTTP/transactions/dispatch with an offline transport only."""
import asyncio
import pytest
from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database
from tests.test_wealth_trading_assistant_rule_storage import rule_database, NOW
from tests.test_wealth_trading_assistant_robot_storage import robot_database, CIPHER
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.api.wealth.market.trading_assistant.router import create_trading_assistant_router
from src.biz.models.wealth.trading_assistant.robots import RobotCandidate, RobotTest, RobotConfig
from src.biz.models.wealth.trading_assistant.recovery import WriteRequest
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.notification_policy import TradingAssistantNotificationPolicyV1
from src.biz.services.wealth.market.trading_assistant.robot_test_dispatch import RobotTestDispatcher
from src.biz.services.wealth.market.trading_assistant.feishu_protocol import SendOutcome


def identity():
    return dict(requestId=str(uuid4()), attemptId=str(uuid4()))


def test_robot_configuration_test_confirmation_and_no_save_recovery(robot_database):
    async def exercise():
        engine = create_async_engine(robot_database.url)
        clock, owner = [NOW], [1]
        policy = TradingAssistantExecutionPolicyV1()
        deps = build_trading_assistant_dependencies(engine, policy=policy, now=lambda: clock[0],
            executor_id="robot-api", credential_cipher=CIPHER)
        class OfflineTransport:
            calls = 0
            outcome = SendOutcome("SUCCEEDED", None)
            async def send(self, webhook, payload):
                self.calls += 1
                assert webhook.endswith("isolated-private")
                # An independent transaction sees the claim before IO.
                with Session(robot_database) as s:
                    assert s.scalar(select(func.count()).select_from(RobotTest).where(
                        RobotTest.dispatch_token.is_not(None))) >= self.calls
                return self.outcome
        transport = OfflineTransport()
        dispatcher = RobotTestDispatcher(deps.transactions, deps.robot_commands.store, transport,
            policy, TradingAssistantNotificationPolicyV1(), lambda: clock[0])
        async def auth(): return owner[0]
        app = FastAPI()
        app.include_router(create_trading_assistant_router(auth_dependency=auth, dependencies_dependency=lambda: deps))
        root = "/wealth/market/trading-assistant"
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                assert (await client.get(root + "/robot")).json() == {"robot": None}
                body = dict(**identity(), expectedConfigVersionId=None, name="私有机器人", keywords=["财势乾坤"],
                    webhook=dict(action="REPLACE", value="https://open.feishu.cn/open-apis/bot/v2/hook/isolated-private"),
                    signingSecret=dict(action="REPLACE", value="isolated-signature"))
                first = await client.post(root + "/robot/candidates", json=body)
                assert first.status_code == 200, first.text
                c = first.json()["result"]["candidateId"]
                assert "isolated-private" not in first.text and "isolated-signature" not in first.text
                assert (await client.post(root + "/robot/candidates", json=body)).json() == first.json()
                assert (await client.post(root + "/robot/candidates", json=dict(body, name="改变"))).status_code == 409
                assert (await client.get(root + "/robot")).json()["robot"] is None
                assert (await client.get(root + "/write-requests/pending", params=dict(scopeType="ROBOT"))).status_code == 400
                test_body = dict(**identity(), expectedCandidateVersion="1")
                accepted = await client.post(root + f"/robot/candidates/{c}/tests", json=test_body)
                assert accepted.status_code == 202, accepted.text
                t = accepted.json()["result"]["testId"]
                confirmation = dict(**identity(), expectedConfigVersionId=None, testId=t, receivedConfirmed=True)
                assert (await client.post(root + f"/robot/candidates/{c}/confirmations", json=confirmation)).status_code == 409
                class RollbackClaim:
                    async def run(self, work, **kwargs):
                        def fail_after_claim(session):
                            value = work(session)
                            if isinstance(value, tuple):
                                raise RuntimeError("simulated claim commit failure")
                            return value
                        return await deps.transactions.run(fail_after_claim, **kwargs)
                broken = RobotTestDispatcher(RollbackClaim(), deps.robot_commands.store, transport,
                    policy, TradingAssistantNotificationPolicyV1(), lambda: clock[0])
                with pytest.raises(RuntimeError, match="claim commit failure"):
                    await broken.tick()
                assert transport.calls == 0
                with Session(robot_database) as s:
                    assert s.get(RobotTest, t).dispatch_token is None
                competitor = RobotTestDispatcher(deps.transactions, deps.robot_commands.store, transport,
                    policy, TradingAssistantNotificationPolicyV1(), lambda: clock[0])
                assert sorted(await asyncio.gather(dispatcher.tick(), competitor.tick())) == [False, True]
                assert not await dispatcher.tick()
                result = await client.get(root + f"/robot/candidates/{c}/tests/{t}")
                assert result.json()["state"] == "SUCCEEDED"
                assert (await client.post(root + f"/robot/candidates/{c}/tests", json=test_body)).json() == accepted.json()
                saved = await client.post(root + f"/robot/candidates/{c}/confirmations", json=confirmation)
                assert saved.status_code == 200, saved.text
                assert (await client.post(root + f"/robot/candidates/{c}/confirmations", json=confirmation)).json() == saved.json()
                current = (await client.get(root + "/robot")).json()["robot"]
                assert current == saved.json()["result"] and current["hasSigningSecret"]
                owner[0] = 2
                assert (await client.get(root + "/robot")).json() == {"robot": None}
                assert (await client.post(root + f"/robot/candidates/{c}/tests", json=test_body)).status_code == 404
                owner[0] = 1
                second = dict(body, **identity(), expectedConfigVersionId=current["configVersionId"],
                    signingSecret=dict(action="CLEAR"))
                c2 = (await client.post(root + "/robot/candidates", json=second)).json()["result"]["candidateId"]
                t2_body = dict(**identity(), expectedCandidateVersion="1")
                t2 = (await client.post(root + f"/robot/candidates/{c2}/tests", json=t2_body)).json()["result"]["testId"]
                assert not await competitor.tick() and transport.calls == 1
                clock[0] += timedelta(seconds=2)
                transport.outcome = SendOutcome("UNKNOWN", "发送结果待核对，不会自动重发")
                assert await dispatcher.tick()
                assert (await client.get(root + f"/robot/candidates/{c2}/tests/{t2}")).json()["state"] == "UNKNOWN"
                assert (await client.post(root + f"/robot/candidates/{c2}/tests", json=dict(**identity(), expectedCandidateVersion="1"))).status_code == 409
                assert not await dispatcher.tick() and transport.calls == 2
                assert (await client.get(root + "/robot")).json()["robot"] == current
                with Session(robot_database) as s:
                    assert s.scalar(select(func.count()).select_from(WriteRequest)) == 0
                    assert s.scalar(select(func.count()).select_from(RobotCandidate)) == 2
                    assert s.scalar(select(func.count()).select_from(RobotConfig)) == 1
        finally:
            await engine.dispose()
    asyncio.run(exercise())
