from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.catalog.tushare_stk_mins import STOCK_BASIC_FIELDS
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    replace_file_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService
from lake_console.backend.app.services.tushare_client import TushareLakeClient


STOCK_BASIC_STATUSES = ("L", "D", "P")


class TushareStockBasicSyncService:
    def __init__(
        self,
        *,
        lake_root: Path,
        client: TushareLakeClient,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.lake_root = lake_root
        self.client = client
        self.progress = progress or print

    def sync(self) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("stock-basic")
        LakeRootService(self.lake_root).require_ready_for_write()
        self.progress(f"[stock_basic] start run_id={run_id}")

        rows_by_code: dict[str, dict[str, Any]] = {}
        fetched_total = 0
        for status in STOCK_BASIC_STATUSES:
            rows = self.client.stock_basic(list_status=status, fields=STOCK_BASIC_FIELDS)
            fetched_total += len(rows)
            self.progress(f"[stock_basic] status={status} fetched={len(rows)} total_fetched={fetched_total}")
            for row in rows:
                normalized = _normalize_stock_basic_row(row, fallback_status=status)
                ts_code = normalized.get("ts_code")
                if not ts_code:
                    continue
                rows_by_code[str(ts_code)] = normalized

        output_rows = sorted(rows_by_code.values(), key=lambda item: str(item.get("ts_code") or ""))
        if not output_rows:
            raise RuntimeError("stock_basic 未获取到任何有效股票记录，拒绝覆盖本地股票池。")

        backup_root = self.lake_root / "_tmp" / run_id / "_backup"
        raw_tmp = self.lake_root / "_tmp" / run_id / "raw_tushare" / "stock_basic" / "current" / "part-000.parquet"
        raw_final = self.lake_root / "raw_tushare" / "stock_basic" / "current" / "part-000.parquet"
        universe_tmp = self.lake_root / "_tmp" / run_id / "manifest" / "security_universe" / "tushare_stock_basic.parquet"
        universe_final = self.lake_root / "manifest" / "security_universe" / "tushare_stock_basic.parquet"

        self.progress(f"[stock_basic] writing raw rows={len(output_rows)} output={raw_tmp}")
        raw_written = _write_and_validate(rows=output_rows, tmp_file=raw_tmp)
        self.progress(f"[stock_basic] writing universe rows={len(output_rows)} output={universe_tmp}")
        universe_written = _write_and_validate(rows=output_rows, tmp_file=universe_tmp)

        replace_file_atomically(tmp_file=raw_tmp, final_file=raw_final, backup_root=backup_root / "raw_stock_basic")
        replace_file_atomically(tmp_file=universe_tmp, final_file=universe_final, backup_root=backup_root / "security_universe")
        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "stock_basic",
            "api_name": "stock_basic",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "fetched_rows": fetched_total,
            "written_rows": raw_written,
            "raw_output": str(raw_final),
            "universe_output": str(universe_final),
            "universe_written_rows": universe_written,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[stock_basic] done fetched={fetched_total} raw_written={raw_written} universe_written={universe_written} "
            f"raw_output={raw_final} universe_output={universe_final} elapsed={math.ceil(elapsed)}s"
        )
        return summary


def _normalize_stock_basic_row(row: dict[str, Any], *, fallback_status: str) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for field in STOCK_BASIC_FIELDS:
        value = row.get(field)
        if field == "list_status" and (value is None or value == ""):
            value = fallback_status
        normalized[field] = None if _is_nan(value) else value
    return normalized


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _write_and_validate(*, rows: list[dict[str, Any]], tmp_file: Path) -> int:
    written = write_rows_to_parquet(rows, tmp_file)
    validated = read_parquet_row_count(tmp_file)
    if validated != written:
        raise RuntimeError(f"stock_basic Parquet 校验失败：written={written} validated={validated} file={tmp_file}")
    return written


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
