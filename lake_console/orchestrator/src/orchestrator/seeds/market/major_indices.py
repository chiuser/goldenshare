from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

EXPECTED_MAJOR_INDICES_COUNT = 11
MAJOR_INDICES_SEED_COLUMNS = (
    "rank",
    "ts_code",
    "display_name",
    "effective_start_date",
    "effective_end_date",
)
MAJOR_INDICES_SEED_PATH = Path(__file__).with_name("major_indices.cn_a.csv")


@dataclass(frozen=True)
class MajorIndexSeedRow:
    rank: int
    ts_code: str
    display_name: str | None
    effective_start_date: date
    effective_end_date: date | None


@cache
def load_major_indices_seed() -> tuple[MajorIndexSeedRow, ...]:
    if not MAJOR_INDICES_SEED_PATH.exists():
        raise FileNotFoundError(f"Missing major indices seed file: {MAJOR_INDICES_SEED_PATH}")

    with MAJOR_INDICES_SEED_PATH.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if tuple(reader.fieldnames or ()) != MAJOR_INDICES_SEED_COLUMNS:
            raise RuntimeError(
                "major_indices.cn_a.csv must use columns: "
                f"{', '.join(MAJOR_INDICES_SEED_COLUMNS)}"
            )
        rows = tuple(_parse_major_index_seed_row(row) for row in reader)

    _validate_major_indices_seed(rows)
    return rows


def _parse_major_index_seed_row(row: dict[str, str]) -> MajorIndexSeedRow:
    rank_value = row.get("rank", "").strip()
    ts_code = row.get("ts_code", "").strip()
    display_name = row.get("display_name", "").strip() or None
    effective_start_date_value = row.get("effective_start_date", "").strip()
    effective_end_date_value = row.get("effective_end_date", "").strip()
    if not rank_value:
        raise RuntimeError("major_indices.cn_a.csv contains empty rank.")
    if not ts_code:
        raise RuntimeError("major_indices.cn_a.csv contains empty ts_code.")
    if not effective_start_date_value:
        raise RuntimeError("major_indices.cn_a.csv contains empty effective_start_date.")
    try:
        rank = int(rank_value)
    except ValueError as exc:
        raise RuntimeError(f"major_indices.cn_a.csv rank is not an integer: {rank_value}") from exc
    effective_start_date = _parse_seed_date(
        effective_start_date_value,
        column_name="effective_start_date",
        ts_code=ts_code,
    )
    effective_end_date = (
        _parse_seed_date(
            effective_end_date_value,
            column_name="effective_end_date",
            ts_code=ts_code,
        )
        if effective_end_date_value
        else None
    )
    return MajorIndexSeedRow(
        rank=rank,
        ts_code=ts_code,
        display_name=display_name,
        effective_start_date=effective_start_date,
        effective_end_date=effective_end_date,
    )


def _parse_seed_date(value: str, *, column_name: str, ts_code: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError(
            "major_indices.cn_a.csv "
            f"{column_name} must use YYYY-MM-DD for {ts_code}: {value}"
        ) from exc


def _validate_major_indices_seed(rows: tuple[MajorIndexSeedRow, ...]) -> None:
    if len(rows) != EXPECTED_MAJOR_INDICES_COUNT:
        raise RuntimeError(
            "major_indices.cn_a.csv must contain exactly "
            f"{EXPECTED_MAJOR_INDICES_COUNT} rows."
        )

    ranks = [row.rank for row in rows]
    expected_ranks = list(range(1, EXPECTED_MAJOR_INDICES_COUNT + 1))
    if ranks != expected_ranks:
        raise RuntimeError(
            "major_indices.cn_a.csv ranks must be continuous and ordered from 1 to "
            f"{EXPECTED_MAJOR_INDICES_COUNT}."
        )

    codes = [row.ts_code for row in rows]
    if len(set(codes)) != len(codes):
        raise RuntimeError("major_indices.cn_a.csv contains duplicate ts_code values.")

    invalid_date_ranges = [
        row.ts_code
        for row in rows
        if row.effective_end_date is not None
        and row.effective_end_date < row.effective_start_date
    ]
    if invalid_date_ranges:
        raise RuntimeError(
            "major_indices.cn_a.csv contains effective_end_date earlier than "
            f"effective_start_date: {invalid_date_ranges}"
        )


def active_major_indices_seed_rows(trade_date: str | date) -> tuple[MajorIndexSeedRow, ...]:
    trade_day = date.fromisoformat(trade_date) if isinstance(trade_date, str) else trade_date
    return tuple(
        row
        for row in load_major_indices_seed()
        if row.effective_start_date <= trade_day
        and (row.effective_end_date is None or trade_day <= row.effective_end_date)
    )
