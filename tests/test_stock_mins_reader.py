"""Gold 1-minute fixtures shared by Trading Assistant tests."""

from datetime import date
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")


def _write_bars(root: Path, *, code: str = "000638.SZ", freq: int = 5, year: int = 2026, rows: list[tuple] | None = None) -> Path:
    target = root / "gold" / "quote" / "stk_mins_qfq" / f"freq={freq}" / f"ts_code={code}" / f"year={year}" / "part-000.parquet"
    target.parent.mkdir(parents=True)
    rows = rows or [
        (code, freq, date(2026, 7, 31), "2026-07-31 09:35:00", 1.1, 1.3, 1.0, 1.2, 11.0, 110.0, "SZSE"),
        (code, freq, date(2026, 7, 31), "2026-07-31 09:40:00", 1.2, 1.4, 1.1, 1.3, 12.0, 120.0, "SZSE"),
        (code, freq, date(2026, 7, 31), "2026-07-31 09:45:00", 1.3, 1.5, 1.2, 1.4, 13.0, 130.0, "SZSE"),
        (code, freq, date(2026, 7, 31), "2026-07-31 09:50:00", 1.4, 1.6, 1.3, 1.5, 14.0, 140.0, "SZSE"),
    ]
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE bars (
                ts_code VARCHAR, freq INTEGER, trade_date DATE, trade_time TIMESTAMP,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                vol DOUBLE, amount DOUBLE, exchange VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO bars VALUES (?, ?, ?, CAST(? AS TIMESTAMP), ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute("COPY bars TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()
    return target
