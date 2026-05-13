from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.parquet_writer import read_parquet_files
from lake_console.backend.app.services.stk_mins_clean_next_gate import CleanNextPartitionGateService


RAW_FREQS = {1, 5, 15, 30, 60}
DERIVED_FREQS = {90, 120}


@dataclass(frozen=True)
class ResearchSourceBatch:
    trade_month: str
    bucket: str
    batch_index: int
    batch_count: int
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class ResearchSourceBatchPlan:
    trade_month: str
    bucket: str
    files: tuple[Path, ...]


@dataclass(frozen=True)
class ResearchSourcePlan:
    months: tuple[str, ...]
    batches: tuple[ResearchSourceBatchPlan, ...]

    @property
    def file_count(self) -> int:
        return sum(len(batch.files) for batch in self.batches)


@dataclass(frozen=True)
class ByDateSourceBatch:
    trade_date: date
    batch_index: int
    batch_count: int
    files: tuple[Path, ...]
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class ByDateSourceBatchPlan:
    trade_date: date
    files: tuple[Path, ...]


@dataclass(frozen=True)
class ByDateSourcePlan:
    trade_dates: tuple[date, ...]
    batches: tuple[ByDateSourceBatchPlan, ...]

    @property
    def file_count(self) -> int:
        return sum(len(batch.files) for batch in self.batches)


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
    return list(
        iter_stk_mins_research_source_batches(
            lake_root=lake_root,
            freq=freq,
            start_date=start_date,
            end_date=end_date,
        )
    )


def plan_stk_mins_research_source_batches(
    *,
    lake_root: Path,
    freq: int,
    start_date: date,
    end_date: date,
) -> ResearchSourcePlan:
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

    batches: list[ResearchSourceBatchPlan] = []
    for month in months:
        month_root = research_root / f"trade_month={month}"
        for bucket_dir in sorted(month_root.glob("bucket=*")):
            files = sorted(bucket_dir.glob("*.parquet"))
            if files:
                bucket = bucket_dir.name.split("=", 1)[1]
                batches.append(ResearchSourceBatchPlan(trade_month=month, bucket=bucket, files=tuple(files)))
    return ResearchSourcePlan(months=tuple(months), batches=tuple(batches))


def plan_stk_mins_by_date_source_batches(
    *,
    lake_root: Path,
    freq: int,
    start_date: date,
    end_date: date,
) -> ByDateSourcePlan:
    if end_date < start_date:
        raise ValueError("end-date 不能早于 start-date。")
    source_root = _source_root(lake_root=lake_root, freq=freq)
    batches: list[ByDateSourceBatchPlan] = []
    for partition in sorted(source_root.glob("trade_date=*")):
        trade_date = _parse_partition_date(partition)
        if trade_date is None or trade_date < start_date or trade_date > end_date:
            continue
        files = tuple(sorted(partition.glob("*.parquet")))
        if files:
            batches.append(ByDateSourceBatchPlan(trade_date=trade_date, files=files))
    if freq in RAW_FREQS:
        _require_clean_next_gate_for_trade_dates(lake_root=lake_root, freq=freq, trade_dates=[batch.trade_date for batch in batches])
    return ByDateSourcePlan(
        trade_dates=tuple(batch.trade_date for batch in batches),
        batches=tuple(batches),
    )


def iter_stk_mins_by_date_source_batches(
    *,
    lake_root: Path,
    freq: int,
    start_date: date,
    end_date: date,
    plan: ByDateSourcePlan | None = None,
):
    source_plan = plan or plan_stk_mins_by_date_source_batches(
        lake_root=lake_root,
        freq=freq,
        start_date=start_date,
        end_date=end_date,
    )
    batch_count = len(source_plan.batches)
    for batch_index, batch in enumerate(source_plan.batches, start=1):
        rows = read_parquet_files(list(batch.files))
        normalized_rows = [_normalize_source_row(row, expected_freq=freq) for row in rows]
        if normalized_rows:
            yield ByDateSourceBatch(
                trade_date=batch.trade_date,
                batch_index=batch_index,
                batch_count=batch_count,
                files=batch.files,
                rows=sorted(normalized_rows, key=lambda row: (row["ts_code"], row["trade_time"])),
            )


def iter_stk_mins_research_source_batches(
    *,
    lake_root: Path,
    freq: int,
    start_date: date,
    end_date: date,
    plan: ResearchSourcePlan | None = None,
):
    source_plan = plan or plan_stk_mins_research_source_batches(
        lake_root=lake_root,
        freq=freq,
        start_date=start_date,
        end_date=end_date,
    )
    batch_count = len(source_plan.batches)
    for batch_index, batch in enumerate(source_plan.batches, start=1):
        rows = read_parquet_files(list(batch.files))
        normalized_rows = [
            _normalize_source_row(row, expected_freq=freq)
            for row in rows
            if start_date <= _parse_trade_time(row.get("trade_time")).date() <= end_date
        ]
        if normalized_rows:
            yield ResearchSourceBatch(
                trade_month=batch.trade_month,
                bucket=batch.bucket,
                batch_index=batch_index,
                batch_count=batch_count,
                rows=sorted(normalized_rows, key=lambda row: (row["ts_code"], row["trade_time"])),
            )


def _source_files(*, lake_root: Path, freq: int, start_date: date, end_date: date) -> list[Path]:
    source_root = _source_root(lake_root=lake_root, freq=freq)
    files: list[Path] = []
    trade_dates: list[date] = []
    for partition in sorted(source_root.glob("trade_date=*")):
        trade_date = _parse_partition_date(partition)
        if trade_date is None or trade_date < start_date or trade_date > end_date:
            continue
        partition_files = sorted(partition.glob("*.parquet"))
        if partition_files:
            trade_dates.append(trade_date)
            files.extend(partition_files)
    if freq in RAW_FREQS:
        _require_clean_next_gate_for_trade_dates(lake_root=lake_root, freq=freq, trade_dates=trade_dates)
    return files


def _source_root(*, lake_root: Path, freq: int) -> Path:
    if freq in RAW_FREQS:
        return lake_root / "research" / "stk_mins_by_date_clean_next" / f"freq={freq}"
    if freq in DERIVED_FREQS:
        return lake_root / "derived" / "stk_mins_by_date" / f"freq={freq}"
    raise ValueError("指标源读取仅支持 freq=1/5/15/30/60/90/120。")


def _require_clean_next_gate_for_trade_dates(*, lake_root: Path, freq: int, trade_dates: list[date]) -> None:
    service = CleanNextPartitionGateService(lake_root=lake_root)
    for trade_date in sorted(set(trade_dates)):
        service.require_passed(freq=freq, trade_date=trade_date)


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
