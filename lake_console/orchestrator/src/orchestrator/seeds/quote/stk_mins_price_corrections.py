from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, time
from functools import cache
from pathlib import Path
from typing import Iterable


STK_MINS_PRICE_CORRECTIONS_SEED_PATH = Path(__file__).with_name(
    "stk_mins_price_corrections.cn_a.csv"
)
STK_MINS_PRICE_CORRECTIONS_SEED_VERSION = "stk_mins_price_corrections.cn_a.v1"
STK_MINS_PRICE_CORRECTIONS_SEED_COLUMNS = (
    "freq",
    "trade_date",
    "ts_code",
    "trade_time",
    "open",
    "high",
    "low",
    "close",
    "reason",
)
STK_MINS_PRICE_CORRECTION_DATES = frozenset(
    {
        "2014-06-03",
        "2014-08-04",
        "2014-12-22",
    }
)


@dataclass(frozen=True)
class StkMinsPriceCorrectionSeedRow:
    freq: int
    trade_date: date
    ts_code: str
    trade_time: time
    open: float
    high: float
    low: float
    close: float
    reason: str

    @property
    def business_key(self) -> tuple[int, date, str, time]:
        return (self.freq, self.trade_date, self.ts_code, self.trade_time)


@dataclass(frozen=True)
class StkMinsPriceCorrectionCatalog:
    rows: tuple[StkMinsPriceCorrectionSeedRow, ...]

    def corrections_for_partition(
        self,
        *,
        freq: int,
        trade_date: str | date,
    ) -> tuple[StkMinsPriceCorrectionSeedRow, ...]:
        trade_day = _coerce_trade_date(trade_date)
        return tuple(
            row for row in self.rows if row.freq == freq and row.trade_date == trade_day
        )


def has_stk_mins_price_corrections(trade_date: str | date) -> bool:
    """Fast daily-path guard that does not load the CSV catalog."""

    trade_date_value = trade_date.isoformat() if isinstance(trade_date, date) else trade_date
    return trade_date_value in STK_MINS_PRICE_CORRECTION_DATES


@cache
def load_stk_mins_price_correction_catalog(
    path: Path = STK_MINS_PRICE_CORRECTIONS_SEED_PATH,
) -> StkMinsPriceCorrectionCatalog:
    if not path.exists():
        raise FileNotFoundError(f"Missing stk_mins price correction seed: {path}")

    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if tuple(reader.fieldnames or ()) != STK_MINS_PRICE_CORRECTIONS_SEED_COLUMNS:
            raise ValueError(
                "stk_mins price correction seed columns must be exactly "
                f"{STK_MINS_PRICE_CORRECTIONS_SEED_COLUMNS}."
            )
        rows = tuple(
            _coerce_seed_row(raw_row, row_number=index + 2)
            for index, raw_row in enumerate(reader)
        )

    _validate_seed_rows(rows)
    return StkMinsPriceCorrectionCatalog(rows=rows)


def _coerce_seed_row(
    raw_row: dict[str, str],
    *,
    row_number: int,
) -> StkMinsPriceCorrectionSeedRow:
    values = {
        column: (raw_row.get(column) or "").strip()
        for column in STK_MINS_PRICE_CORRECTIONS_SEED_COLUMNS
    }
    missing_columns = [column for column, value in values.items() if not value]
    if missing_columns:
        raise ValueError(
            f"stk_mins price correction seed row {row_number} has blank fields: "
            f"{missing_columns}"
        )

    try:
        freq = int(values["freq"])
    except ValueError as exc:
        raise ValueError(
            f"stk_mins price correction seed row {row_number} has invalid freq: "
            f"{values['freq']}"
        ) from exc
    if freq != 1:
        raise ValueError(
            "stk_mins price correction seed currently only supports freq=1; "
            f"row {row_number} has freq={freq}."
        )

    trade_date = _parse_seed_date(
        values["trade_date"],
        row_number=row_number,
        field_name="trade_date",
    )
    trade_time = _parse_seed_time(
        values["trade_time"],
        row_number=row_number,
        field_name="trade_time",
    )
    open_price = _parse_positive_price(values["open"], row_number=row_number, field_name="open")
    high_price = _parse_positive_price(values["high"], row_number=row_number, field_name="high")
    low_price = _parse_positive_price(values["low"], row_number=row_number, field_name="low")
    close_price = _parse_positive_price(
        values["close"],
        row_number=row_number,
        field_name="close",
    )
    _validate_price_relation(
        row_number=row_number,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
    )

    return StkMinsPriceCorrectionSeedRow(
        freq=freq,
        trade_date=trade_date,
        ts_code=values["ts_code"],
        trade_time=trade_time,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        reason=values["reason"],
    )


def _validate_seed_rows(rows: tuple[StkMinsPriceCorrectionSeedRow, ...]) -> None:
    if not rows:
        raise ValueError("stk_mins price correction seed must not be empty.")

    duplicate_keys = _duplicates(row.business_key for row in rows)
    if duplicate_keys:
        raise ValueError(
            "stk_mins price correction seed business keys must be unique: "
            f"{duplicate_keys[:10]}"
        )

    seed_trade_dates = frozenset(row.trade_date.isoformat() for row in rows)
    if seed_trade_dates != STK_MINS_PRICE_CORRECTION_DATES:
        raise ValueError(
            "STK_MINS_PRICE_CORRECTION_DATES must match seed trade_date values: "
            f"constant={sorted(STK_MINS_PRICE_CORRECTION_DATES)}, "
            f"seed={sorted(seed_trade_dates)}"
        )


def _parse_seed_date(value: str, *, row_number: int, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"stk_mins price correction seed row {row_number} has invalid "
            f"{field_name}: {value}"
        ) from exc


def _parse_seed_time(value: str, *, row_number: int, field_name: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"stk_mins price correction seed row {row_number} has invalid "
            f"{field_name}: {value}"
        ) from exc


def _parse_positive_price(value: str, *, row_number: int, field_name: str) -> float:
    try:
        price = float(value)
    except ValueError as exc:
        raise ValueError(
            f"stk_mins price correction seed row {row_number} has invalid "
            f"{field_name}: {value}"
        ) from exc
    if price <= 0:
        raise ValueError(
            f"stk_mins price correction seed row {row_number} has non-positive "
            f"{field_name}: {value}"
        )
    return price


def _validate_price_relation(
    *,
    row_number: int,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
) -> None:
    if high_price < low_price:
        raise ValueError(
            f"stk_mins price correction seed row {row_number} has high below low."
        )
    if not low_price <= open_price <= high_price:
        raise ValueError(
            f"stk_mins price correction seed row {row_number} has open outside [low, high]."
        )
    if not low_price <= close_price <= high_price:
        raise ValueError(
            f"stk_mins price correction seed row {row_number} has close outside [low, high]."
        )


def _coerce_trade_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _duplicates(values: Iterable[object]) -> list[object]:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)
