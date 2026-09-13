"""Coordinator fairness and cooperative stop; resource draining is separate."""
import asyncio
from unittest.mock import Mock

from src.biz.services.wealth.market.trading_assistant.calculation_loop import run_calculation_loop
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1


def test_every_scope_gets_one_turn_without_waiting_for_full_account_completion():
    async def run():
        stop, calls = asyncio.Event(), []
        async def unit(kind):
            calls.append(kind)
            if len(calls) == 7:
                stop.set()
            return "PREPARING"
        await run_calculation_loop(unit, policy=TradingAssistantExecutionPolicyV1(), stop=stop, logger=Mock())
        assert calls == ["CALCULATE", "CUTOFF", "HISTORY"]*2+["CALCULATE"]
    asyncio.run(run())


def test_idle_wait_is_interruptible_and_no_new_unit_starts_after_stop():
    async def run():
        stop, visited, calls = asyncio.Event(), asyncio.Event(), []
        async def unit(kind):
            calls.append(kind)
            if kind == "HISTORY":
                visited.set()
            return "IDLE"
        task = asyncio.create_task(run_calculation_loop(unit, policy=TradingAssistantExecutionPolicyV1(), stop=stop, logger=Mock()))
        await visited.wait()
        stop.set()
        await asyncio.wait_for(task, .1)
        assert calls == ["CALCULATE", "CUTOFF", "HISTORY"]
    asyncio.run(run())


def test_failure_and_broken_logging_do_not_starve_other_scopes():
    async def run():
        stop, calls = asyncio.Event(), []
        logger = Mock()
        logger.warning.side_effect = RuntimeError("unavailable log sink")
        async def unit(kind):
            calls.append(kind)
            if kind == "CALCULATE":
                raise RuntimeError("private account details")
            if kind == "HISTORY":
                stop.set()
            return "PREPARING"
        await run_calculation_loop(unit, policy=TradingAssistantExecutionPolicyV1(), stop=stop, logger=logger)
        assert calls == ["CALCULATE", "CUTOFF", "HISTORY"]
        logger.warning.assert_called_once_with("trading-assistant bounded execution unit did not complete: %s", "CALCULATE")
    asyncio.run(run())
