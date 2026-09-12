"""M2 process lifecycle uses an isolated database; no configured DB connections."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from starlette.datastructures import State

from tests.test_wealth_trading_assistant_persistence import database
from src.app.runtime.trading_assistant_lifespan import trading_assistant_lifespan, maintain_recovery
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1


def test_resources_exist_only_during_lifespan_and_loop_stops(database):
    async def run():
        app = SimpleNamespace(state=State())
        async with trading_assistant_lifespan(app, database_url=database.url, logger=Mock()):
            assert app.state.trading_assistant is not None
            result = await app.state.trading_assistant.read(
                lambda s,d:app.state.trading_assistant.account_queries.list(s, owner_id=1, deadline=d))
            assert result.items == []
            assert len([t for t in asyncio.all_tasks() if t.get_name() == "ta-recovery-maintenance"]) == 1
        assert not hasattr(app.state, "trading_assistant")
        assert not [t for t in asyncio.all_tasks() if t.get_name() == "ta-recovery-maintenance"]
    asyncio.run(run())


def test_maintenance_failure_does_not_kill_loop_and_shutdown_interrupts_idle_wait():
    async def run():
        stop, entered = asyncio.Event(), asyncio.Event()
        class FailingMaintenance:
            async def sweep(self, *, deadline, cancelled):
                assert deadline.remaining_ms() <= 2000 and not cancelled()
                entered.set()
                raise RuntimeError("private input must never reach log")
        logger = Mock()
        task = asyncio.create_task(maintain_recovery(FailingMaintenance(), TradingAssistantExecutionPolicyV1(), stop, logger))
        await entered.wait()
        stop.set()
        await asyncio.wait_for(task, .5)
        logger.warning.assert_called_once_with("trading-assistant recovery maintenance did not complete")
    asyncio.run(run())
