"""Deployment address and durable IO boundary tests; no external HTTP."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.app.runtime.trading_assistant_notifications import resolve_public_base_url, run_notifications
from src.biz.services.wealth.market.trading_assistant.message_dispatch import DurableMessageDispatcher
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.notification_policy import TradingAssistantNotificationPolicyV1
from src.biz.services.wealth.market.trading_assistant.feishu_protocol import SendOutcome
from src.biz.services.wealth.market.trading_assistant.feishu_protocol import FeishuInputError
from src.biz.services.wealth.market.trading_assistant.notification_dispatch import NotificationDispatcher


@pytest.mark.parametrize("value", ["", "http://wealth.example", "https://user:secret@wealth.example",
    "https://wealth.example/path", "https://wealth.example?x=1", "https://wealth.example#x",
    "https://wealth.example:99999", "https://wealth.example\n", "https://wealth.example\\x"])
def test_invalid_public_address_is_not_used(value):
    assert resolve_public_base_url(value) == ""


def test_public_origin_and_no_key_lifecycle():
    assert resolve_public_base_url("https://wealth.example/") == "https://wealth.example"
    async def exercise():
        # Missing key does not start either sender, even if called repeatedly.
        deps = SimpleNamespace(robot_commands=SimpleNamespace(store=SimpleNamespace(cipher=None)))
        await run_notifications(deps, stop=asyncio.Event(), logger=Mock())
    asyncio.run(exercise())


def test_missing_detail_address_refuses_payload_before_credentials_or_io():
    dispatcher = NotificationDispatcher(None, None, None, None, None, None)
    with pytest.raises(FeishuInputError):
        dispatcher._payload(None, None, None, None)


def test_result_storage_failure_never_repeats_io_and_shutdown_does_not_claim():
    async def exercise():
        class Transactions:
            async def run(self, fn, **kwargs): return fn(None)
        class Transport:
            calls = 0
            async def send(self, *args): self.calls += 1; return SendOutcome("SUCCEEDED", None)
        class Dispatcher(DurableMessageDispatcher):
            claimed = False
            swept = 0
            def _sweep(self, *args): self.swept += 1
            def _claim(self, *args):
                if self.claimed: return None
                self.claimed = True
                return "original", "token"
            def _payload(self, *args): return "private", {}
            def _finish(self, *args): raise RuntimeError("result write unavailable")
        transport = Transport()
        dispatcher = Dispatcher(Transactions(), None, transport, TradingAssistantExecutionPolicyV1(),
            TradingAssistantNotificationPolicyV1(), None)
        assert not await dispatcher.tick(cancelled=lambda:True) and dispatcher.swept == 0
        with pytest.raises(RuntimeError, match="result write"):
            await dispatcher.tick()
        assert not await dispatcher.tick() and transport.calls == 1
    asyncio.run(exercise())


def test_notification_loop_shutdown_waits_for_inflight_unit(monkeypatch):
    from src.app.runtime import trading_assistant_notifications as runtime
    async def exercise():
        entered, release, stop = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = []
        class TestSender:
            def __init__(self, *args, **kwargs): pass
            async def tick(self, **kwargs):
                calls.append("test")
                entered.set()
                await release.wait()
                return True
        class FormalSender:
            def __init__(self, *args, **kwargs): pass
            async def tick(self, **kwargs): calls.append("formal"); return False
        monkeypatch.setattr(runtime, "RobotTestDispatcher", TestSender)
        monkeypatch.setattr(runtime, "NotificationDispatcher", FormalSender)
        deps = SimpleNamespace(robot_commands=SimpleNamespace(store=SimpleNamespace(cipher=True)),
            transactions=None, policy=TradingAssistantExecutionPolicyV1(), now=None)
        task = asyncio.create_task(run_notifications(deps, stop=stop, logger=Mock(), transport=object(),
            public_base_url="https://wealth.example"))
        await asyncio.wait_for(entered.wait(), 1)
        stop.set()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        await asyncio.wait_for(task, 1)
        assert calls == ["test"]  # No new work after stop; no detached send task.
    asyncio.run(exercise())
