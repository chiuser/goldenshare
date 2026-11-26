"""Normalize Tushare minute volume against the previous session's stored shares."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from math import fsum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.dao.trade_calendar_dao import TradeCalendarDAO
from src.foundation.models.raw.raw_index_mins import RawIndexMins


def normalize_index_minute_volumes(
    session: Session,
    calendar: TradeCalendarDAO,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not rows:
        return rows

    # Like the quote DAO, keep the last row for each write key before summing.
    unique_rows = {(row["ts_code"], row["freq"], row["trade_time"]): row for row in rows}
    groups: dict[tuple[str, str, date], list[dict[str, Any]]] = defaultdict(list)
    for (code, freq, stamp), row in unique_rows.items():
        groups[code, freq, stamp.date()].append(row)

    first_day, last_day = min(key[2] for key in groups), max(key[2] for key in groups)
    first_previous = calendar.get_latest_open_date("SSE", first_day - timedelta(days=1))
    dates = calendar.get_open_dates("SSE", first_day, last_day) if first_day != last_day else [first_day]
    previous_dates = dict(zip(dates, [first_previous, *dates[:-1]]))

    output = []
    share_totals: dict[tuple[str, str, date], float] = {}
    for key, day_rows in sorted(groups.items()):
        code, freq, day = key
        previous_day = previous_dates.get(day)
        previous_shares = share_totals.get((code, freq, previous_day)) if previous_day else None
        if previous_day is not None and previous_shares is None:
            start = datetime.combine(previous_day, time.min)
            previous_shares = session.scalar(
                select(func.sum(RawIndexMins.vol)).where(
                    RawIndexMins.ts_code == code,
                    RawIndexMins.freq == freq,
                    RawIndexMins.trade_time >= start,
                    RawIndexMins.trade_time < start + timedelta(days=1),
                )
            )
        if previous_shares is None:
            raise ValueError(f"指数分钟成交量比较起点缺失：{code} {freq} {day}")

        source_total = fsum(row["vol"] for row in day_rows if row["vol"] is not None)
        multiplier = 100 if source_total * 50 < previous_shares else 1
        output.extend(
            {**row, "vol": row["vol"] * multiplier if row["vol"] is not None else None}
            for row in day_rows
        )
        share_totals[key] = source_total * multiplier
    return output
