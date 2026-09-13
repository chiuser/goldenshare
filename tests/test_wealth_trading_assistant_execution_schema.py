"""Fail closed on an old isolated schema without migration or background work."""
import asyncio
from threading import enumerate as threads
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from starlette.datastructures import State

from tests.test_wealth_trading_assistant_persistence import database
from src.app.runtime.trading_assistant_lifespan import trading_assistant_lifespan


def test_old_schema_refuses_startup_and_releases_resources(database):
    async def run():
        app = SimpleNamespace(state=State())
        with pytest.raises(ProgrammingError):
            async with trading_assistant_lifespan(app, database_url=database.url, logger=Mock()):
                pytest.fail("Missing M3 schema must not start the App resources")
        assert not hasattr(app.state, "trading_assistant")
        assert not [t for t in asyncio.all_tasks() if t.get_name().startswith("ta-")]
        assert not [t for t in threads() if t.name.startswith("ta-calculation")]
    asyncio.run(run())
    with database.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('app.wealth_ta_cutoff_preparation')")) is None
        assert connection.scalar(text("SELECT count(*) FROM app.wealth_ta_account")) == 0
