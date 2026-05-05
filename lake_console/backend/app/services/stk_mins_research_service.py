from __future__ import annotations

import hashlib
import math
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_files,
    read_parquet_row_count,
    replace_directory_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


RAW_FREQS = {1, 5, 15, 30, 60}
DERIVED_FREQS = {90, 120}


class StkMinsResearchService:
    def __init__(self, *, lake_root: Path, bucket_count: int, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.bucket_count = bucket_count
        self.progress = progress or print

    def rebuild_month(self, *, freq: int, trade_month: str) -> dict[str, Any]:
        if freq not in RAW_FREQS | DERIVED_FREQS:
            raise ValueError("research 重排仅支持 freq=1/5/15/30/60/90/120。")
        if self.bucket_count <= 0:
            raise ValueError("bucket_count 必须大于 0。")
        _validate_trade_month(trade_month)

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("research-stk-mins")
        LakeRootService(self.lake_root).require_ready_for_write()
        source_layer = "raw_tushare" if freq in RAW_FREQS else "derived"
        source_root = self.lake_root / source_layer / "stk_mins_by_date" / f"freq={freq}"
        source_files = _month_source_files(source_root=source_root, trade_month=trade_month)
        if not source_files:
            raise RuntimeError(f"缺少可重排源文件：{source_root}/trade_date={trade_month}-*/")

        rows = read_parquet_files(source_files)
        buckets = bucket_rows(rows=rows, bucket_count=self.bucket_count)
        tmp_month = (
            self.lake_root
            / "_tmp"
            / run_id
            / "research"
            / "stk_mins_by_symbol_month"
            / f"freq={freq}"
            / f"trade_month={trade_month}"
        )
        final_month = (
            self.lake_root
            / "research"
            / "stk_mins_by_symbol_month"
            / f"freq={freq}"
            / f"trade_month={trade_month}"
        )
        written_total = 0
        self.progress(
            f"[research_stk_mins] start run_id={run_id} freq={freq} trade_month={trade_month} "
            f"source_files={len(source_files)} source_rows={len(rows)} buckets={self.bucket_count}"
        )
        for bucket, bucket_rows_value in sorted(buckets.items()):
            bucket_dir = tmp_month / f"bucket={bucket}"
            tmp_file = bucket_dir / "part-000.parquet"
            written = write_rows_to_parquet(sorted(bucket_rows_value, key=lambda item: (str(item.get("ts_code") or ""), str(item.get("trade_time") or ""))), tmp_file)
            validated = read_parquet_row_count(tmp_file)
            if validated != written:
                raise RuntimeError(f"research bucket 校验失败：written={written} validated={validated} file={tmp_file}")
            written_total += written
            self.progress(f"[research_stk_mins] bucket={bucket} written={written} accumulated={written_total}")

        replace_directory_atomically(
            tmp_dir=tmp_month,
            final_dir=final_month,
            backup_root=self.lake_root / "_tmp" / run_id / "_backup",
        )
        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "stk_mins",
            "operation": "research_stk_mins",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "freq": freq,
            "trade_month": trade_month,
            "source_layer": source_layer,
            "source_files": len(source_files),
            "source_rows": len(rows),
            "bucket_count": self.bucket_count,
            "written_rows": written_total,
            "output": str(final_month),
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[research_stk_mins] done freq={freq} trade_month={trade_month} "
            f"source_rows={len(rows)} written={written_total} output={final_month} elapsed={math.ceil(elapsed)}s"
        )
        return summary

    def rebuild_range(self, *, freqs: list[int], start_month: str, end_month: str) -> dict[str, Any]:
        if not freqs:
            raise ValueError("rebuild-stk-mins-research-range 必须至少指定一个 freq。")
        invalid_freqs = sorted(set(freqs) - (RAW_FREQS | DERIVED_FREQS))
        if invalid_freqs:
            raise ValueError(f"research 重排仅支持 freq=1/5/15/30/60/90/120，不支持 {invalid_freqs}。")
        if self.bucket_count <= 0:
            raise ValueError("bucket_count 必须大于 0。")
        months = list_trade_months(start_month=start_month, end_month=end_month)
        if not months:
            raise ValueError("rebuild-stk-mins-research-range 没有可重建月份。")

        LakeRootService(self.lake_root).require_ready_for_write()
        missing_sources = _missing_month_sources(lake_root=self.lake_root, freqs=freqs, trade_months=months)
        if missing_sources:
            preview = "\n".join(str(item) for item in missing_sources[:10])
            suffix = "" if len(missing_sources) <= 10 else f"\n... 另有 {len(missing_sources) - 10} 个缺失源月份"
            raise RuntimeError(f"rebuild-stk-mins-research-range 缺少源文件，未执行任何写入：\n{preview}{suffix}")

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("research-stk-mins-range")
        units_total = len(freqs) * len(months)
        self.progress(
            f"[research_stk_mins_range] start run_id={run_id} start_month={start_month} "
            f"end_month={end_month} months={len(months)} freqs={freqs} units_total={units_total}"
        )

        summaries: list[dict[str, Any]] = []
        total_source_rows = 0
        total_written_rows = 0
        unit = 0
        for freq in freqs:
            for trade_month in months:
                unit += 1
                self.progress(
                    f"[research_stk_mins_range] unit={unit}/{units_total} "
                    f"freq={freq} trade_month={trade_month}"
                )
                summary = self.rebuild_month(freq=freq, trade_month=trade_month)
                summaries.append(summary)
                total_source_rows += int(summary.get("source_rows") or 0)
                total_written_rows += int(summary.get("written_rows") or 0)

        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "stk_mins",
            "operation": "research_stk_mins_range",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "start_month": start_month,
            "end_month": end_month,
            "trade_months": months,
            "freqs": freqs,
            "units_total": units_total,
            "source_rows": total_source_rows,
            "written_rows": total_written_rows,
            "unit_summaries": summaries,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[research_stk_mins_range] done start_month={start_month} end_month={end_month} "
            f"months={len(months)} freqs={freqs} source_rows={total_source_rows} "
            f"written={total_written_rows} elapsed={math.ceil(elapsed)}s"
        )
        return summary


def bucket_rows(*, rows: list[dict[str, Any]], bucket_count: int) -> dict[int, list[dict[str, Any]]]:
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip()
        if not ts_code:
            continue
        bucket = stable_bucket(ts_code=ts_code, bucket_count=bucket_count)
        buckets[bucket].append(row)
    return buckets


def stable_bucket(*, ts_code: str, bucket_count: int) -> int:
    digest = hashlib.sha256(ts_code.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % bucket_count


def _month_source_files(*, source_root: Path, trade_month: str) -> list[Path]:
    files: list[Path] = []
    for partition in sorted(source_root.glob(f"trade_date={trade_month}-*")):
        files.extend(sorted(partition.glob("*.parquet")))
    return files


def list_trade_months(*, start_month: str, end_month: str) -> list[str]:
    start_year, start_month_value = _parse_trade_month(start_month)
    end_year, end_month_value = _parse_trade_month(end_month)
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


def _missing_month_sources(*, lake_root: Path, freqs: list[int], trade_months: list[str]) -> list[Path]:
    missing: list[Path] = []
    for freq in freqs:
        source_layer = "raw_tushare" if freq in RAW_FREQS else "derived"
        source_root = lake_root / source_layer / "stk_mins_by_date" / f"freq={freq}"
        for trade_month in trade_months:
            if not _month_source_files(source_root=source_root, trade_month=trade_month):
                missing.append(source_root / f"trade_date={trade_month}-*")
    return missing


def _validate_trade_month(value: str) -> None:
    _parse_trade_month(value)


def _parse_trade_month(value: str) -> tuple[int, int]:
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ValueError("trade_month 必须是 YYYY-MM 格式。") from exc
    return parsed.year, parsed.month


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
