"""Request-owned read-only database resources, next-stage LLD 14.9.2.

No route registration, business rules, writes, pool or background execution.
"""
import asyncio
import math
import sys
import time

import psycopg
from sqlalchemy import Select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from src.foundation.config.settings import get_settings
from src.biz.queries.wealth.market.index_detail_daily_wave.query import DailyWaveSourceError
from src.biz.services.wealth.market.index_detail_daily_wave.budget import (
    DailyWaveBudgetExceeded,
)


class DailyWaveReadSession:
    def __init__(self, *, budget, database_url=None):
        self.budget = budget
        self.database_url = database_url
        self.engine = self.connection = self.session = self.transaction = self.raw = None
        self.aborting = self.closed = False
        self._task = None

    async def _creator(self):
        args, kwargs = self.engine.sync_engine.dialect.create_connect_args(self._url)
        kwargs["connect_timeout"] = max(1, math.ceil(self.budget.spec.connection_seconds))
        options = kwargs.get("options", "")
        kwargs["options"] = (
            options + " -c default_transaction_read_only=on"
            f" -c statement_timeout={int(self.budget.spec.query_seconds * 1000)}"
            f" -c lock_timeout={int(self.budget.spec.lock_seconds * 1000)}"
        ).strip()
        raw = await psycopg.AsyncConnection.connect(*args, **kwargs)
        # No yield between checking owner state and registering this handle.
        if self.aborting or self.closed:
            await raw.close()
            raise asyncio.CancelledError()
        self.raw = raw
        return raw

    async def _drain(self, task):
        if task is None:
            return
        if not task.done():
            task.cancel()
            done, _ = await asyncio.wait(
                {task}, timeout=max(0, self.budget.deadline - time.monotonic()))
            if not done:
                raise DailyWaveBudgetExceeded("连接任务未在总时限内清理完毕")
        try:
            task.result()
        except BaseException:
            pass  # The original operation error remains the caller's error.

    async def _abort(self, task=None):
        self.aborting = True
        if self.raw is not None:
            # Direct unpooled psycopg close calls pgconn.finish, not network rollback.
            await self.raw.close()
        await self._drain(task)

    async def await_read_io(self, awaitable, operation_deadline):
        task = asyncio.ensure_future(awaitable)
        self._task = task
        try:
            while True:
                self.budget.check()
                remaining = operation_deadline - time.monotonic()
                if remaining <= 0:
                    raise DailyWaveBudgetExceeded("本次连接或SQL超过时限")
                done, _ = await asyncio.wait({task}, timeout=min(0.05, remaining))
                if done:
                    result = task.result()
                    self.budget.check()
                    return result
        except BaseException:
            await self._abort(task)
            raise
        finally:
            self._task = None

    def _sql_deadline(self):
        return min(self.budget.read_deadline,
                   time.monotonic() + self.budget.spec.query_seconds)

    async def __aenter__(self):
        try:
            self.budget.check()
            try:
                self._url = make_url(self.database_url or get_settings().database_url)
            except ArgumentError:
                raise DailyWaveSourceError("日线只读连接配置无效") from None
            if self._url.drivername != "postgresql+psycopg":
                raise DailyWaveSourceError("日线只读连接要求postgresql+psycopg配置")
            self.engine = create_async_engine(
                self._url, async_creator=self._creator, poolclass=NullPool,
                echo=False, hide_parameters=True,
            )
            self.connection = await self.await_read_io(
                self.engine.connect(), min(self.budget.read_deadline,
                    time.monotonic() + self.budget.spec.connection_seconds))
            await self.await_read_io(self.connection.execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True), self._sql_deadline())
            self.transaction = await self.await_read_io(
                self.connection.begin(), self._sql_deadline())
            self.session = AsyncSession(
                bind=self.connection, autoflush=False, expire_on_commit=False,
                join_transaction_mode="rollback_only")
            return self
        except BaseException:
            await self.__aexit__(*sys.exc_info())
            raise

    async def _execute(self, statement, parameters=None):
        result = await self.session.execute(statement, parameters)
        return tuple(dict(row) for row in result.mappings().all())

    async def execute_read(self, statement, parameters=None):
        if self.aborting or self.closed or self.session is None:
            raise DailyWaveSourceError("本次只读会话已关闭")
        if self._task is not None:
            raise DailyWaveSourceError("同一次只读会话不允许并发SQL")
        if not isinstance(statement, Select):
            raise DailyWaveSourceError("日线查询只允许SELECT")
        remaining_ms = self.budget.remaining_ms()
        if remaining_ms < 2:
            raise DailyWaveBudgetExceeded("剩余查询时间不足")
        statement_ms = min(int(self.budget.spec.query_seconds * 1000), remaining_ms)
        lock_ms = min(int(self.budget.spec.lock_seconds * 1000), statement_ms - 1)
        try:
            await self.await_read_io(self._execute(text(
                "SELECT set_config('statement_timeout', :statement_ms, true), "
                "set_config('lock_timeout', :lock_ms, true)"),
                {"statement_ms": str(statement_ms), "lock_ms": str(lock_ms)}), self._sql_deadline())
            return await self.await_read_io(self._execute(statement, parameters), self._sql_deadline())
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) in {"57014", "55P03"}:
                raise DailyWaveBudgetExceeded("数据库查询或锁等待超过时限") from exc
            raise

    async def _release(self, awaitable):
        task = asyncio.ensure_future(awaitable)
        done, _ = await asyncio.wait({task}, timeout=max(0, self.budget.deadline - time.monotonic()))
        if not done:
            await self._abort(task)
            raise DailyWaveBudgetExceeded("资源清理超过总时限")
        return task.result()

    async def __aexit__(self, exc_type, exc, traceback):
        if self.closed:
            return False
        try:
            if exc_type is not None or self.aborting:
                await self._abort(self._task)
            elif self.transaction is not None and self.transaction.is_active:
                await self.await_read_io(self.transaction.rollback(), self.budget.deadline)
            if self.aborting and self.connection is not None:
                await self._release(self.connection.invalidate())
            if self.session is not None:
                await self._release(self.session.close())
            if self.connection is not None:
                await self._release(self.connection.close())
        finally:
            try:
                if self.raw is not None:
                    await self.raw.close()
                if self.engine is not None:
                    await self._release(self.engine.dispose())
            finally:
                self.closed = True
        return False


def daily_wave_session_factory(*, budget):
    return DailyWaveReadSession(budget=budget)
