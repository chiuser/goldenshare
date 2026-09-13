"""One TA-owned thread with deadline-aware, thread-local database resources.

Neither request Sessions nor pooled HTTP connections enter this resource.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

from src.biz.services.wealth.market.trading_assistant.calculation_work import CalculationWork
from src.biz.services.wealth.market.trading_assistant.cutoff_discovery import CutoffDiscovery
from src.biz.services.wealth.market.trading_assistant.cutoff_preparation import AccountCutoffPreparation
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import RecalculationExecution


class TradingAssistantExecutionResource:
    def __init__(self, database_url, policy, *, rule_version):
        self.database_url, self.policy, self.rule_version = database_url, policy, rule_version
        self.executor_id = str(uuid4())
        self._executor = ThreadPoolExecutor(max_workers=policy.local_concurrency, thread_name_prefix="ta-calculation")
        self._runner = self._engine = self._active = None
        self._closing = self._closed = False
        self._close_task = None
        self._worker = None

    async def run_one(self, kind):
        if kind not in ("SCHEMA", "CALCULATE", "CUTOFF", "HISTORY"):
            raise ValueError("Unknown TA execution unit")
        if self._closing:
            raise RuntimeError("TA execution resource is closing")
        if self._active is not None and not self._active.done():
            raise RuntimeError("TA execution resource already has an in-flight unit")
        self._active = asyncio.get_running_loop().run_in_executor(self._executor, self._run, kind)
        # Cancelling a coordinator must not cancel this bookkeeping Future and
        # pretend the underlying thread has returned.
        return await asyncio.shield(self._active)

    def _run(self, kind):
        if self._runner is None:
            self._runner = asyncio.Runner()
        return self._runner.run(self._execute(kind))

    async def _execute(self, kind):
        self._worker = None
        if self._engine is None:
            self._engine = create_async_engine(self.database_url, pool_pre_ping=True,
                pool_size=self.policy.local_concurrency, max_overflow=0,
                pool_timeout=self.policy.batch_budget_ms/1000)
        # Includes pool acquisition, initial connection, all short transactions
        # and source reads. Interrupted commits remain uncertain, not "unsaved".
        try:
            async with asyncio.timeout(self.policy.batch_budget_ms/1000):
                async with self._engine.connect() as connection:
                    return await connection.run_sync(lambda sync: self._unit(
                        sessionmaker(bind=sync, expire_on_commit=False), kind))
        except TimeoutError as error:
            if self._worker is None:
                raise
            # The failed connection has exited. Only recovery bookkeeping gets
            # a separate bounded transaction; no extra calculation is started.
            async with asyncio.timeout(self.policy.batch_budget_ms/1000):
                async with self._engine.connect() as connection:
                    return await connection.run_sync(lambda sync: self._worker.record_failure(
                        error, sessions=sessionmaker(bind=sync, expire_on_commit=False)))

    def _unit(self, sessions, kind):
        if kind == "SCHEMA":
            from .trading_assistant_execution_schema import verify_execution_schema
            return verify_execution_schema(sessions, self.policy)
        if kind != "CALCULATE":
            self._worker = CutoffDiscovery(self.policy, sessions, purpose=kind)
            return self._worker.run_once()
        execution = RecalculationExecution(self.policy)
        self._worker = CalculationWork(execution, sessions, rule_version=self.rule_version,
            resolve_through_date=AccountCutoffPreparation(self.policy).resolve)
        return self._worker.run_once(executor_id=self.executor_id)

    async def close(self):
        if self._closed:
            return
        self._closing = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._finish_close())
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await asyncio.shield(self._close_task)
            raise

    async def _finish_close(self):
        if self._active is not None:
            try:
                await asyncio.shield(self._active)
            except Exception:
                # The unit failed but has really returned; its durable state
                # remains the authority. Cleanup must still run on its thread.
                pass
        try:
            await asyncio.get_running_loop().run_in_executor(self._executor, self._close_on_thread)
        finally:
            self._executor.shutdown(wait=True)
            self._closed = True

    def _close_on_thread(self):
        if self._runner is not None:
            try:
                if self._engine is not None:
                    self._runner.run(self._engine.dispose())
            finally:
                self._runner.close()
