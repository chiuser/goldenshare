from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import cache
from pathlib import Path


EXPECTED_MAJOR_INDICES_COUNT = 10
MAJOR_INDICES_SEED_COLUMNS = ("rank", "ts_code", "display_name")
MAJOR_INDICES_SEED_PATH = Path(__file__).with_name("major_indices.cn_a.csv")


@dataclass(frozen=True)
class MajorIndexSeedRow:
    rank: int
    ts_code: str
    display_name: str | None


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
    if not rank_value:
        raise RuntimeError("major_indices.cn_a.csv contains empty rank.")
    if not ts_code:
        raise RuntimeError("major_indices.cn_a.csv contains empty ts_code.")
    try:
        rank = int(rank_value)
    except ValueError as exc:
        raise RuntimeError(f"major_indices.cn_a.csv rank is not an integer: {rank_value}") from exc
    return MajorIndexSeedRow(rank=rank, ts_code=ts_code, display_name=display_name)


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
