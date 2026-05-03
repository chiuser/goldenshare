from __future__ import annotations

from datetime import date
from pathlib import Path

from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.sync.helpers.params import parse_date


def load_open_trade_dates(*, lake_root: Path, start_date: date, end_date: date) -> list[date]:
    calendar_file = lake_root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet"
    if not calendar_file.exists():
        raise RuntimeError(
            "缺少本地交易日历 manifest/trading_calendar/tushare_trade_cal.parquet。"
            "请先执行 sync-trade-cal。"
        )
    rows = read_parquet_rows(calendar_file)
    trade_dates: list[date] = []
    for row in rows:
        if not bool(row.get("is_open")):
            continue
        current_date = parse_date(row.get("cal_date"))
        if start_date <= current_date <= end_date:
            trade_dates.append(current_date)
    return sorted(set(trade_dates))
