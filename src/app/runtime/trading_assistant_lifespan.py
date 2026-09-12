"""App-owned M2 resources; recovery maintenance never accepts user commands."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import create_async_engine

from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.recovery_maintenance import RecoveryMaintenance
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocol
from .trading_assistant_container import build_trading_assistant_dependencies


async def maintain_recovery(maintenance, policy, stop, logger):
    while not stop.is_set():
        try:
            count = await maintenance.sweep(deadline=Deadline.after_ms(policy.batch_budget_ms),
                cancelled=stop.is_set)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not log SQL parameters, retained inputs or private account facts.
            logger.warning("trading-assistant recovery maintenance did not complete")
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
async def trading_assistant_lifespan(app, *, database_url, logger):
    policy = TradingAssistantExecutionPolicyV1()
    # Same configured DB and pool defaults as src/db.py; the original pool is untouched.
    engine = create_async_engine(database_url, pool_pre_ping=True, pool_recycle=300, pool_use_lifo=True)
    now = lambda: datetime.now(timezone.utc)
    dependencies = build_trading_assistant_dependencies(engine, policy=policy, now=now, executor_id=str(uuid4()))
    maintenance = RecoveryMaintenance(dependencies.transactions, WriteProtocol(policy), policy, now)
    stop = asyncio.Event()
    app.state.trading_assistant = dependencies
    task = asyncio.create_task(maintain_recovery(maintenance, policy, stop, logger), name="ta-recovery-maintenance")
    logger.info("trading-assistant execution policy=v1 batch_ms=%s page_rows=%s lease_seconds=%s",
        policy.batch_budget_ms, policy.page_rows, policy.lease_seconds)
    try:
        yield
    finally:
        stop.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=policy.shutdown_grace_seconds)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        finally:
            del app.state.trading_assistant
            await engine.dispose()
