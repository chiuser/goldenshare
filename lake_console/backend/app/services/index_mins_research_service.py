from __future__ import annotations

import hashlib
import math
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.index_mins_universe_filter import load_index_mins_universe_for_range
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_files,
    read_parquet_row_count,
    replace_directory_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService
from lake_console.backend.app.sync.helpers.dates import load_open_trade_dates


INDEX_MINS_RESEARCH_FREQS = frozenset({"1min", "5min", "15min", "30min", "60min"})
INDEX_MINS_RESEARCH_BUCKET_COUNT = 16
INDEX_MINS_BARS_PER_CODE = {
    "1min": 241,
    "5min": 49,
    "15min": 17,
    "30min": 9,
    "60min": 5,
}


class IndexMinsResearchService:
    def __init__(self, *, lake_root: Path, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.progress = progress or print

    def rebuild_month(self, *, freq: str, trade_month: str) -> dict[str, Any]:
        normalized_freq = _normalize_freq(freq)
        month_start, month_end = _parse_trade_month(trade_month)

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("research-index-mins")
        LakeRootService(self.lake_root).require_ready_for_write()

        gate = _validate_research_source_month(
            lake_root=self.lake_root,
            freq=normalized_freq,
            trade_month=trade_month,
            month_start=month_start,
            month_end=month_end,
        )
        source_rows = read_parquet_files(gate.source_files)
        buckets = _bucket_rows(rows=source_rows, bucket_count=INDEX_MINS_RESEARCH_BUCKET_COUNT)

        tmp_month = (
            self.lake_root
            / "_tmp"
            / run_id
            / "research"
            / "index_mins_by_symbol_month"
            / f"freq={normalized_freq}"
            / f"trade_month={trade_month}"
        )
        final_month = (
            self.lake_root
            / "research"
            / "index_mins_by_symbol_month"
            / f"freq={normalized_freq}"
            / f"trade_month={trade_month}"
        )

        written_total = 0
        self.progress(
            f"[research_index_mins] start run_id={run_id} freq={normalized_freq} trade_month={trade_month} "
            f"trade_dates={len(gate.trade_dates)} source_files={len(gate.source_files)} "
            f"source_rows={len(source_rows)} buckets={INDEX_MINS_RESEARCH_BUCKET_COUNT}"
        )
        for bucket_label, bucket_rows in sorted(buckets.items()):
            bucket_dir = tmp_month / f"bucket={bucket_label}"
            tmp_file = bucket_dir / "part-000.parquet"
            written = write_rows_to_parquet(
                sorted(
                    bucket_rows,
                    key=lambda item: (str(item.get("ts_code") or ""), item.get("trade_time")),
                ),
                tmp_file,
            )
            validated = read_parquet_row_count(tmp_file)
            if validated != written:
                raise RuntimeError(
                    f"index_mins research bucket 校验失败：written={written} validated={validated} file={tmp_file}"
                )
            written_total += written
            self.progress(f"[research_index_mins] bucket={bucket_label} written={written} accumulated={written_total}")

        replace_directory_atomically(
            tmp_dir=tmp_month,
            final_dir=final_month,
            backup_root=self.lake_root / "_tmp" / run_id / "_backup",
        )
        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "index_mins",
            "operation": "research_index_mins",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "source_node_key": "raw_tushare_by_date",
            "freq": normalized_freq,
            "trade_month": trade_month,
            "input_trade_dates": [item.isoformat() for item in gate.trade_dates],
            "source_files": len(gate.source_files),
            "source_rows": len(source_rows),
            "bucket_count": INDEX_MINS_RESEARCH_BUCKET_COUNT,
            "written_rows": written_total,
            "output": str(final_month),
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[research_index_mins] done freq={normalized_freq} trade_month={trade_month} "
            f"trade_dates={len(gate.trade_dates)} source_rows={len(source_rows)} "
            f"written={written_total} output={final_month} elapsed={math.ceil(elapsed)}s"
        )
        return summary

    def rebuild_range(self, *, freqs: list[str], start_month: str, end_month: str) -> dict[str, Any]:
        normalized_freqs = [_normalize_freq(item) for item in freqs]
        if not normalized_freqs:
            raise ValueError("rebuild-index-mins-research-range 必须至少指定一个 freq。")
        trade_months = _list_trade_months(start_month=start_month, end_month=end_month)
        if not trade_months:
            raise ValueError("rebuild-index-mins-research-range 没有可重建月份。")

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("research-index-mins-range")
        units_total = len(normalized_freqs) * len(trade_months)
        self.progress(
            f"[research_index_mins_range] start run_id={run_id} start_month={start_month} "
            f"end_month={end_month} months={len(trade_months)} freqs={normalized_freqs} units_total={units_total}"
        )

        summaries: list[dict[str, Any]] = []
        total_source_rows = 0
        total_written_rows = 0
        unit_index = 0
        for current_freq in normalized_freqs:
            for trade_month in trade_months:
                unit_index += 1
                self.progress(
                    f"[research_index_mins_range] unit={unit_index}/{units_total} "
                    f"freq={current_freq} trade_month={trade_month}"
                )
                summary = self.rebuild_month(freq=current_freq, trade_month=trade_month)
                summaries.append(summary)
                total_source_rows += int(summary.get("source_rows") or 0)
                total_written_rows += int(summary.get("written_rows") or 0)

        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "index_mins",
            "operation": "research_index_mins_range",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "start_month": start_month,
            "end_month": end_month,
            "trade_months": trade_months,
            "freqs": normalized_freqs,
            "units_total": units_total,
            "source_rows": total_source_rows,
            "written_rows": total_written_rows,
            "unit_summaries": summaries,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[research_index_mins_range] done start_month={start_month} end_month={end_month} "
            f"months={len(trade_months)} freqs={normalized_freqs} source_rows={total_source_rows} "
            f"written={total_written_rows} elapsed={math.ceil(elapsed)}s"
        )
        return summary


class _ResearchSourceGateResult:
    def __init__(self, *, trade_dates: list[date], source_files: list[Path]) -> None:
        self.trade_dates = trade_dates
        self.source_files = source_files


def _validate_research_source_month(
    *,
    lake_root: Path,
    freq: str,
    trade_month: str,
    month_start: date,
    month_end: date,
) -> _ResearchSourceGateResult:
    trade_dates = load_open_trade_dates(lake_root=lake_root, start_date=month_start, end_date=month_end)
    if not trade_dates:
        raise RuntimeError(f"index_mins research 目标月份没有开市日：trade_month={trade_month}")

    universe = load_index_mins_universe_for_range(
        lake_root=lake_root,
        start_date=trade_dates[0],
        end_date=trade_dates[-1],
    )
    expected_per_code_rows = INDEX_MINS_BARS_PER_CODE[freq]
    source_files: list[Path] = []
    for trade_date in trade_dates:
        partition_dir = (
            lake_root
            / "raw_tushare"
            / "index_mins_by_date"
            / f"freq={freq}"
            / f"trade_date={trade_date.isoformat()}"
        )
        partition_files = sorted(partition_dir.glob("*.parquet"))
        if not partition_files:
            raise RuntimeError(
                "index_mins research 缺少正式 raw 分区："
                f"freq={freq} trade_date={trade_date.isoformat()} "
                "请先完成 sync-dataset index_mins 或 repair-index-mins-from-1m。"
            )
        expected_rows = universe.effective_code_count_on(trade_date=trade_date) * expected_per_code_rows
        actual_rows = sum(read_parquet_row_count(item) for item in partition_files)
        if actual_rows <= 0:
            raise RuntimeError(
                f"index_mins research 遇到 0 行正式分区：freq={freq} trade_date={trade_date.isoformat()}"
            )
        if actual_rows != expected_rows:
            raise RuntimeError(
                "index_mins research 分区行数不满足 completeness gate："
                f"freq={freq} trade_date={trade_date.isoformat()} expected_rows={expected_rows} actual_rows={actual_rows}"
            )
        source_files.extend(partition_files)
    return _ResearchSourceGateResult(trade_dates=trade_dates, source_files=source_files)


def _bucket_rows(*, rows: list[dict[str, Any]], bucket_count: int) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip()
        if not ts_code:
            continue
        bucket = _stable_bucket(ts_code=ts_code, bucket_count=bucket_count)
        bucket_label = f"{bucket:02d}"
        buckets[bucket_label].append(row)
    return buckets


def _stable_bucket(*, ts_code: str, bucket_count: int) -> int:
    digest = hashlib.sha256(ts_code.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % bucket_count


def _normalize_freq(value: str) -> str:
    normalized = str(value).strip()
    if normalized not in INDEX_MINS_RESEARCH_FREQS:
        allowed = ",".join(sorted(INDEX_MINS_RESEARCH_FREQS))
        raise ValueError(f"index_mins research 仅支持 freq={allowed}。")
    return normalized


def _list_trade_months(*, start_month: str, end_month: str) -> list[str]:
    start_year, start_month_value = _parse_trade_month_key(start_month)
    end_year, end_month_value = _parse_trade_month_key(end_month)
    if (end_year, end_month_value) < (start_year, start_month_value):
        raise ValueError("end-month 不能早于 start-month。")

    months: list[str] = []
    year = start_year
    month = start_month_value
    while (year, month) <= (end_year, end_month_value):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def _parse_trade_month(value: str) -> tuple[date, date]:
    year, month = _parse_trade_month_key(value)
    month_start = date(year, month, 1)
    if month == 12:
        next_month_start = date(year + 1, 1, 1)
    else:
        next_month_start = date(year, month + 1, 1)
    month_end = next_month_start - timedelta(days=1)
    return month_start, month_end


def _parse_trade_month_key(value: str) -> tuple[int, int]:
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ValueError("trade_month 必须是 YYYY-MM 格式。") from exc
    return parsed.year, parsed.month


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
