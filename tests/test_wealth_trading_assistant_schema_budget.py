"""Startup-only budget wiring; no database, sockets or background workers."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from src.app.runtime.trading_assistant_execution_resource import TradingAssistantExecutionResource
from src.app.runtime.trading_assistant_execution_schema import verify_execution_schema
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1


@pytest.mark.parametrize("kind,seconds", [("SCHEMA", 3), ("CALCULATE", 2), ("CUTOFF", 2), ("HISTORY", 2)])
def test_only_schema_uses_three_second_outer_budget(kind, seconds):
    seen = []

    @asynccontextmanager
    async def timeout(value):
        seen.append(value)
        yield

    class Connection:
        async def run_sync(self, work):
            return "READY"

    class Engine:
        @asynccontextmanager
        async def connect(self):
            yield Connection()

    async def run():
        resource = TradingAssistantExecutionResource("unused", TradingAssistantExecutionPolicyV1(), rule_version=1)
        resource._engine = Engine()
        try:
            with patch("src.app.runtime.trading_assistant_execution_resource.asyncio.timeout", timeout):
                assert await resource._execute(kind) == "READY"
        finally:
            # _execute is called directly: no worker thread or real engine was started.
            resource._executor.shutdown(wait=True)

    asyncio.run(run())
    assert seen == [seconds]


def test_schema_internal_deadline_uses_same_budget():
    session = MagicMock()
    session.scalars.return_value = (1, 2)
    sessions = MagicMock()
    sessions.return_value.__enter__.return_value = session
    with patch("src.app.runtime.trading_assistant_execution_schema.Deadline.after_ms") as deadline:
        assert verify_execution_schema(sessions, TradingAssistantExecutionPolicyV1()) == "READY"
        deadline.assert_called_once_with(3000)


@pytest.mark.parametrize("value", [0, -1, True])
def test_invalid_schema_budget_rejected(value):
    with pytest.raises(ValueError):
        replace(TradingAssistantExecutionPolicyV1(), schema_check_budget_ms=value)
