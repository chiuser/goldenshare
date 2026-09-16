"""Two real processes share the DB claim and robot throttle, without HTTP."""
import asyncio
from datetime import timedelta
import multiprocessing
from uuid import uuid4
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from tests.test_wealth_trading_assistant_persistence import database
from tests.test_wealth_trading_assistant_rule_storage import rule_database, NOW
from tests.test_wealth_trading_assistant_robot_storage import robot_database, CIPHER
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.schemas.wealth.market.trading_assistant.robot import CandidateCommand, TestCandidateCommand as RobotTestCommand
from src.biz.models.wealth.trading_assistant.robots import RobotTest
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.notification_policy import TradingAssistantNotificationPolicyV1
from src.biz.services.wealth.market.trading_assistant.robot_test_dispatch import RobotTestDispatcher
from src.biz.services.wealth.market.trading_assistant.feishu_protocol import SendOutcome


def competing_sender(url, gate, results, seconds):
    async def run():
        engine = create_async_engine(url)
        policy = TradingAssistantExecutionPolicyV1()
        deps = build_trading_assistant_dependencies(engine, policy=policy,
            now=lambda: NOW + timedelta(seconds=seconds), executor_id=str(uuid4()), credential_cipher=CIPHER)
        class Offline:
            calls = 0
            async def send(self, *args):
                self.calls += 1
                return SendOutcome("SUCCEEDED", None)
        transport = Offline()
        try:
            dispatcher = RobotTestDispatcher(deps.transactions, deps.robot_commands.store, transport,
                policy, TradingAssistantNotificationPolicyV1(), deps.now)
            gate.wait(timeout=20)
            results.put((await dispatcher.tick(), transport.calls))
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_cross_process_claim_and_shared_interval(robot_database):
    async def prepare():
        engine = create_async_engine(robot_database.url)
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(),
            now=lambda: NOW, executor_id="prepare", credential_cipher=CIPHER)
        try:
            for i in range(2):
                receipt = await deps.robot_commands.create(owner_id=1, command=CandidateCommand(
                    requestId=str(uuid4()), attemptId=str(uuid4()), name=f"测试{i}", expectedConfigVersionId=None,
                    webhook=dict(action="REPLACE",value="https://open.feishu.cn/open-apis/bot/v2/hook/isolated-race"),
                    signingSecret=dict(action="CLEAR"), keywords=[]))
                from uuid import UUID
                await deps.robot_commands.test(owner_id=1, candidate_id=UUID(receipt.result.candidateId),
                    command=RobotTestCommand(requestId=str(uuid4()), attemptId=str(uuid4()), expectedCandidateVersion="1"))
        finally:
            await engine.dispose()
    asyncio.run(prepare())
    context = multiprocessing.get_context("spawn")
    for second, expected in [(0, [(False, 0), (True, 1)]), (0, [(False, 0), (False, 0)]),
                             (2, [(False, 0), (True, 1)])]:
        gate, results = context.Barrier(2), context.Queue()
        processes = [context.Process(target=competing_sender,
            args=(str(robot_database.url), gate, results, second)) for _ in range(2)]
        try:
            for process in processes: process.start()
            for process in processes:
                process.join(timeout=30)
                assert process.exitcode == 0
            assert sorted([results.get(timeout=2), results.get(timeout=2)]) == expected
        finally:
            for process in processes:
                if process.is_alive(): process.terminate(); process.join(timeout=5)
            results.close(); results.join_thread()
    with Session(robot_database) as session:
        assert session.scalar(select(func.count()).select_from(RobotTest).where(RobotTest.state == "SUCCEEDED")) == 2
