from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isnan
from pathlib import Path
from typing import Any

import duckdb

from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.services.security_universe_filter import load_security_universe_rows

BSE_MAPPING_PATH = Path("manifest") / "security_reference" / "tushare_bse_mapping.parquet"
BSE_920_STK_MINS_MIN_SOURCE_DATE = date(2022, 7, 15)
RAW_FREQS = {1, 5, 15, 30, 60}
DERIVED_FREQS = {90, 120}


@dataclass(frozen=True)
class MissingStateClassification:
    bootstrap_ts_codes: frozenset[str]
    rejected_reasons: dict[str, str]

    @property
    def rejected(self) -> bool:
        return bool(self.rejected_reasons)


@dataclass(frozen=True)
class _BseMappingReference:
    loaded: bool
    new_codes: frozenset[str]


def classify_missing_macd_states(
    *,
    lake_root: Path,
    missing_ts_codes: list[str],
    freq: int,
    window_start_date: date,
    trade_date: date,
) -> MissingStateClassification:
    if not missing_ts_codes:
        return MissingStateClassification(bootstrap_ts_codes=frozenset(), rejected_reasons={})
    if trade_date < window_start_date:
        raise ValueError("trade_date 不能早于 window_start_date。")

    rows_by_code = {row.ts_code: row for row in load_security_universe_rows(lake_root=lake_root)}
    bse_missing_codes = sorted({item for item in missing_ts_codes if _is_bse_920_code(item)})
    bse_reference = _load_bse_mapping_reference(lake_root=lake_root) if bse_missing_codes else None
    bse_first_source_dates = (
        _find_bse_920_first_source_dates(lake_root=lake_root, ts_codes=bse_missing_codes, freq=freq, end_date=trade_date)
        if bse_reference is not None and bse_reference.loaded
        else {}
    )
    bootstrap_codes: set[str] = set()
    rejected_reasons: dict[str, str] = {}
    for ts_code in sorted(set(missing_ts_codes)):
        universe_row = rows_by_code.get(ts_code)
        if universe_row is None:
            rejected_reasons[ts_code] = "stock_basic 缺少该 ts_code，无法判断是否为新股"
            continue
        if universe_row.delist_date is not None and universe_row.delist_date < trade_date:
            rejected_reasons[ts_code] = (
                "源分钟线日期晚于 stock_basic.delist_date，疑似源数据或股票池不一致，"
                f"list_date={universe_row.list_date.isoformat()} delist_date={universe_row.delist_date.isoformat()}"
            )
            continue
        if _is_bse_920_code(ts_code):
            if bse_reference is None or not bse_reference.loaded:
                rejected_reasons[ts_code] = (
                    "北交所 920 新代码缺少 bse_mapping manifest，无法按分钟线代码切换口径初始化 MACD state"
                )
                continue
            if ts_code not in bse_reference.new_codes:
                rejected_reasons[ts_code] = (
                    "北交所 920 新代码不在 bse_mapping.n_code 中，无法按分钟线代码切换口径初始化 MACD state"
                )
                continue
            first_source_date = bse_first_source_dates.get(ts_code)
            if first_source_date is None:
                rejected_reasons[ts_code] = (
                    "北交所 920 新代码缺少 MACD state，但未能在本地分钟线源文件中确认首次出现日期"
                )
                continue
            if first_source_date < BSE_920_STK_MINS_MIN_SOURCE_DATE:
                rejected_reasons[ts_code] = (
                    "北交所 920 新代码源分钟线日期早于本地约定的首次分钟线日期，"
                    f"min_source_date={BSE_920_STK_MINS_MIN_SOURCE_DATE.isoformat()} "
                    f"first_source_date={first_source_date.isoformat()}"
                )
                continue
            if trade_date != first_source_date:
                rejected_reasons[ts_code] = (
                    "北交所 920 新代码缺少 MACD state，必须从该股票本地首次分钟线日期初始化，"
                    f"first_source_date={first_source_date.isoformat()} "
                    f"trade_date={trade_date.isoformat()}"
                )
                continue
            bootstrap_codes.add(ts_code)
            continue
        if universe_row.list_date > trade_date:
            rejected_reasons[ts_code] = (
                "源分钟线日期早于 stock_basic.list_date，疑似源数据或股票池不一致，"
                f"list_date={universe_row.list_date.isoformat()} trade_date={trade_date.isoformat()}"
            )
            continue
        if universe_row.list_date < window_start_date:
            rejected_reasons[ts_code] = (
                "老股票缺少 MACD state，不能从本次增量窗口中途初始化，"
                f"list_date={universe_row.list_date.isoformat()} window_start={window_start_date.isoformat()}"
            )
            continue
        bootstrap_codes.add(ts_code)

    return MissingStateClassification(
        bootstrap_ts_codes=frozenset(bootstrap_codes),
        rejected_reasons=rejected_reasons,
    )


def _load_bse_mapping_reference(*, lake_root: Path) -> _BseMappingReference:
    mapping_file = lake_root / BSE_MAPPING_PATH
    if not mapping_file.exists():
        return _BseMappingReference(loaded=False, new_codes=frozenset())

    new_codes: set[str] = set()
    for row in read_parquet_rows(mapping_file):
        n_code = _text_or_none(row.get("n_code"))
        if n_code and _is_bse_920_code(n_code):
            new_codes.add(n_code)
    return _BseMappingReference(loaded=True, new_codes=frozenset(new_codes))


def _find_bse_920_first_source_dates(*, lake_root: Path, ts_codes: list[str], freq: int, end_date: date) -> dict[str, date]:
    if not ts_codes:
        return {}
    source_root = lake_root / _source_layer(freq) / "stk_mins_by_date" / f"freq={freq}"
    source_files: list[Path] = []
    for partition in sorted(source_root.glob("trade_date=*")):
        partition_date = _parse_trade_date_partition(partition)
        if partition_date is None:
            continue
        if BSE_920_STK_MINS_MIN_SOURCE_DATE <= partition_date <= end_date:
            source_files.extend(sorted(partition.glob("*.parquet")))
    if not source_files:
        return {}

    placeholders = ",".join("?" for _ in ts_codes)
    sql = f"""
        select ts_code, min(cast(trade_time as timestamp)) as first_trade_time
        from read_parquet(?)
        where ts_code in ({placeholders})
        group by ts_code
    """
    rows = duckdb.connect(database=":memory:").execute(sql, [[str(path) for path in source_files], *ts_codes]).fetchall()
    return {str(ts_code): first_trade_time.date() for ts_code, first_trade_time in rows if first_trade_time is not None}


def _source_layer(freq: int) -> str:
    if freq in RAW_FREQS:
        return "raw_tushare"
    if freq in DERIVED_FREQS:
        return "derived"
    raise ValueError("指标源读取仅支持 freq=1/5/15/30/60/90/120。")


def _parse_trade_date_partition(partition: Path) -> date | None:
    prefix = "trade_date="
    if not partition.name.startswith(prefix):
        return None
    try:
        return date.fromisoformat(partition.name[len(prefix) :])
    except ValueError:
        return None


def _is_bse_920_code(ts_code: str) -> bool:
    return ts_code.startswith("920") and ts_code.endswith(".BJ")


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and isnan(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    return text
