"""Fixed source projections; no display conversion or signal computation."""
from collections.abc import Mapping
from datetime import date
from typing import Protocol

from sqlalchemy import Select, select

from src.foundation.models.core.index_factor_pro import IndexFactorPro
from src.foundation.models.core.trade_calendar import TradeCalendar


class DailyWaveSourceError(ValueError):
    """Invalid source rows, calendar or connection configuration."""


class DailyWaveReadSessionProtocol(Protocol):
    async def execute_read(self, statement: Select, parameters=None) -> tuple[Mapping, ...]: ...


class DailyWaveQuery:
    @staticmethod
    def _market():
        table = IndexFactorPro.__table__
        return select(*(table.c[name] for name in (
            "ts_code", "trade_date", "close", "macd_dif_bfq", "macd_dea_bfq", "macd_bfq")))

    async def load_main_window(self, session, *, start_date: date, end_date: date, spec):
        table = IndexFactorPro.__table__
        statement = self._market().where(
            table.c.ts_code == spec.ts_code,
            table.c.trade_date.between(start_date, end_date),
        ).order_by(table.c.trade_date.asc()).limit(spec.max_main_points + 1)
        return await session.execute_read(statement)

    async def load_context_window(self, session, *, before_date: date, spec):
        table = IndexFactorPro.__table__
        statement = self._market().where(
            table.c.ts_code == spec.ts_code,
            table.c.trade_date >= date.fromisoformat(spec.absolute_start),
            table.c.trade_date < before_date,
        ).order_by(table.c.trade_date.desc()).limit(spec.context_batch_points + 1)
        return await session.execute_read(statement)

    async def load_calendar(self, session, *, context_start: date, observation_end: date, spec):
        table = TradeCalendar.__table__
        statement = select(table.c.exchange, table.c.trade_date, table.c.is_open).where(
            table.c.exchange == "SSE", table.c.trade_date.between(context_start, observation_end),
        ).order_by(table.c.trade_date.asc()).limit(spec.max_calendar_days + 1)
        return await session.execute_read(statement)
