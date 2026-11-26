"""Convert Tushare index minute volume before the normal raw upsert."""

from collections import defaultdict
from datetime import date, timedelta
from math import fsum
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.foundation.dao.trade_calendar_dao import TradeCalendarDAO
from src.foundation.models.raw.index_mins_volume_evidence import IndexMinsVolumeEvidence


def resolve_index_minute_volume_unit(previous_total: float, previous_unit: str, source_total: float) -> str:
    if source_total > previous_total * 50:
        return "share"
    if source_total * 50 < previous_total:
        return "lot"
    return previous_unit


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
    model = IndexMinsVolumeEvidence
    lookup_keys = set(groups)
    lookup_keys.update(
        (code, freq, previous_dates[day])
        for code, freq, day in groups
        if previous_dates.get(day) is not None
    )
    recorded = {
        (record.ts_code, record.freq, record.trade_date): (record.source_vol, record.source_unit)
        for record in session.scalars(
            select(model).where(tuple_(model.ts_code, model.freq, model.trade_date).in_(lookup_keys))
        )
    }

    output = []
    evidence = []
    for key, day_rows in sorted(groups.items()):
        code, freq, day = key
        previous = recorded.get((code, freq, previous_dates.get(day)))
        source_total = fsum(row["vol"] for row in day_rows if row["vol"] is not None)
        if previous is not None:
            unit = resolve_index_minute_volume_unit(*previous, source_total)
        elif key in recorded:
            unit = recorded[key][1]
        else:
            raise ValueError(f"指数分钟成交量比较起点缺失：{code} {freq} {day}")
        multiplier = 100 if unit == "lot" else 1
        output.extend(
            {**row, "vol": row["vol"] * multiplier if row["vol"] is not None else None}
            for row in day_rows
        )
        recorded[key] = (source_total, unit)
        evidence.append(dict(ts_code=code, freq=freq, trade_date=day, source_vol=source_total, source_unit=unit))

    statement = insert(model)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[model.ts_code, model.freq, model.trade_date],
            set_={"source_vol": statement.excluded.source_vol, "source_unit": statement.excluded.source_unit},
        ),
        evidence,
    )
    return output
