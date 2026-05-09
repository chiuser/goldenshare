from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.parquet_writer import read_parquet_files


RAW_FREQS = {1, 5, 15, 30, 60}
DERIVED_FREQS = {90, 120}


@dataclass(frozen=True)
class ResearchSourceBatch:
    bucket: str
    rows: list[dict[str, Any]]


def read_stk_mins_source_rows(
    *,
    lake_root: Path,
    ts_code: str,
    freq: int,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    if end_date < start_date:
        raise ValueError("end-date 不能早于 start-date。")
    ts_code_value = ts_code.strip()
    if not ts_code_value:
        raise ValueError("ts_code 不能为空。")
    source_files = _source_files(lake_root=lake_root, freq=freq, start_date=start_date, end_date=end_date)
    if not source_files:
        raise RuntimeError(f"缺少源分钟线文件：freq={freq} date_range={start_date.isoformat()}~{end_date.isoformat()}")
    rows = read_parquet_files(source_files)
    filtered = [_normalize_source_row(row, expected_ts_code=ts_code_value, expected_freq=freq) for row in rows if str(row.get("ts_code") or "").strip() == ts_code_value]
    return sorted(filtered, key=lambda row: row["trade_time"])


def read_stk_mins_all_source_rows(
    *,
    lake_root: Path,
    freq: int,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    if end_date < start_date:
        raise ValueError("end-date 不能早于 start-date。")
    source_files = _source_files(lake_root=lake_root, freq=freq, start_date=start_date, end_date=end_date)
    if not source_files:
        raise RuntimeError(f"缺少源分钟线文件：freq={freq} date_range={start_date.isoformat()}~{end_date.isoformat()}")
    rows = read_parquet_files(source_files)
    return sorted((_normalize_source_row(row, expected_freq=freq) for row in rows), key=lambda row: (row["ts_code"], row["trade_time"]))


def read_stk_mins_research_source_batches(
    *,
    lake_root: Path,
    freq: int,
    start_date: date,
    end_date: date,
) -> list[ResearchSourceBatch]:
    if end_date < start_date:
        raise ValueError("end-date 不能早于 start-date。")
    months = _list_trade_months(start_date=start_date, end_date=end_date)
    research_root = lake_root / "research" / "stk_mins_by_symbol_month" / f"freq={freq}"
    missing_months = [month for month in months if not sorted((research_root / f"trade_month={month}").glob("bucket=*/*.parquet"))]
    if missing_months:
        raise RuntimeError(
            "缺少 source research，无法执行 all-market full。请先执行："
            "lake-console rebuild-stk-mins-research-range "
            f"--start-month {months[0]} --end-month {months[-1]} --freqs {freq}。"
            f" 缺失月份：{', '.join(missing_months[:5])}"
        )

    bucket_files: dict[str, list[Path]] = {}
    for month in months:
        month_root = research_root / f"trade_month={month}"
        for bucket_dir in sorted(month_root.glob("bucket=*")):
            files = sorted(bucket_dir.glob("*.parquet"))
            if files:
                bucket = bucket_dir.name.split("=", 1)[1]
                bucket_files.setdefault(bucket, []).extend(files)

    batches: list[ResearchSourceBatch] = []
    for bucket, files in sorted(bucket_files.items()):
        rows = read_parquet_files(files)
        normalized_rows = [
            _normalize_source_row(row, expected_freq=freq)
            for row in rows
            if start_date <= _parse_trade_time(row.get("trade_time")).date() <= end_date
        ]
        if normalized_rows:
            batches.append(ResearchSourceBatch(bucket=bucket, rows=sorted(normalized_rows, key=lambda row: (row["ts_code"], row["trade_time"]))))
    return batches


def _source_files(*, lake_root: Path, freq: int, start_date: date, end_date: date) -> list[Path]:
    source_layer = _source_layer(freq)
    source_root = lake_root / source_layer / "stk_mins_by_date" / f"freq={freq}"
    files: list[Path] = []
    for partition in sorted(source_root.glob("trade_date=*")):
        trade_date = _parse_partition_date(partition)
        if trade_date is None or trade_date < start_date or trade_date > end_date:
            continue
        files.extend(sorted(partition.glob("*.parquet")))
    return files


def _source_layer(freq: int) -> str:
    if freq in RAW_FREQS:
        return "raw_tushare"
    if freq in DERIVED_FREQS:
        return "derived"
    raise ValueError("指标源读取仅支持 freq=1/5/15/30/60/90/120。")


def _parse_partition_date(partition: Path) -> date | None:
    prefix = "trade_date="
    if not partition.name.startswith(prefix):
        return None
    try:
        return date.fromisoformat(partition.name[len(prefix) :])
    except ValueError:
        return None


def _normalize_source_row(row: dict[str, Any], *, expected_freq: int, expected_ts_code: str | None = None) -> dict[str, Any]:
    ts_code = str(row.get("ts_code") or "").strip()
    if expected_ts_code is not None:
        ts_code = expected_ts_code
    if not ts_code:
        raise ValueError(f"源分钟线缺少 ts_code：freq={expected_freq}")
    trade_time = _parse_trade_time(row.get("trade_time"))
    close = row.get("close")
    if close is None:
        raise ValueError(f"源分钟线缺少 close：ts_code={ts_code} freq={expected_freq} trade_time={trade_time}")
    return {
        "ts_code": ts_code,
        "freq": expected_freq,
        "trade_time": trade_time,
        "close": float(close),
    }


def _parse_trade_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().replace(tzinfo=None)
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError("源分钟线 trade_time 不能为空。")
    try:
        return datetime.fromisoformat(raw_value.replace("T", " "))
    except ValueError as exc:
        raise ValueError(f"源分钟线 trade_time 格式无效：{raw_value}") from exc


def _list_trade_months(*, start_date: date, end_date: date) -> list[str]:
    months: list[str] = []
    year = start_date.year
    month = start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months
