from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class CollectionWindowContext:
    local_now: datetime
    is_trading_day: bool
    collection_status: str
    collection_sessions: tuple[str, ...]


class RealtimeMarketClock:
    def resolve(
        self,
        session: Session,
        *,
        exchange: str,
        collection_sessions: str,
        now: datetime | None = None,
    ) -> CollectionWindowContext:
        local_now = (now or datetime.now(CN_TIMEZONE)).astimezone(CN_TIMEZONE)
        sessions = _parse_collection_sessions(collection_sessions)
        is_trading_day = bool(
            session.scalar(
                select(TradeCalendar.is_open).where(
                    TradeCalendar.exchange == exchange,
                    TradeCalendar.trade_date == local_now.date(),
                )
            )
        )
        if not is_trading_day:
            status = "market_closed"
        elif _is_inside_any_session(local_now.timetz().replace(tzinfo=None), sessions):
            status = "open"
        else:
            status = "idle"
        return CollectionWindowContext(
            local_now=local_now,
            is_trading_day=is_trading_day,
            collection_status=status,
            collection_sessions=tuple(f"{start.isoformat(timespec='minutes')}-{end.isoformat(timespec='minutes')}" for start, end in sessions),
        )


def _parse_collection_sessions(raw_value: str) -> tuple[tuple[time, time], ...]:
    sessions: list[tuple[time, time]] = []
    for raw_part in raw_value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        start_text, separator, end_text = part.partition("-")
        if not separator:
            raise ValueError(f"invalid collection session: {part}")
        sessions.append((time.fromisoformat(start_text.strip()), time.fromisoformat(end_text.strip())))
    if not sessions:
        raise ValueError("collection sessions cannot be empty")
    return tuple(sessions)


def _is_inside_any_session(current_time: time, sessions: tuple[tuple[time, time], ...]) -> bool:
    return any(start <= current_time <= end for start, end in sessions)
