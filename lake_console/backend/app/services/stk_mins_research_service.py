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


def _validate_trade_month(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ValueError("trade_month 必须是 YYYY-MM 格式。") from exc


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
