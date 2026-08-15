from __future__ import annotations

import re
from pathlib import Path
from typing import Final


FORMAL_LAKE_ROOT: Final = Path("/Volumes/datasource/data_lake")
SUPPORTED_STOCK_NINE_TURN_FREQS: Final = (30, 60, 90, 120)
EXPECTED_BARS_PER_SESSION: Final = {30: 9, 60: 5, 90: 3, 120: 2}
MAX_NINE_TURN_LIMIT: Final = 10_000
MAX_NINE_TURN_PARTITION_FILES: Final = 5_000
STOCK_TS_CODE_PATTERN: Final = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
TRADE_DATE_PARTITION_PATTERN: Final = re.compile(r"^trade_date=(\d{4}-\d{2}-\d{2})$")

BAR_COLUMN_SPECS: Final = (
    ("ts_code", "VARCHAR"),
    ("freq", "INTEGER"),
    ("trade_date", "DATE"),
    ("trade_time", "TIMESTAMP"),
)
NINE_TURN_COLUMN_SPECS: Final = (
    ("ts_code", "VARCHAR"),
    ("freq", "INTEGER"),
    ("trade_date", "DATE"),
    ("trade_time", "TIMESTAMP"),
    ("up_count", "INTEGER"),
    ("down_count", "INTEGER"),
    ("nine_up_turn", "VARCHAR"),
    ("nine_down_turn", "VARCHAR"),
)


def stock_minute_bar_dataset_root(lake_root: Path) -> Path:
    return _bounded_dataset_root(lake_root, Path("gold/quote/stk_mins_qfq"))


def stock_minute_nine_turn_dataset_root(lake_root: Path) -> Path:
    return _bounded_dataset_root(
        lake_root,
        Path("gold/indicator/stk_mins_qfq_nineturn"),
    )


def _bounded_dataset_root(lake_root: Path, relative: Path) -> Path:
    root = lake_root.expanduser().resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("股票九转分钟数据集路径越界。")
    return candidate
