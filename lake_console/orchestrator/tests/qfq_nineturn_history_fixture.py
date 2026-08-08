"""Small two-year Lake fixture for QFQ nine-turn offline-tool tests."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb


def build_qfq_nineturn_history_fixture(
    lake_root: Path,
    *,
    trading_day_count: int = 22,
    stock_codes: tuple[str, ...] = ("000001.SZ", "000002.SZ"),
) -> tuple[str, ...]:
    dates = _business_dates(trading_day_count)
    with duckdb.connect() as connection:
        for index, trade_date in enumerate(dates, start=1):
            daily_path = (
                lake_root
                / "gold"
                / "quote"
                / "stock_daily_qfq"
                / f"trade_date={trade_date}"
                / "part-000.parquet"
            )
            daily_path.parent.mkdir(parents=True, exist_ok=True)
            values = ", ".join(
                f"('{code}', DATE '{trade_date}', {float(index + offset)})"
                for offset, code in enumerate(stock_codes)
            )
            connection.execute(
                f"""
                COPY (
                  SELECT ts_code::VARCHAR AS ts_code,
                         trade_date::DATE AS trade_date,
                         close::DOUBLE AS close
                  FROM (VALUES {values}) source(ts_code, trade_date, close)
                  ORDER BY ts_code
                ) TO '{daily_path}' (FORMAT PARQUET)
                """
            )

        dates_by_year: dict[int, list[tuple[int, str]]] = {}
        for index, trade_date in enumerate(dates, start=1):
            dates_by_year.setdefault(int(trade_date[:4]), []).append((index, trade_date))
        for freq in (30, 60, 90, 120):
            for code_offset, code in enumerate(stock_codes):
                for year, year_dates in dates_by_year.items():
                    minute_path = (
                        lake_root
                        / "gold"
                        / "quote"
                        / "stk_mins_qfq"
                        / f"freq={freq}"
                        / f"ts_code={code}"
                        / f"year={year}"
                        / "part-000.parquet"
                    )
                    minute_path.parent.mkdir(parents=True, exist_ok=True)
                    values = ", ".join(
                        (
                            f"('{code}', {freq}, DATE '{trade_date}', "
                            f"TIMESTAMP '{trade_date} 15:00:00', "
                            f"{float(index + code_offset)})"
                        )
                        for index, trade_date in year_dates
                    )
                    connection.execute(
                        f"""
                        COPY (
                          SELECT ts_code::VARCHAR AS ts_code,
                                 freq::INTEGER AS freq,
                                 trade_date::DATE AS trade_date,
                                 trade_time::TIMESTAMP AS trade_time,
                                 close::DOUBLE AS close
                          FROM (VALUES {values})
                            source(ts_code, freq, trade_date, trade_time, close)
                          ORDER BY trade_time
                        ) TO '{minute_path}' (FORMAT PARQUET)
                        """
                    )
    return dates


def _business_dates(count: int) -> tuple[str, ...]:
    if count < 10:
        raise ValueError("Fixture requires at least 10 trading days.")
    values: list[str] = []
    current = date(2025, 12, 15)
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current.isoformat())
        current += timedelta(days=1)
    return tuple(values)
