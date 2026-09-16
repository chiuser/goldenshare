"""App-owned TA resources; recovery and M3 execution have separate lifecycles."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.recovery_maintenance import RecoveryMaintenance
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocol
from src.biz.services.wealth.market.trading_assistant.calculation import CALCULATION_RULE_VERSION
from src.biz.services.wealth.market.trading_assistant.calculation_loop import run_calculation_loop
from .trading_assistant_container import build_trading_assistant_dependencies
from .trading_assistant_execution_resource import TradingAssistantExecutionResource
from .trading_assistant_credentials import load_credential_cipher
from .trading_assistant_notifications import run_notifications
from src.foundation.config.local_minute_capability import resolve_local_minute_capability
from src.foundation.config.settings import get_settings
from src.foundation.clients.local_lake.stock_rule_minute_reader import StockRuleMinuteReader


def _log(logger, level, message, *args):
    try:
        getattr(logger, level)(message, *args)
    except Exception:
        pass


async def maintain_recovery(maintenance, policy, stop, logger):
    while not stop.is_set():
        try:
            count = await maintenance.sweep(deadline=Deadline.after_ms(policy.batch_budget_ms),
                cancelled=stop.is_set)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not log SQL parameters, retained inputs or private account facts.
            _log(logger, "warning", "trading-assistant recovery maintenance did not complete")
            count = 0
        if stop.is_set():
            return
        if count:
            await asyncio.sleep(0)
        else:
            try:
                await asyncio.wait_for(stop.wait(), timeout=policy.idle_poll_seconds)
            except TimeoutError:
                pass


@asynccontextmanager
async def trading_assistant_lifespan(app, *, database_url, logger, minute_reader=None, rule_robots=None):
    policy = TradingAssistantExecutionPolicyV1()
    credential_cipher = load_credential_cipher(get_settings().wealth_ta_credential_key_file)
    if minute_reader is None:
        capability = resolve_local_minute_capability(get_settings())
        if capability.enabled:
            if capability.lake_root != Path("/Volumes/datasource/data_lake"):
                raise RuntimeError("Trading-assistant minutes require the formal Lake root")
            minute_reader = StockRuleMinuteReader(capability.lake_root)
    # Resolve the source before allocating resources, including on invalid configuration.
    # Same configured DB and pool defaults as src/db.py; the original pool is untouched.
    engine = create_async_engine(database_url, pool_pre_ping=True, pool_recycle=300, pool_use_lifo=True)
    resource = TradingAssistantExecutionResource(database_url, policy,
        rule_version=CALCULATION_RULE_VERSION, minute_reader=minute_reader)
    stop = asyncio.Event()
    tasks, dependencies = [], None
    try:
        if await resource.run_one("SCHEMA") != "READY":
            raise RuntimeError("Trading-assistant execution schema is not ready")
        now = lambda: datetime.now(timezone.utc)
        dependencies = build_trading_assistant_dependencies(engine, policy=policy, now=now, executor_id=str(uuid4()),
            rule_robots=rule_robots, credential_cipher=credential_cipher)
        maintenance = RecoveryMaintenance(dependencies.transactions, WriteProtocol(policy), policy, now)
        app.state.trading_assistant = dependencies
        tasks = [asyncio.create_task(maintain_recovery(maintenance, policy, stop, logger), name="ta-recovery-maintenance"),
            asyncio.create_task(run_calculation_loop(resource.run_one, policy=policy, stop=stop, logger=logger),
                name="ta-calculation-coordinator"),
            asyncio.create_task(run_notifications(dependencies, stop=stop, logger=logger,
                public_base_url=get_settings().wealth_public_base_url), name="ta-notifications")]
        _log(logger, "info", "trading-assistant execution policy=v1 rule_version=%s batch_ms=%s page_rows=%s lease_seconds=%s",
            CALCULATION_RULE_VERSION, policy.batch_budget_ms, policy.page_rows, policy.lease_seconds)
        yield
    finally:
        stop.set()
        cleanup = asyncio.create_task(_stop_execution(tasks, resource, policy, logger))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await asyncio.shield(cleanup)
            raise
        finally:
            if dependencies is not None:
                del app.state.trading_assistant
            await engine.dispose()


async def _stop_execution(tasks, resource, policy, logger):
    if tasks:
        done = asyncio.gather(*tasks, return_exceptions=True)
        try:
            results = await asyncio.wait_for(asyncio.shield(done), timeout=policy.shutdown_grace_seconds)
        except TimeoutError:
            _log(logger, "warning", "trading-assistant shutdown exceeded grace; waiting for actual unit exit")
            results = await done
        if any(isinstance(result, BaseException) for result in results):
            _log(logger, "warning", "trading-assistant coordinator exited with an error")
    await resource.close()
