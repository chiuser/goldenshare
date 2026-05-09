from __future__ import annotations

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
from lake_console.backend.app.services.stk_mins_research_service import list_trade_months, stable_bucket
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


class StkMinsIndicatorResearchService:
    def __init__(self, *, lake_root: Path, bucket_count: int, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.bucket_count = bucket_count
        self.progress = progress or print

    def rebuild_month(self, *, indicator: str, params_key: str, freq: int, trade_month: str) -> dict[str, Any]:
        indicator_key = _validate_indicator(indicator)
        params_key_value = _validate_params_key(params_key)
        if self.bucket_count <= 0:
            raise ValueError("bucket_count 必须大于 0。")
        _validate_trade_month(trade_month)

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("research-stk-mins-indicator")
        LakeRootService(self.lake_root).require_ready_for_write()
        source_files = _month_source_files(
            lake_root=self.lake_root,
            indicator=indicator_key,
            params_key=params_key_value,
            freq=freq,
            trade_month=trade_month,
        )
        if not source_files:
            raise RuntimeError(
                "缺少可重排指标 by_date 文件："
                f"derived/stk_mins_indicators_by_date/indicator={indicator_key}/"
                f"params_key={params_key_value}/freq={freq}/trade_date={trade_month}-*/"
            )

        rows = read_parquet_files(source_files)
        buckets = _bucket_indicator_rows(rows=rows, bucket_count=self.bucket_count)
        tmp_month = _tmp_month_path(
            lake_root=self.lake_root,
            run_id=run_id,
            indicator=indicator_key,
            params_key=params_key_value,
            freq=freq,
            trade_month=trade_month,
        )
        final_month = _final_month_path(
            lake_root=self.lake_root,
            indicator=indicator_key,
            params_key=params_key_value,
            freq=freq,
            trade_month=trade_month,
        )
        written_total = 0
        self.progress(
            f"[research_stk_mins_indicator] start run_id={run_id} indicator={indicator_key} "
            f"params_key={params_key_value} freq={freq} trade_month={trade_month} "
            f"source_files={len(source_files)} source_rows={len(rows)} buckets={self.bucket_count}"
        )
        for bucket, bucket_rows_value in sorted(buckets.items()):
            bucket_dir = tmp_month / f"bucket={bucket}"
            tmp_file = bucket_dir / "part-000.parquet"
            sorted_rows = sorted(bucket_rows_value, key=lambda item: (str(item.get("ts_code") or ""), str(item.get("trade_time") or "")))
            written = write_rows_to_parquet(sorted_rows, tmp_file)
            validated = read_parquet_row_count(tmp_file)
            if validated != written:
                raise RuntimeError(f"指标 research bucket 校验失败：written={written} validated={validated} file={tmp_file}")
            written_total += written
            self.progress(f"[research_stk_mins_indicator] bucket={bucket} written={written} accumulated={written_total}")

        replace_directory_atomically(
            tmp_dir=tmp_month,
            final_dir=final_month,
            backup_root=self.lake_root / "_tmp" / run_id / "_backup",
        )
        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "stk_mins",
            "operation": "research_stk_mins_indicator",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "indicator": indicator_key,
            "params_key": params_key_value,
            "freq": freq,
            "trade_month": trade_month,
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
            f"[research_stk_mins_indicator] done indicator={indicator_key} params_key={params_key_value} "
            f"freq={freq} trade_month={trade_month} source_rows={len(rows)} written={written_total} "
            f"elapsed={math.ceil(elapsed)}s"
        )
        return summary

    def rebuild_range(self, *, indicator: str, params_key: str, freq: int, start_month: str, end_month: str) -> dict[str, Any]:
        months = list_trade_months(start_month=start_month, end_month=end_month)
        if not months:
            raise ValueError("rebuild-stk-mins-indicator-research-range 没有可重建月份。")
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        summaries: list[dict[str, Any]] = []
        total_source_rows = 0
        total_written_rows = 0
        self.progress(
            f"[research_stk_mins_indicator_range] start indicator={indicator} params_key={params_key} "
            f"freq={freq} start_month={start_month} end_month={end_month} months={len(months)}"
        )
        for index, trade_month in enumerate(months, start=1):
            self.progress(f"[research_stk_mins_indicator_range] unit={index}/{len(months)} trade_month={trade_month}")
            summary = self.rebuild_month(indicator=indicator, params_key=params_key, freq=freq, trade_month=trade_month)
            summaries.append(summary)
            total_source_rows += int(summary.get("source_rows") or 0)
            total_written_rows += int(summary.get("written_rows") or 0)
        elapsed = time.monotonic() - started
        return {
            "dataset_key": "stk_mins",
            "operation": "research_stk_mins_indicator_range",
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "indicator": indicator,
            "params_key": params_key,
            "freq": freq,
            "start_month": start_month,
            "end_month": end_month,
            "trade_months": months,
            "units_total": len(months),
            "source_rows": total_source_rows,
            "written_rows": total_written_rows,
            "unit_summaries": summaries,
            "elapsed_seconds": round(elapsed, 3),
        }


def _bucket_indicator_rows(*, rows: list[dict[str, Any]], bucket_count: int) -> dict[int, list[dict[str, Any]]]:
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip()
        if not ts_code:
            continue
        buckets[stable_bucket(ts_code=ts_code, bucket_count=bucket_count)].append(row)
    return buckets


def _month_source_files(*, lake_root: Path, indicator: str, params_key: str, freq: int, trade_month: str) -> list[Path]:
    source_root = (
        lake_root
        / "derived"
        / "stk_mins_indicators_by_date"
        / f"indicator={indicator}"
        / f"params_key={params_key}"
        / f"freq={freq}"
    )
    files: list[Path] = []
    for partition in sorted(source_root.glob(f"trade_date={trade_month}-*")):
        files.extend(sorted(partition.glob("*.parquet")))
    return files


def _final_month_path(*, lake_root: Path, indicator: str, params_key: str, freq: int, trade_month: str) -> Path:
    return (
        lake_root
        / "research"
        / "stk_mins_indicators_by_symbol_month"
        / f"indicator={indicator}"
        / f"params_key={params_key}"
        / f"freq={freq}"
        / f"trade_month={trade_month}"
    )


def _tmp_month_path(*, lake_root: Path, run_id: str, indicator: str, params_key: str, freq: int, trade_month: str) -> Path:
    return (
        lake_root
        / "_tmp"
        / run_id
        / "research"
        / "stk_mins_indicators_by_symbol_month"
        / f"indicator={indicator}"
        / f"params_key={params_key}"
        / f"freq={freq}"
        / f"trade_month={trade_month}"
    )


def _validate_indicator(value: str) -> str:
    indicator = str(value or "").strip()
    if indicator != "macd":
        raise ValueError("当前仅支持 indicator=macd。")
    return indicator


def _validate_params_key(value: str) -> str:
    params_key = str(value or "").strip()
    if params_key != "12_26_9":
        raise ValueError("当前仅支持 params_key=12_26_9。")
    return params_key


def _validate_trade_month(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ValueError("trade_month 必须是 YYYY-MM 格式。") from exc


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
