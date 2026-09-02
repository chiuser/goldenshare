from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.clients.local_lake.major_index_mins_contract import (
    MAJOR_INDEX_TURNOVER_MAX_PARTITIONS,
)
from src.foundation.models.core.trade_calendar import TradeCalendar


class IndexTurnoverInsightCalendarContractError(RuntimeError):
    code = "ITI_SOURCE_CONTRACT_MISMATCH"


@dataclass(frozen=True, slots=True)
class IndexTurnoverInsightCalendarDay:
    trade_date: date
    previous_trade_date: date | None


class IndexTurnoverInsightCalendarQuery:
    def load_candidates(
        self,
        session: Session,
        *,
        expected_trade_date: date,
        limit: int = MAJOR_INDEX_TURNOVER_MAX_PARTITIONS,
    ) -> tuple[IndexTurnoverInsightCalendarDay, ...]:
        if not 1 <= limit <= MAJOR_INDEX_TURNOVER_MAX_PARTITIONS:
            raise ValueError("calendar candidate limit must be between 1 and 24")
        rows = session.execute(
            select(TradeCalendar.trade_date, TradeCalendar.pretrade_date)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= expected_trade_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(limit)
        ).all()
        candidates = tuple(
            IndexTurnoverInsightCalendarDay(
                trade_date=row.trade_date,
                previous_trade_date=row.pretrade_date,
            )
            for row in rows
        )
        self._validate(candidates)
        return candidates

    @staticmethod
    def _validate(
        candidates: tuple[IndexTurnoverInsightCalendarDay, ...],
    ) -> None:
        dates = tuple(candidate.trade_date for candidate in candidates)
        if len(set(dates)) != len(dates) or dates != tuple(
            sorted(dates, reverse=True)
        ):
            raise IndexTurnoverInsightCalendarContractError(
                "SSE 交易日候选必须严格降序且无重复。"
            )
        for newer, older in zip(candidates, candidates[1:], strict=False):
            if newer.previous_trade_date != older.trade_date:
                raise IndexTurnoverInsightCalendarContractError(
                    "SSE 交易日候选与 pretrade_date 不相邻。"
                )
