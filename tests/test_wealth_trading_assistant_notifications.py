"""Real configuration → minute result → notification attempts; offline IO only."""
import asyncio
from datetime import timedelta
from uuid import UUID, uuid4
from sqlalchemy import insert, select, func
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from tests.test_wealth_trading_assistant_rule_storage import rule_database, NOW
from tests.test_wealth_trading_assistant_robot_storage import robot_database, CIPHER
from tests.test_wealth_trading_assistant_rule_commands import plan
from tests.test_wealth_trading_assistant_rule_work import bars
from tests.wealth_trading_assistant_fixture_support import fixed_fixture_clock
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.clients.local_lake.stock_rule_minute_reader import StockRuleMinuteReader
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.api.wealth.market.trading_assistant.router import create_trading_assistant_router
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1, Deadline
from src.biz.services.wealth.market.trading_assistant.notification_policy import TradingAssistantNotificationPolicyV1
from src.biz.services.wealth.market.trading_assistant.feishu_protocol import SendOutcome
from src.biz.services.wealth.market.trading_assistant.robot_test_dispatch import RobotTestDispatcher
from src.biz.services.wealth.market.trading_assistant.notification_dispatch import NotificationDispatcher
from src.biz.services.wealth.market.trading_assistant.rule_work import RuleWork
from src.biz.models.wealth.trading_assistant.rule_notifications import TriggerNotification
from src.biz.models.wealth.trading_assistant.notification_attempts import NotificationAttempt
from src.biz.models.wealth.trading_assistant.rule_checks import RuleResult
from src.biz.models.wealth.trading_assistant.ledger import Ledger

def identity():
    return dict(requestId=str(uuid4()), attemptId=str(uuid4()))

def test_real_trigger_dispatch_retry_versions_owner_and_unknown(robot_database, tmp_path):
    with robot_database.begin() as conn:
        account, _, _ = seed_account(conn)
        conn.execute(insert(Security).values(ts_code="000001.SZ", name="平安银行", exchange="SZSE",
            security_type="EQUITY", curr_type="CNY", source="isolated-test"))
        conn.execute(insert(TradeCalendar).values(exchange="SSE", trade_date=NOW.date(),
            is_open=True, pretrade_date=NOW.date() - timedelta(days=1)))
    bars(tmp_path)
    async def exercise():
        engine = create_async_engine(robot_database.url)
        clock, owner = [NOW], [1]
        policy = TradingAssistantExecutionPolicyV1()
        deps = build_trading_assistant_dependencies(engine, policy=policy, now=lambda: clock[0],
            executor_id="notification-api", credential_cipher=CIPHER)
        class Offline:
            calls = []
            outcome = SendOutcome("SUCCEEDED", None, 0)
            crash = False
            async def send(self, webhook, payload):
                self.calls.append((webhook, payload))
                if self.crash:
                    raise RuntimeError("simulated sender exit")
                return self.outcome
        transport = Offline()
        tests = RobotTestDispatcher(deps.transactions, deps.robot_commands.store, transport, policy,
            TradingAssistantNotificationPolicyV1(), lambda: clock[0])
        sends = NotificationDispatcher(deps.transactions, deps.robot_commands.store, transport, policy,
            TradingAssistantNotificationPolicyV1(), lambda: clock[0], detail_base_url="https://wealth.example")
        app = FastAPI()
        async def auth(): return owner[0]
        app.include_router(create_trading_assistant_router(auth_dependency=auth, dependencies_dependency=lambda: deps))
        root = "/wealth/market/trading-assistant"
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                async def configure(previous=None):
                    clock[0] += timedelta(seconds=2)
                    body = dict(**identity(), name="新版" if previous else "首版", expectedConfigVersionId=previous,
                        webhook=dict(action="REPLACE", value="https://open.feishu.cn/open-apis/bot/v2/hook/isolated-notification"),
                        signingSecret=dict(action="CLEAR"), keywords=["隔离验收"])
                    c = await client.post(root + "/robot/candidates", json=body)
                    assert c.status_code == 200, c.text
                    candidate = c.json()["result"]["candidateId"]
                    t = await client.post(root + f"/robot/candidates/{candidate}/tests", json=dict(**identity(), expectedCandidateVersion="1"))
                    assert t.status_code == 202, t.text
                    transport.outcome = SendOutcome("SUCCEEDED", None, 0)
                    assert await tests.tick()
                    saved = await client.post(root + f"/robot/candidates/{candidate}/confirmations", json=dict(
                        **identity(), expectedConfigVersionId=previous, testId=t.json()["result"]["testId"], receivedConfirmed=True))
                    assert saved.status_code == 200, saved.text
                    return saved.json()["result"]
                config = await configure()
                created = await client.post(root + "/plans", json=plan(account, notifyEnabled=True,
                    robotId=config["robotId"]).model_dump(mode="json", exclude_unset=True))
                assert created.status_code == 201, created.text
                rule_id = created.json()["result"]["ruleId"]
                clock[0] = NOW + timedelta(hours=6)
                with fixed_fixture_clock(robot_database, clock):
                    work = RuleWork(policy, sessionmaker(robot_database, expire_on_commit=False),
                        minute_reader=StockRuleMinuteReader(tmp_path))
                    for _ in range(12):
                        work.run_once(executor_id="notification-rule")
                        with Session(robot_database) as s:
                            n = s.scalar(select(TriggerNotification).where(TriggerNotification.rule_id == UUID(rule_id)))
                            if n:
                                notification_id, trigger_id = str(n.notification_id), n.trigger_id
                                break
                    else:
                        raise AssertionError("No real trigger notification published")
                path = root + "/notifications/" + notification_id
                before = await client.get(path)
                assert before.status_code == 200, before.text
                assert before.json()["state"] == "PENDING" and not before.json()["items"]
                transport.outcome = SendOutcome("FAILED", "机器人拒绝了消息", 19024)
                other_sender = NotificationDispatcher(deps.transactions, deps.robot_commands.store, transport, policy,
                    TradingAssistantNotificationPolicyV1(), lambda: clock[0], detail_base_url="https://wealth.example")
                assert sorted(await asyncio.gather(sends.tick(), other_sender.tick())) == [False, True]
                assert not await sends.tick()  # no automatic retry
                failed = (await client.get(path)).json()
                assert failed["canRetry"] and failed["items"][0]["attemptNo"] == 1
                newer = await configure(config["configVersionId"])
                retry = dict(**identity(), expectedStateVersion=failed["stateVersion"])
                accepted = await client.post(path + "/retry", json=retry)
                assert accepted.status_code == 202, accepted.text
                assert (await client.post(path + "/retry", json=retry)).json() == accepted.json()
                assert (await client.post(path + "/retry", json=dict(**identity(), expectedStateVersion=failed["stateVersion"]))).status_code == 409
                pending = await client.get(root + "/write-requests/pending", params=dict(scopeType="NOTIFICATION", notificationId=notification_id))
                assert pending.status_code == 200, pending.text
                clock[0] += timedelta(seconds=2)
                transport.crash = True
                try:
                    await sends.tick()
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("Expected interrupted sender")
                calls = len(transport.calls)
                clock[0] += timedelta(seconds=11)
                assert not await sends.tick()
                unknown = (await client.get(path, params=dict(limit=1))).json()
                assert unknown["state"] == "UNKNOWN" and not unknown["canRetry"]
                assert unknown["items"][0]["robotConfigVersionId"] == newer["configVersionId"]
                assert unknown["nextCursor"] and len(transport.calls) == calls
                older = (await client.get(path, params=dict(limit=1, cursor=unknown["nextCursor"]))).json()
                assert older["items"][0]["robotConfigVersionId"] == config["configVersionId"]
                assert (await client.post(path + "/retry", json=dict(**identity(), expectedStateVersion=unknown["stateVersion"]))).status_code == 409
                owner[0] = 2
                assert (await client.get(path)).status_code == 404
                assert (await client.post(path + "/retry", json=dict(**identity(), expectedStateVersion=unknown["stateVersion"]))).status_code == 404
                owner[0] = 1
                with Session(robot_database) as s:
                    attempt = s.scalar(select(NotificationAttempt).where(NotificationAttempt.notification_id == UUID(notification_id), NotificationAttempt.attempt_no == 2))
                    attempt_id, token = attempt.attempt_id, attempt.dispatch_token
                    assert attempt.outcome == "UNKNOWN"
                    assert "盘后验证" in attempt.business_content and "不代表实际成交" in attempt.business_content
                    assert "截止时间：" in attempt.business_content and "盘后检查时间：" in attempt.business_content
                    assert "https://wealth.example/wealth/market/trading-assistant?ruleType=PLAN&ruleId=" in attempt.business_content
                    assert "open.feishu" not in attempt.business_content
                deadline = Deadline.after_ms(2000)
                await deps.transactions.run(lambda s: sends._finish(s, attempt_id, token, SendOutcome("SUCCEEDED", None, 0), deadline), deadline=deadline, write=True)
                assert (await client.get(path)).json()["state"] == "SUCCEEDED"
                with Session(robot_database) as s:
                    assert s.scalar(select(func.count()).select_from(RuleResult).where(RuleResult.result_id == trigger_id)) == 1
                    assert s.scalar(select(func.count()).select_from(Ledger).where(Ledger.account_id == account)) == 0
                    attempt = s.get(NotificationAttempt, attempt_id)
                    assert [x["state"] for x in attempt.result_history] == ["UNKNOWN", "SUCCEEDED"]
        finally:
            await engine.dispose()
    asyncio.run(exercise())
