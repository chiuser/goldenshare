from __future__ import annotations

import re
from pathlib import Path
from typing import Final, Literal


IndexMinuteDataset = Literal["bars", "indicators"]

FORMAL_LAKE_ROOT: Final = Path("/Volumes/datasource/data_lake")
SUPPORTED_INDEX_MINUTE_FREQS: Final = (1, 5, 15, 30, 60, 90, 120)
EXPECTED_BARS_PER_SESSION: Final = {1: 241, 5: 48, 15: 16, 30: 8, 60: 4, 90: 3, 120: 2}
MAX_INDEX_MINUTE_LIMIT: Final = 10_000
MAX_INDEX_MINUTE_PARTITION_FILES: Final = 5_000
INDEX_MINUTE_CURSOR_VERSION: Final = 1
INDEX_TS_CODE_PATTERN: Final = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
TRADE_DATE_PARTITION_PATTERN: Final = re.compile(r"^trade_date=(\d{4}-\d{2}-\d{2})$")

GOLD_PARAMS_KEY: Final = "ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3"
GOLD_INDICATOR_VERSION: Final = 1

GOLD_BAR_COLUMN_SPECS: Final = (
    ("ts_code", "VARCHAR"),
    ("freq", "INTEGER"),
    ("trade_date", "DATE"),
    ("trade_time", "TIMESTAMP"),
    ("open", "DOUBLE"),
    ("high", "DOUBLE"),
    ("low", "DOUBLE"),
    ("close", "DOUBLE"),
    ("vol", "DOUBLE"),
    ("amount", "DOUBLE"),
    ("exchange", "VARCHAR"),
    ("vwap", "DOUBLE"),
)

GOLD_INDICATOR_COLUMN_SPECS: Final = (
    ("ts_code", "VARCHAR"),
    ("freq", "SMALLINT"),
    ("trade_date", "DATE"),
    ("trade_time", "TIMESTAMP"),
    ("ma_5", "DOUBLE"),
    ("ma_10", "DOUBLE"),
    ("ma_20", "DOUBLE"),
    ("ma_30", "DOUBLE"),
    ("ma_60", "DOUBLE"),
    ("ma_90", "DOUBLE"),
    ("ma_250", "DOUBLE"),
    ("boll_mid", "DOUBLE"),
    ("boll_upper", "DOUBLE"),
    ("boll_lower", "DOUBLE"),
    ("macd_dif", "DOUBLE"),
    ("macd_dea", "DOUBLE"),
    ("macd", "DOUBLE"),
    ("kdj_k", "DOUBLE"),
    ("kdj_d", "DOUBLE"),
    ("kdj_j", "DOUBLE"),
    ("observation_count", "INTEGER"),
    ("params_key", "VARCHAR"),
    ("indicator_version", "INTEGER"),
)


def major_index_minute_dataset_root(
    lake_root: Path, dataset: IndexMinuteDataset
) -> Path:
    root = lake_root.expanduser().resolve()
    relative = (
        Path("gold/quote/major_index_mins")
        if dataset == "bars"
        else Path("gold/indicator/major_index_mins_technical")
    )
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("指数分钟数据集路径越界。")
    return candidate


def major_index_minute_frequency_root(
    lake_root: Path,
    dataset: IndexMinuteDataset,
    freq: int,
) -> Path:
    if freq not in SUPPORTED_INDEX_MINUTE_FREQS:
        raise ValueError("不支持的指数分钟频率。")
    partition = str(freq)
    candidate = (
        major_index_minute_dataset_root(lake_root, dataset) / f"freq={partition}"
    ).resolve()
    if not candidate.is_relative_to(lake_root.expanduser().resolve()):
        raise ValueError("指数分钟频率路径越界。")
    return candidate
